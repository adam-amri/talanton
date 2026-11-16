"""Shared pieces of the data layer: errors, quotes and the local cache."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

CACHE_MAX_AGE_S = 24 * 3600


class DataError(RuntimeError):
    """Data not found or source unreachable."""


@dataclass(frozen=True)
class Quote:
    ticker: str
    date: date
    price: float
    currency: str
    source: str


@dataclass(frozen=True)
class Observation:
    """One value of a time series (rates and spreads are in percent)."""

    series: str
    date: date
    value: float
    source: str

    @property
    def fraction(self) -> float:
        return self.value / 100.0


def is_fresh(file: Path, max_age_s: float = CACHE_MAX_AGE_S) -> bool:
    return file.exists() and (time.time() - file.stat().st_mtime) < max_age_s


def http_get(url: str, *, headers: dict | None = None, params: dict | None = None, what: str = ""):
    """GET with a clear error message. `requests` is imported here: it is not needed offline."""
    import requests

    try:
        response = requests.get(url, headers=headers or {}, params=params, timeout=60)
    except requests.RequestException as exc:      # network down, DNS, timeout...
        raise DataError(f"{what or url}: source unreachable ({exc.__class__.__name__}).") from exc
    if response.status_code == 404:
        raise DataError(f"{what or url}: not found (HTTP 404).")
    if response.status_code == 429:
        raise DataError(f"{what or url}: rate limit reached (HTTP 429). Wait and retry.")
    if response.status_code >= 400:
        raise DataError(f"{what or url}: HTTP {response.status_code}.")
    return response
