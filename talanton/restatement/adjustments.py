"""Analyst adjustments: the layer of judgment, written in a TOML file.

Example (examples/adjustments/MAT.toml):

    [capex]
    source = "10-K, cash-flow statement: two investing lines added together"
    "2025-12-31" = 181.992

    [ebitda]
    source = "Q3 2026 earnings release: tariff refunds"
    "LTM" = -88.0

    [net_income]
    source = "Non-recurring gain"
    "LTM" = -150.0

Amounts are in millions. Keys are fiscal year ends (YYYY-MM-DD) or "LTM". An
EBITDA adjustment is added to reported EBITDA: a negative amount removes a
non-recurring gain, a positive amount adds back a charge. A net income
adjustment (after tax) is only used for the P/E of the comparables.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Adjustments:
    capex: dict[str, float] = field(default_factory=dict)
    ebitda: dict[str, float] = field(default_factory=dict)
    net_income: dict[str, float] = field(default_factory=dict)
    capex_source: str = ""
    ebitda_source: str = ""
    net_income_source: str = ""

    @property
    def empty(self) -> bool:
        return not (self.capex or self.ebitda or self.net_income)


def load_adjustments(file: Path | None) -> Adjustments:
    if file is None or not Path(file).exists():
        return Adjustments()
    raw = tomllib.loads(Path(file).read_text(encoding="utf-8"))
    unknown = set(raw) - {"capex", "ebitda", "net_income"}
    if unknown:
        raise ValueError(f"{file}: unknown section(s) {sorted(unknown)}. Expected [capex], [ebitda], [net_income].")
    capex, ebitda, net_income = (dict(raw.get(k, {})) for k in ("capex", "ebitda", "net_income"))
    return Adjustments(
        capex_source=str(capex.pop("source", "")),
        ebitda_source=str(ebitda.pop("source", "")),
        net_income_source=str(net_income.pop("source", "")),
        capex={k: float(v) for k, v in capex.items()},
        ebitda={k: float(v) for k, v in ebitda.items()},
        net_income={k: float(v) for k, v in net_income.items()},
    )
