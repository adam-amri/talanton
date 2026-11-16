"""Rates and credit spreads from FRED (Federal Reserve Bank of St. Louis).

Two access paths, same data:
  - with FRED_API_KEY: the official JSON API;
  - without a key: the public CSV export of each series (no sign-up).

Series used by Talanton, all in percent:
  DGS10         10-year Treasury yield         -> risk-free rate
  SOFR          secured overnight rate         -> floating base of LBO debt
  BAMLH0A2HYB   single-B high-yield spread     -> proxy for a leveraged-loan margin
  BAMLC0A0CM    investment-grade spread        -> information
  T10YIE        10-year breakeven inflation    -> sanity check of perpetual growth
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path

from .. import config
from .base import DataError, Observation, http_get, is_fresh

URL_API = "https://api.stlouisfed.org/fred/series/observations"
URL_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
RISK_FREE, SOFR, LOAN_SPREAD, IG_SPREAD, BREAKEVEN = "DGS10", "SOFR", "BAMLH0A2HYB", "BAMLC0A0CM", "T10YIE"
LABELS = {
    RISK_FREE: "10-year Treasury yield", SOFR: "SOFR", LOAN_SPREAD: "ICE BofA Single-B US High Yield spread",
    IG_SPREAD: "ICE BofA US Corporate (investment grade) spread", BREAKEVEN: "10-year breakeven inflation",
}
WINDOW_DAYS = 90


def parse_csv(text: str) -> list[tuple[date, float]]:
    """Reads FRED's CSV export: a date column, a value column, blanks on holidays."""
    rows = []
    for line in list(csv.reader(io.StringIO(text)))[1:]:
        if len(line) < 2 or line[1].strip() in ("", "."):
            continue
        rows.append((date.fromisoformat(line[0].strip()), float(line[1])))
    return rows


class FredClient:
    def __init__(self, cache: Path, offline: bool = False, api_key: str | None = None):
        self.cache = Path(cache) / "fred"
        self.offline = offline
        self.api_key = api_key or config.get(config.FRED)

    def _download(self, series: str) -> list[tuple[date, float]]:
        start = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()
        if self.api_key:
            response = http_get(URL_API, what=f"FRED API ({series})", params={
                "series_id": series, "api_key": self.api_key, "file_type": "json", "observation_start": start})
            try:
                rows = response.json()["observations"]
            except (KeyError, ValueError) as exc:
                raise DataError(f"FRED API ({series}): unexpected answer.") from exc
            return [(date.fromisoformat(r["date"]), float(r["value"])) for r in rows if r["value"] not in ("", ".")]
        response = http_get(URL_CSV, what=f"FRED ({series})", params={"id": series, "cosd": start})
        return parse_csv(response.text)

    def series(self, series: str) -> list[tuple[date, float]]:
        file = self.cache / f"{series}.csv"
        if file.exists() and (self.offline or is_fresh(file)):
            return parse_csv(file.read_text(encoding="utf-8"))
        if self.offline:
            raise DataError(f"Offline mode: no FRED series {series} in the cache.")
        rows = self._download(series)
        if not rows:
            raise DataError(f"FRED returned no value for {series}.")
        self.cache.mkdir(parents=True, exist_ok=True)
        file.write_text(f"observation_date,{series}\n" + "".join(f"{d.isoformat()},{v}\n" for d, v in rows),
                        encoding="utf-8")
        return rows

    def latest(self, series: str, on_or_before: date | None = None) -> Observation:
        """Last published value, optionally as of a date (to stay consistent with the share price date)."""
        rows = [r for r in self.series(series) if on_or_before is None or r[0] <= on_or_before]
        if not rows:
            raise DataError(f"FRED series {series}: no value on or before {on_or_before}.")
        d, v = max(rows)
        return Observation(series, d, v, f"FRED, {LABELS.get(series, series)} ({series}), {d.isoformat()}")
