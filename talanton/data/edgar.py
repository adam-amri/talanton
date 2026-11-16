"""Accounts published by US-listed companies (SEC EDGAR).

Calls used:
  1. the ticker -> CIK table (the SEC identifier);
  2. "companyfacts": every tagged (XBRL) figure of every filing of a company;
  3. "submissions": the company profile, including its SIC industry code;
  4. the company list of a SIC code, to suggest comparable companies.

The API is free and needs no key, but the SEC requires a User-Agent header that
identifies the caller (name + e-mail) and caps the rate at 10 requests/second.
Every answer is kept in a local cache: a file younger than 24 hours is not
downloaded again, and offline mode reads the cache only.
"""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .. import config
from .base import DataError, http_get, is_fresh

URL_TICKERS = "https://www.sec.gov/files/company_tickers.json"
URL_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
URL_PROFILE = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
URL_SIC = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type=10-K"
           "&dateb=&owner=include&start={start}&count={count}&output=atom")
SIC_PAGE = 100
SIC_MAX_PAGES = 5
_ENTRY = re.compile(r"<cik>(\d+)</cik>.*?<name>([^<]*)</name>", re.DOTALL)


@dataclass(frozen=True)
class Profile:
    cik: int
    name: str
    sic: str                    # four-digit industry code, "" when the SEC gives none
    sic_description: str
    tickers: tuple[str, ...]
    exchanges: tuple[str, ...]
    fiscal_year_end: str        # "MMDD"


class EdgarClient:
    def __init__(self, cache: Path, offline: bool = False, contact: str | None = None,
                 pause_s: float = 0.2):
        self.cache = Path(cache) / "sec"
        self.offline = offline
        self.contact = contact or config.get(config.CONTACT)
        self.pause_s = pause_s

    # -- low-level access ---------------------------------------------------
    def _read(self, url: str, file: Path) -> str:
        if file.exists() and (self.offline or is_fresh(file)):
            return file.read_text(encoding="utf-8")
        if self.offline:
            raise DataError(f"Offline mode: {file} is not in the cache. "
                            "Run again without --offline to download it.")
        if not self.contact:
            raise DataError(
                "The SEC requires callers to identify themselves. Set the TALANTON_CONTACT variable "
                '(environment or .env file), for example: TALANTON_CONTACT="First Last first.last@example.com"')
        time.sleep(self.pause_s)
        response = http_get(url, headers={"User-Agent": self.contact}, what=f"SEC ({url})")
        text = response.text if file.suffix == ".xml" else json.dumps(response.json())
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        return text

    def _tickers(self) -> list[dict]:
        return list(json.loads(self._read(URL_TICKERS, self.cache / "company_tickers.json")).values())

    # -- interface ----------------------------------------------------------
    def cik(self, ticker: str) -> tuple[int, str]:
        """Returns (CIK, registered name) for a US ticker."""
        for row in self._tickers():
            if row["ticker"].upper() == ticker.upper():
                return int(row["cik_str"]), row["title"]
        raise DataError(f"Ticker unknown to the SEC: {ticker}. Talanton only covers companies that "
                        "file their accounts in the United States (10-K / 10-Q).")

    def facts(self, ticker: str) -> dict:
        """Returns the raw "companyfacts" document of the company."""
        cik, _ = self.cik(ticker)
        file = self.cache / "companyfacts" / f"CIK{cik:010d}.json"
        return json.loads(self._read(URL_FACTS.format(cik=cik), file))

    def profile(self, ticker: str) -> Profile:
        cik, name = self.cik(ticker)
        file = self.cache / "submissions" / f"CIK{cik:010d}.json"
        raw = json.loads(self._read(URL_PROFILE.format(cik=cik), file))
        return Profile(cik=cik, name=raw.get("name") or name, sic=str(raw.get("sic") or ""),
                       sic_description=raw.get("sicDescription") or "",
                       tickers=tuple(raw.get("tickers") or ()), exchanges=tuple(raw.get("exchanges") or ()),
                       fiscal_year_end=raw.get("fiscalYearEnd") or "")

    def companies_by_sic(self, sic: str) -> list[tuple[int, str]]:
        """Every company that ever filed a 10-K under this SIC code: (CIK, name)."""
        found: list[tuple[int, str]] = []
        for page in range(SIC_MAX_PAGES):
            start = page * SIC_PAGE
            file = self.cache / "sic" / f"{sic}_{start}.xml"
            try:
                text = self._read(URL_SIC.format(sic=sic, start=start, count=SIC_PAGE), file)
            except DataError:
                if page == 0:
                    raise
                break                                   # offline: later pages not in the cache
            rows = [(int(c), html.unescape(n).strip()) for c, n in _ENTRY.findall(text)]
            found += rows
            if len(rows) < SIC_PAGE:
                break
        return found

    def listed(self, ciks: set[int]) -> dict[int, tuple[str, str]]:
        """Among these CIKs, those with a ticker today: CIK -> (ticker, name). First ticker wins."""
        result: dict[int, tuple[str, str]] = {}
        for row in self._tickers():
            cik = int(row["cik_str"])
            if cik in ciks and cik not in result:
                result[cik] = (row["ticker"].upper(), row["title"])
        return result
