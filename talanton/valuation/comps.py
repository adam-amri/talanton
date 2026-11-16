"""Trading comparables: peer multiples and implied value of the target.

A multiple is kept only when it is meaningful: positive denominator and result
below a cap. Otherwise it is shown as "n.m." and ignored by the statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data.base import Quote
from ..data.damodaran import Industry
from ..model.assumptions import Assumptions
from ..restatement.statements import Company

MULTIPLES = ("ev_revenue", "ev_ebitda", "ev_ebit", "pe")
LABELS = {"ev_revenue": "EV / Revenue", "ev_ebitda": "EV / EBITDA", "ev_ebit": "EV / EBIT", "pe": "P/E"}


@dataclass
class Comparable:
    company: Company
    quote: Quote

    @property
    def market_cap(self) -> float:
        return self.quote.price * self.company.shares

    @property
    def enterprise_value(self) -> float:
        b = self.company.balance
        return self.market_cap + b["debt"] - b["cash"] + b["minorities"]

    def multiple(self, name: str, cap: float) -> float | None:
        ltm = self.company.ltm
        if name == "ev_revenue":
            return self.enterprise_value / ltm["revenue"] if ltm["revenue"] and ltm["revenue"] > 0 else None
        numerator, denominator = {
            "ev_ebitda": (self.enterprise_value, ltm["ebitda_adjusted"]),
            "ev_ebit": (self.enterprise_value, ltm["ebit_adjusted"]),
            "pe": (self.market_cap, ltm["net_income_adjusted"]),
        }[name]
        if denominator is None or denominator <= 0:
            return None
        m = numerator / denominator
        return m if m <= cap else None


def quartile(values: list[float], q: float) -> float | None:
    """Quartile by linear interpolation, like QUARTILE / MEDIAN in Excel."""
    v = sorted(values)
    if not v:
        return None
    pos = (len(v) - 1) * q
    low = int(pos)
    high = min(low + 1, len(v) - 1)
    return v[low] + (v[high] - v[low]) * (pos - low)


@dataclass
class Comps:
    peers: list[Comparable]
    cap: float
    stats: dict[str, dict[str, float | None]] = field(default_factory=dict)     # multiple -> q1/median/q3/min/max
    implied: dict[str, dict[str, float | None]] = field(default_factory=dict)   # multiple -> value per share
    industry: Industry | None = None                                            # sector reference, for display

    def values(self, name: str) -> list[float]:
        return [m for p in self.peers if (m := p.multiple(name, self.cap)) is not None]


def compute_statistics(peers: list[Comparable], cap: float, industry: Industry | None = None) -> Comps:
    c = Comps(peers=peers, cap=cap, industry=industry)
    for name in MULTIPLES:
        v = c.values(name)
        c.stats[name] = {
            "min": min(v) if v else None, "q1": quartile(v, 0.25), "median": quartile(v, 0.5),
            "q3": quartile(v, 0.75), "max": max(v) if v else None,
        }
    return c


def value_target(c: Comps, target: Company, a: Assumptions) -> None:
    """Applies the peer multiples to the target's LTM aggregates: value per share."""
    aggregates = {"ev_ebitda": target.ltm["ebitda_adjusted"], "ev_ebit": target.ltm["ebit_adjusted"],
                  "pe": target.ltm["net_income_adjusted"]}
    for name, aggregate in aggregates.items():
        c.implied[name] = {}
        for level in ("q1", "median", "q3"):
            m = c.stats[name][level]
            if m is None or aggregate is None:
                c.implied[name][level] = None
            elif name == "pe":
                c.implied[name][level] = m * aggregate / a.diluted_shares
            else:
                c.implied[name][level] = (m * aggregate - a.bridge) / a.diluted_shares
