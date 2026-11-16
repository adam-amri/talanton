"""Settings that shape the model itself (as opposed to assumptions, which are numbers)."""

from __future__ import annotations

from dataclasses import dataclass, field, fields

BETA_METHODS = ("auto", "regression", "sector")
MIN_YEARS, MAX_YEARS = 6, 10


@dataclass
class Settings:
    years: int = 6                   # projected fiscal years; the LBO holding period is years - 1
    history_years: int = 5           # fiscal years of published accounts shown
    beta_method: str = "auto"        # auto | regression | sector
    industry: str | None = None      # Damodaran industry name; None: deduced from the SIC code
    include_leases: bool = False     # add operating lease liabilities to the EV bridge
    theme: str = "classic"           # workbook colours: classic | midnight | forest | slate
    theme_overrides: dict[str, str] = field(default_factory=dict)
    bloomberg_formulas: bool = False  # write live Bloomberg (BDP) formulas for share prices

    def validate(self) -> None:
        if not MIN_YEARS <= self.years <= MAX_YEARS:
            raise ValueError(f"settings.years must be between {MIN_YEARS} and {MAX_YEARS} (got {self.years}).")
        if not 2 <= self.history_years <= 10:
            raise ValueError(f"settings.history_years must be between 2 and 10 (got {self.history_years}).")
        if self.beta_method not in BETA_METHODS:
            raise ValueError(f"settings.beta_method must be one of {', '.join(BETA_METHODS)} (got {self.beta_method!r}).")

    @classmethod
    def from_dict(cls, raw: dict, theme: dict | None = None) -> "Settings":
        known = {f.name for f in fields(cls)} - {"theme_overrides"}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}. Known: {', '.join(sorted(known))}.")
        settings = cls(**raw, theme_overrides=dict(theme or {}))
        settings.validate()
        return settings
