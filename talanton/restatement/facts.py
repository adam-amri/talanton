"""Picking the right figures in the SEC "companyfacts" document.

The same figure appears several times: fiscal 2024 is in the 2024 10-K, then as
a comparative in the 2025 and 2026 ones. The `fy` and `fp` fields describe the
filing, not the period of the figure, so they are never trusted. Every rule
below reasons on start and end dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

YEAR_MIN_DAYS, YEAR_MAX_DAYS = 350, 380   # covers 52- and 53-week fiscal years
TOLERANCE_DAYS = 10


@dataclass(frozen=True)
class Fact:
    tag: str
    unit: str
    start: date | None      # None for a balance-sheet figure (instant)
    end: date
    value: float
    form: str
    filed: date
    accession: str          # SEC accession number, for traceability

    @property
    def days(self) -> int | None:
        return None if self.start is None else (self.end - self.start).days

    @property
    def annual(self) -> bool:
        return (self.start is not None and self.form == "10-K"
                and YEAR_MIN_DAYS <= self.days <= YEAR_MAX_DAYS)


class Facts:
    """Access to the facts of a company, by tag."""

    FORMS = ("10-K", "10-Q")

    def __init__(self, raw: dict):
        self.name: str = raw.get("entityName", "")
        self.cik: int = int(raw.get("cik", 0))
        self._raw = raw.get("facts", {})
        self._cache: dict[tuple[str, str], list[Fact]] = {}

    def of(self, tag: str, namespace: str = "us-gaap") -> list[Fact]:
        key = (namespace, tag)
        if key not in self._cache:
            facts: list[Fact] = []
            node = self._raw.get(namespace, {}).get(tag)
            if node:
                for unit, rows in node.get("units", {}).items():
                    for e in rows:
                        if e.get("form") not in self.FORMS:
                            continue
                        facts.append(Fact(
                            tag=tag, unit=unit,
                            start=date.fromisoformat(e["start"]) if e.get("start") else None,
                            end=date.fromisoformat(e["end"]), value=float(e["val"]),
                            form=e["form"], filed=date.fromisoformat(e["filed"]),
                            accession=e.get("accn", ""),
                        ))
            self._cache[key] = facts
        return self._cache[key]

    def exists(self, tag: str) -> bool:
        return bool(self.of(tag))

    # -- calendar -----------------------------------------------------------
    def fiscal_years(self, anchor_tags: tuple[str, ...]) -> list[tuple[date, date]]:
        """Chronological list of published fiscal years: (start, end)."""
        seen: dict[date, date] = {}
        for tag in anchor_tags:
            for f in self.of(tag):
                if f.annual:
                    seen[f.end] = f.start
        return [(seen[end], end) for end in sorted(seen)]

    def last_quarter(self, anchor_tags: tuple[str, ...], year_end: date) -> date | None:
        """End of the last quarter published after the annual close (None if there is none)."""
        ends = [f.end for tag in anchor_tags for f in self.of(tag)
                if f.form == "10-Q" and f.end > year_end]
        return max(ends) if ends else None

    # -- reading a value ----------------------------------------------------
    @staticmethod
    def _latest_filed(candidates: list[Fact]) -> Fact | None:
        """Among several publications of the same figure, keeps the last one filed."""
        return max(candidates, key=lambda f: f.filed) if candidates else None

    def annual(self, tag: str, end: date) -> Fact | None:
        return self._latest_filed([f for f in self.of(tag) if f.annual and f.end == end])

    def instant(self, tag: str, end: date) -> Fact | None:
        return self._latest_filed([f for f in self.of(tag) if f.start is None and f.end == end])

    def year_to_date(self, tag: str, year_start: date, end: date) -> Fact | None:
        """Cumulative figure from the start of the fiscal year to `end` (6 months, 9 months...).

        A 10-Q gives both the single quarter and the year-to-date figure: the
        figure must start at the beginning of the fiscal year, else nothing is returned.
        """
        candidates = [f for f in self.of(tag)
                      if f.start is not None and f.end == end and f.days < YEAR_MIN_DAYS
                      and abs((f.start - year_start).days) <= TOLERANCE_DAYS]
        return self._latest_filed(candidates)

    def prior_year_to_date(self, tag: str, prior_year_start: date, end: date) -> Fact | None:
        """Same cumulative figure one year earlier (ending about 365 days before `end`)."""
        target = end - timedelta(days=365)
        candidates = [f for f in self.of(tag)
                      if f.start is not None and f.days < YEAR_MIN_DAYS
                      and abs((f.end - target).days) <= TOLERANCE_DAYS
                      and abs((f.start - prior_year_start).days) <= TOLERANCE_DAYS]
        return self._latest_filed(candidates)
