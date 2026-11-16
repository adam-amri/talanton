"""Suggests comparable companies for a ticker.

Free method, no key: the SEC classifies every filer under a four-digit SIC
industry code. Talanton lists the companies of the same code that still have a
ticker, then widens to the neighbouring codes (same first three digits).

These are suggestions, not a selection: SIC codes are coarse, the list contains
micro-caps and shells, and choosing peers remains the analyst's judgment.
With a Finnhub key, Finnhub's own peer list is merged in first.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import DataError
from .edgar import EdgarClient


@dataclass(frozen=True)
class Suggestion:
    ticker: str
    name: str
    reason: str


def suggest_peers(edgar: EdgarClient, ticker: str, limit: int = 20, finnhub=None
                  ) -> tuple[list[Suggestion], list[str]]:
    """Returns (suggestions, notes on what could not be read)."""
    ticker = ticker.upper()
    notes: list[str] = []
    found: dict[str, Suggestion] = {}

    if finnhub is not None:
        try:
            for t in finnhub.peers(ticker):
                found.setdefault(t, Suggestion(t, "", "Finnhub peer list"))
        except DataError as exc:
            notes.append(str(exc))

    try:
        profile = edgar.profile(ticker)
    except DataError as exc:
        return list(found.values())[:limit], notes + [str(exc)]
    if not profile.sic:
        return list(found.values())[:limit], notes + [f"The SEC gives no SIC code for {ticker}."]

    siblings = [profile.sic[:3] + str(d) for d in range(10) if profile.sic[:3] + str(d) != profile.sic]
    for sic in [profile.sic] + siblings:
        try:
            companies = edgar.companies_by_sic(sic)
        except DataError as exc:
            if sic == profile.sic or not edgar.offline:
                notes.append(f"SIC {sic}: {exc}")
            continue
        same = sic == profile.sic
        reason = (f"Same SIC code {sic} ({profile.sic_description})" if same
                  else f"Neighbouring SIC code {sic}")
        listed = edgar.listed({cik for cik, _ in companies})
        for cik, (t, name) in sorted(listed.items(), key=lambda kv: kv[1][0]):
            if t != ticker and cik != profile.cik:
                found.setdefault(t, Suggestion(t, name, reason))
        if len(found) >= limit:
            break
    return list(found.values())[:limit], notes
