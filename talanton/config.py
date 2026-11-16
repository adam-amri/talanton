"""API keys and identification, read from the environment or from a `.env` file.

Talanton never needs a paid key. The free sources fall into two groups:
  - no key:   SEC EDGAR (identification only), FRED public CSV, Damodaran, Yahoo Finance
  - free key: FRED API, Alpha Vantage, Finnhub

Put the keys in a `.env` file at the root of the project (see `.env.example`).
That file is listed in `.gitignore`: a key pushed to a public repository is
visible to everyone and must be revoked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CONTACT = "TALANTON_CONTACT"
FRED = "FRED_API_KEY"
ALPHA_VANTAGE = "ALPHAVANTAGE_API_KEY"
FINNHUB = "FINNHUB_API_KEY"
BLOOMBERG = "TALANTON_BLOOMBERG"


@dataclass(frozen=True)
class Variable:
    name: str
    purpose: str
    required: bool
    where: str


VARIABLES = (
    Variable(CONTACT, "Identifies you to the SEC (name and e-mail), mandatory to download filings",
             True, "no sign-up: just your name and e-mail"),
    Variable(FRED, "FRED API (rates, spreads). Optional: without a key Talanton reads FRED's public CSV files",
             False, "https://fred.stlouisfed.org/docs/api/api_key.html"),
    Variable(ALPHA_VANTAGE, "Alpha Vantage: backup source for prices and monthly history",
             False, "https://www.alphavantage.co/support/#api-key"),
    Variable(FINNHUB, "Finnhub: backup source for prices, and peer suggestions",
             False, "https://finnhub.io/register"),
    Variable(BLOOMBERG, "Set to 1 on a machine with a logged-in Bloomberg Terminal to use it first",
             False, "Bloomberg Terminal + `pip install blpapi`"),
)


def load_env(path: Path | str | None = None) -> list[str]:
    """Reads KEY=VALUE lines from a `.env` file into the environment.

    Variables already set in the environment win. Returns the names loaded.
    """
    file = Path(path) if path else Path.cwd() / ".env"
    if not file.exists():
        return []
    loaded = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and value and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded


def get(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def status() -> list[tuple[Variable, bool]]:
    """Which variables are set (never returns the values themselves)."""
    return [(v, get(v.name) is not None) for v in VARIABLES]
