"""The model config file: one TOML file that customises a run.

    # 1. Assumption overrides, at the top level. A number, or one value per projected year.
    acquisition_premium = 0.35
    ebitda_margin = [0.115, 0.12, 0.125, 0.13, 0.13, 0.13]

    # 2. Settings: how the model is built.
    [settings]
    years = 6
    beta_method = "sector"          # auto | regression | sector
    theme = "midnight"

    # 3. Workbook colours (hex), on top of the chosen theme.
    [theme]
    ink = "0B3D2E"

    # 4. Named scenarios: overrides applied on top of the base case.
    #    An absolute value, or a move relative to the base: {shift = 0.01} or {scale = 1.1}.
    [scenarios.bull]
    revenue_growth = { shift = 0.01 }
    ebitda_margin = { shift = 0.01 }
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

from .assumptions import Assumptions
from .settings import Settings

RESERVED = ("n", "notes")
SECTIONS = ("settings", "theme", "scenarios")


@dataclass
class ModelConfig:
    overrides: dict = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)
    scenarios: dict[str, dict] = field(default_factory=dict)
    origin: str = "the config"


def load_config(file: Path | None) -> ModelConfig:
    if file is None:
        return ModelConfig()
    raw = tomllib.loads(Path(file).read_text(encoding="utf-8"))
    scenarios = raw.get("scenarios", {})
    if not all(isinstance(v, dict) for v in scenarios.values()):
        raise ValueError(f"{file}: each scenario must be a table, for example [scenarios.bull].")
    return ModelConfig(
        overrides={k: v for k, v in raw.items() if k not in SECTIONS},
        settings=Settings.from_dict(raw.get("settings", {}), raw.get("theme")),
        scenarios=scenarios, origin=Path(file).name)


def _relative(key: str, current, change: dict):
    """Applies {shift = x} and/or {scale = y} to a number or to each value of a list."""
    unknown = set(change) - {"shift", "scale"}
    if unknown or not change:
        raise ValueError(f"{key}: a relative change is written {{shift = 0.01}} or {{scale = 1.1}}.")
    move = lambda v: float(v) * float(change.get("scale", 1.0)) + float(change.get("shift", 0.0))   # noqa: E731
    return [move(v) for v in current] if isinstance(current, list) else move(current)


def apply_overrides(assumptions: Assumptions, overrides: dict, origin: str = "the config") -> list[str]:
    """Replaces assumptions with the given values. Returns the names changed.

    An annual assumption takes a list of `n` values or a single number (applied
    to every year). A table {shift = ..} / {scale = ..} moves the current value.
    """
    known = {f.name for f in fields(assumptions)}
    changed = []
    for key, value in overrides.items():
        if key not in known or key in RESERVED:
            raise ValueError(f"Unknown assumption in {origin}: {key}")
        current = getattr(assumptions, key)
        relative = isinstance(value, dict)
        if relative:
            if isinstance(current, date):
                raise ValueError(f"{key}: a date cannot be shifted or scaled.")
            value = _relative(key, current, value)
        if isinstance(current, list):
            values = [float(v) for v in value] if isinstance(value, list) else [float(value)] * assumptions.n
            if len(values) != assumptions.n:
                raise ValueError(f"{key}: {assumptions.n} values expected, {len(values)} given.")
            setattr(assumptions, key, values)
        elif isinstance(current, date):
            setattr(assumptions, key, value if isinstance(value, date) else date.fromisoformat(str(value)))
        elif isinstance(current, int) and not isinstance(current, bool):
            setattr(assumptions, key, int(value))
        else:
            setattr(assumptions, key, float(value))
        assumptions.notes[key] = (f"Moved from the default by {origin}." if relative
                                  else f"Value set by {origin}.")
        changed.append(key)
    return changed
