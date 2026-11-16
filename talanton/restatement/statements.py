"""Putting published accounts into bank format.

From the raw SEC facts, builds for one company:
  - the annual history (income statement, cash flows, simplified balance sheet);
  - the last twelve months (LTM);
  - the last published balance sheet (cash, debt, minorities);
  - the share count and the dilutive securities.
All amounts are in millions of dollars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import tags as T
from .adjustments import Adjustments
from .facts import Facts

MILLION = 1e6
REVENUE_TAG_GAP = 0.01       # beyond a 1% gap between two revenue tags: warning

FLOW_LINES = ("revenue", "gross_profit", "ebit", "da", "impairments", "ebitda_adj", "ebitda_reported",
              "ebitda_adjusted", "ebit_adjusted", "interest_expense", "interest_income", "pretax_income",
              "income_tax", "net_income", "sbc", "cfo", "capex", "buybacks", "dividends")
BALANCE_LINES = ("cash", "operating_current_assets", "net_fixed_assets", "goodwill", "other_assets",
                 "total_assets", "operating_current_liabilities", "debt", "other_liabilities", "equity",
                 "total_liabilities_equity", "nwc", "minorities")
LTM_LINES = ("revenue", "gross_profit", "ebit", "da", "impairments", "ebitda_adj", "ebitda_reported",
             "ebitda_adjusted", "ebit_adjusted", "net_income", "net_income_adj", "net_income_adjusted")


class RestatementError(RuntimeError):
    pass


@dataclass
class Company:
    ticker: str
    name: str
    cik: int
    fiscal_years: list[date]                    # fiscal year ends, chronological
    hist: dict[str, list[float | None]]         # one figure per fiscal year
    ltm_date: date                              # end of the LTM period
    ltm: dict[str, float | None]
    balance_date: date                          # date of the last published balance sheet
    balance: dict[str, float]                   # cash, debt, minorities at that date
    distributions_ytd: float                    # buybacks + dividends since the last year end
    shares: float                               # in millions
    shares_source: str
    options: float = 0.0                        # stock options outstanding, in millions
    option_strike: float = 0.0                  # weighted average exercise price, in $
    rsus: float = 0.0                           # unvested restricted stock units, in millions
    dilution_source: str = ""
    lease_liabilities: float = 0.0              # operating lease liabilities at the last year end
    sources: dict[str, str] = field(default_factory=dict)    # line -> tag(s) used
    adjustments: Adjustments = field(default_factory=Adjustments)
    filings: dict[str, str] = field(default_factory=dict)    # last 10-K / 10-Q used
    warnings: list[str] = field(default_factory=list)

    @property
    def last(self) -> dict[str, float | None]:
        """Figures of the last closed fiscal year."""
        return {k: v[-1] for k, v in self.hist.items()}

    @property
    def short_name(self) -> str:
        return (self.name.title().replace(" /De/", "").replace(" Inc", " Inc.").replace("..", ".")
                .replace(",.", "."))


def _m(value: float | None) -> float | None:
    return None if value is None else value / MILLION


class _Builder:
    def __init__(self, ticker: str, raw: dict, n_years: int, adjustments: Adjustments | None,
                 detailed_balance: bool = True):
        self.ticker = ticker
        self.detailed_balance = detailed_balance
        self.f = Facts(raw)
        self.adj = adjustments or Adjustments()
        self.sources: dict[str, str] = {}
        self.warnings: list[str] = []
        every = self.f.fiscal_years(T.ANCHORS)
        if not every:
            raise RestatementError(f"{ticker}: no annual fiscal year (10-K) found.")
        self.years = every[-n_years:]
        self.last_start, self.last_end = self.years[-1]
        self.quarter = self.f.last_quarter(T.ANCHORS, self.last_end)

    # -- annual flows ---------------------------------------------------------
    def _first_annual(self, candidates: tuple[str, ...], end: date):
        for tag in candidates:
            fact = self.f.annual(tag, end)
            if fact is not None:
                return fact
        return None

    def annual_flow(self, line: str, end: date) -> float | None:
        fact = self._first_annual(T.FLOWS[line], end)
        if fact is not None:
            if end == self.last_end:
                self.sources[line] = fact.tag
            return _m(fact.value)
        return None

    def annual_da(self, end: date) -> float | None:
        v = self.annual_flow("da", end)
        if v is not None:
            return v
        parts = [self.f.annual(tag, end) for tag in T.DA_COMPONENTS]
        if all(p is not None for p in parts):
            self.sources["da"] = " + ".join(T.DA_COMPONENTS)
            return _m(sum(p.value for p in parts))
        return None

    def annual_capex(self, end: date) -> float | None:
        forced = self.adj.capex.get(end.isoformat())
        if forced is not None:
            self.sources["capex"] = "analyst adjustment"
            return forced
        v = self.annual_flow("capex", end)
        if v is not None:
            return v
        parts = [p for p in (self.f.annual(tag, end) for tag in T.CAPEX_PARTIAL) if p is not None]
        if parts:
            if end == self.last_end:
                self.sources["capex"] = " + ".join(p.tag for p in parts) + " (partial)"
                self.warnings.append(
                    "Capex: no total tag, only a partial line is available "
                    f"({', '.join(p.tag for p in parts)}). Enter the total in the adjustments file.")
            return _m(sum(p.value for p in parts))
        return None

    def annual_impairments(self, end: date) -> float:
        aggregate = [self.f.annual(tag, end) for tag in T.IMPAIRMENTS_AGGREGATE]
        detail = [self.f.annual(tag, end) for tag in T.IMPAIRMENTS_DETAIL]
        a = max((x.value for x in aggregate if x is not None), default=0.0)
        d = sum(x.value for x in detail if x is not None)
        return _m(max(a, d))

    # -- LTM ------------------------------------------------------------------
    def _ltm_tag(self, tag: str) -> float | None:
        a = self.f.annual(tag, self.last_end)
        if a is None:
            return None
        if self.quarter is None:
            return a.value
        c = self.f.year_to_date(tag, self.last_end + timedelta(days=1), self.quarter)
        p = self.f.prior_year_to_date(tag, self.last_start, self.quarter)
        if c is None or p is None:
            return None
        return a.value + c.value - p.value

    def ltm_flow(self, line: str) -> float | None:
        for tag in T.FLOWS[line]:
            v = self._ltm_tag(tag)
            if v is not None:
                return _m(v)
        return None

    def ltm_da(self) -> float | None:
        v = self.ltm_flow("da")
        if v is not None:
            return v
        parts = [self._ltm_tag(tag) for tag in T.DA_COMPONENTS]
        return _m(sum(parts)) if all(p is not None for p in parts) else None

    def _ltm_impairment(self, tag: str) -> float:
        a = self.f.annual(tag, self.last_end)
        if self.quarter is None:
            return a.value if a else 0.0
        c = self.f.year_to_date(tag, self.last_end + timedelta(days=1), self.quarter)
        p = self.f.prior_year_to_date(tag, self.last_start, self.quarter)
        if a is not None and a.value and (c is None or p is None):
            self.warnings.append(
                f"Asset impairment ({tag}): quarterly year-to-date figure missing, "
                "check the LTM amount added back.")
        return (a.value if a else 0.0) + (c.value if c else 0.0) - (p.value if p else 0.0)

    def ltm_impairments(self) -> float:
        a = max((self._ltm_impairment(tag) for tag in T.IMPAIRMENTS_AGGREGATE), default=0.0)
        d = sum(self._ltm_impairment(tag) for tag in T.IMPAIRMENTS_DETAIL)
        return _m(max(a, d, 0.0))

    # -- balance sheet ----------------------------------------------------------
    def _first_instant(self, candidates: tuple[str, ...], d: date):
        for tag in candidates:
            fact = self.f.instant(tag, d)
            if fact is not None:
                return fact
        return None

    def _instant(self, line: str, d: date) -> float | None:
        fact = self._first_instant(T.BALANCE[line], d)
        if fact is not None and d == self.last_end:
            self.sources[line] = fact.tag
        return None if fact is None else fact.value

    def cash(self, d: date) -> float | None:
        cash = self._instant("cash_equivalents", d)
        if cash is None:
            return None
        return _m(cash + (self._instant("short_term_investments", d) or 0.0))

    def debt(self, d: date) -> tuple[float, float]:
        """Returns (total financial debt, portion classified as current)."""
        long_term = self._instant("long_term_debt", d)
        short_fact = self._first_instant(T.BALANCE["short_term_debt"], d)
        short = short_fact.value if short_fact else None
        extras = 0.0
        if short_fact is None or short_fact.tag != "DebtCurrent":
            for tag in T.SHORT_TERM_DEBT_EXTRAS:
                fact = self.f.instant(tag, d)
                if fact is not None:
                    extras += fact.value
        if long_term is None and short is None and not extras:
            fallback = self._instant("total_debt_fallback", d)
            return _m(fallback or 0.0), 0.0
        current = (short or 0.0) + extras
        return _m((long_term or 0.0) + current), _m(current)

    def minorities(self, d: date) -> float:
        total = 0.0
        for tag in T.MINORITIES:
            fact = self.f.instant(tag, d)
            if fact is not None:
                total += fact.value
        return _m(total)

    def full_balance(self, d: date) -> dict[str, float]:
        required = {p: self._instant(p, d) for p in ("current_assets", "total_assets", "current_liabilities")}
        missing = [p for p, v in required.items() if v is None]
        cash = self.cash(d)
        if missing or cash is None:
            raise RestatementError(
                f"{self.ticker}: incomplete balance sheet at {d} ({', '.join(missing) or 'cash'}). "
                "Banks, insurers and real-estate companies are not covered by this version.")
        debt, current_debt = self.debt(d)
        minorities = self.minorities(d)
        equity_total = self._instant("equity_total", d)
        if equity_total is None:
            equity_parent = self._instant("equity_parent", d)
            if equity_parent is None:
                raise RestatementError(f"{self.ticker}: shareholders' equity not found at {d}.")
            equity_total = equity_parent + minorities * MILLION
        total_assets = _m(required["total_assets"])
        total_le = _m(self._instant("total_liabilities_equity", d)) or total_assets
        op_assets = _m(required["current_assets"]) - cash
        fixed = _m((self._instant("ppe", d) or 0.0) + (self._instant("intangibles", d) or 0.0))
        goodwill = _m(self._instant("goodwill", d) or 0.0)
        op_liabilities = _m(required["current_liabilities"]) - current_debt
        equity = _m(equity_total)
        return {
            "cash": cash, "operating_current_assets": op_assets, "net_fixed_assets": fixed,
            "goodwill": goodwill,
            "other_assets": total_assets - cash - op_assets - fixed - goodwill,
            "total_assets": total_assets, "operating_current_liabilities": op_liabilities, "debt": debt,
            "other_liabilities": total_le - op_liabilities - debt - equity,
            "equity": equity, "total_liabilities_equity": total_le,
            "nwc": op_assets - op_liabilities, "minorities": minorities,
        }

    # -- shares and dilutive securities -------------------------------------------
    def shares(self) -> tuple[float, str]:
        cover = self.f.of(T.COVER_PAGE_SHARES, "dei")
        if cover:
            last = max(cover, key=lambda f: (f.end, f.filed))
            return _m(last.value), (f"shares outstanding at {last.end.isoformat()} "
                                    f"(cover page of the {last.form})")
        annual = self.f.annual(T.DILUTED_SHARES, self.last_end)
        if annual is None:
            raise RestatementError(f"{self.ticker}: share count not found.")
        value = annual.value
        if self.quarter is not None:
            c = self.f.year_to_date(T.DILUTED_SHARES, self.last_end + timedelta(days=1), self.quarter)
            # guard: some companies publish this figure in thousands in their 10-Qs
            if c is not None and 0.5 <= c.value / annual.value <= 2.0:
                value = c.value
        self.warnings.append(
            f"{self.ticker}: share count estimated from the diluted weighted average "
            "(no cover-page figure, often several share classes). Check it.")
        return _m(value), "diluted weighted average of the last published period"

    def dilutive(self) -> tuple[float, float, float, str]:
        """(options in millions, average strike, RSUs in millions, source)."""
        options = self.f.instant(T.OPTIONS_OUTSTANDING, self.last_end)
        strike = self.f.instant(T.OPTIONS_STRIKE, self.last_end)
        rsus = self.f.instant(T.RSUS_NONVESTED, self.last_end)
        found = []
        n_options = k = n_rsus = 0.0
        if options is not None and strike is not None and options.value > 0:
            n_options, k = _m(options.value), strike.value
            found.append(f"{n_options:,.3f}m options at an average strike of ${k:,.2f}")
        if rsus is not None and rsus.value > 0:
            n_rsus = _m(rsus.value)
            found.append(f"{n_rsus:,.3f}m unvested RSUs")
        if not found:
            return 0.0, 0.0, 0.0, "No option or RSU tag in the SEC data: enter them from the 10-K notes."
        missing = "" if n_rsus else " RSUs are not tagged: add them from the 10-K notes."
        return n_options, k, n_rsus, (f"10-K at {self.last_end.isoformat()}: " + ", ".join(found) + "." + missing)

    def leases(self) -> float:
        total = self._first_instant(T.LEASES_TOTAL, self.last_end)
        if total is not None:
            return _m(total.value)
        parts = [self.f.instant(tag, self.last_end) for tag in T.LEASES_PARTS]
        return _m(sum(p.value for p in parts if p is not None))

    # -- check of the revenue tags ---------------------------------------------
    def check_revenue_tags(self) -> None:
        values = [(tag, self.f.annual(tag, self.last_end)) for tag in T.FLOWS["revenue"]]
        present = [(tag, f.value) for tag, f in values if f is not None]
        if len(present) >= 2:
            (t1, v1), (t2, v2) = present[0], present[1]
            if v1 and abs(v2 - v1) / abs(v1) > REVENUE_TAG_GAP:
                self.warnings.append(
                    f"{self.ticker}: two revenue tags disagree "
                    f"({t1} = {v1 / MILLION:,.1f}; {t2} = {v2 / MILLION:,.1f}). "
                    f"Talanton keeps {t1}.")

    # -- assembly -------------------------------------------------------------
    def build(self) -> Company:
        ends = [end for _, end in self.years]
        hist: dict[str, list[float | None]] = {p: [] for p in FLOW_LINES + BALANCE_LINES}
        for end in ends:
            row = {p: self.annual_flow(p, end) for p in
                   ("revenue", "gross_profit", "ebit", "interest_expense", "interest_income",
                    "pretax_income", "income_tax", "net_income", "sbc", "cfo", "buybacks", "dividends")}
            row["da"] = self.annual_da(end)
            row["capex"] = self.annual_capex(end)
            row["impairments"] = self.annual_impairments(end)
            row["ebitda_adj"] = self.adj.ebitda.get(end.isoformat(), 0.0)
            for required in ("revenue", "ebit", "da"):
                if row[required] is None:
                    raise RestatementError(
                        f"{self.ticker}: line '{required}' not found for the fiscal year ended {end}.")
            row["ebitda_reported"] = row["ebit"] + row["da"]
            row["ebitda_adjusted"] = row["ebitda_reported"] + row["impairments"] + row["ebitda_adj"]
            row["ebit_adjusted"] = row["ebitda_adjusted"] - row["da"]
            for p in FLOW_LINES:
                hist[p].append(row[p])
            b = self.full_balance(end) if self.detailed_balance else {p: None for p in BALANCE_LINES}
            for p in BALANCE_LINES:
                hist[p].append(b[p])
        self.check_revenue_tags()

        ltm: dict[str, float | None] = {p: self.ltm_flow(p) for p in ("revenue", "gross_profit", "ebit", "net_income")}
        ltm["da"] = self.ltm_da()
        ltm["impairments"] = self.ltm_impairments()
        ltm["ebitda_adj"] = self.adj.ebitda.get("LTM", 0.0)
        for required in ("revenue", "ebit", "da"):
            if ltm[required] is None:
                self.warnings.append(
                    f"{self.ticker}: LTM unavailable for '{required}', falling back on the last fiscal year.")
                ltm[required] = hist[required][-1]
        if ltm["net_income"] is None:
            ltm["net_income"] = hist["net_income"][-1]
        ltm["ebitda_reported"] = ltm["ebit"] + ltm["da"]
        ltm["ebitda_adjusted"] = ltm["ebitda_reported"] + ltm["impairments"] + ltm["ebitda_adj"]
        ltm["ebit_adjusted"] = ltm["ebitda_adjusted"] - ltm["da"]
        ltm["net_income_adj"] = self.adj.net_income.get("LTM", 0.0)
        ltm["net_income_adjusted"] = ltm["net_income"] + ltm["net_income_adj"]

        balance_date = self.quarter or self.last_end
        cash = self.cash(balance_date)
        if cash is None:
            raise RestatementError(f"{self.ticker}: cash not found at {balance_date}.")
        debt, _ = self.debt(balance_date)
        balance = {"cash": cash, "debt": debt, "minorities": self.minorities(balance_date)}

        distributions = 0.0
        if self.quarter is not None:
            for line in ("buybacks", "dividends"):
                for tag in T.FLOWS[line]:
                    c = self.f.year_to_date(tag, self.last_end + timedelta(days=1), self.quarter)
                    if c is not None:
                        distributions += _m(c.value)
                        break

        shares, shares_source = self.shares()
        options, strike, rsus, dilution_source = self.dilutive()
        filings = {}
        for tag in T.FLOWS["revenue"]:
            a = self.f.annual(tag, self.last_end)
            if a is not None:
                filings["annual"] = f"10-K filed on {a.filed.isoformat()} (no. {a.accession})"
                if self.quarter is not None:
                    c = self.f.year_to_date(tag, self.last_end + timedelta(days=1), self.quarter)
                    if c is not None:
                        filings["quarterly"] = f"10-Q filed on {c.filed.isoformat()} (no. {c.accession})"
                break

        return Company(
            ticker=self.ticker, name=self.f.name, cik=self.f.cik, fiscal_years=ends, hist=hist,
            ltm_date=balance_date, ltm=ltm, balance_date=balance_date, balance=balance,
            distributions_ytd=distributions, shares=shares, shares_source=shares_source,
            options=options, option_strike=strike, rsus=rsus, dilution_source=dilution_source,
            lease_liabilities=self.leases(), sources=self.sources, adjustments=self.adj,
            filings=filings, warnings=self.warnings,
        )


def build_company(ticker: str, raw: dict, n_years: int = 5, adjustments: Adjustments | None = None,
                  detailed_balance: bool = True) -> Company:
    """Entry point: raw SEC facts -> company in bank format.

    `detailed_balance=False` for a comparable: only the LTM, debt, cash and share
    count are used, the full balance sheet is not needed.
    """
    return _Builder(ticker, raw, n_years, adjustments, detailed_balance).build()
