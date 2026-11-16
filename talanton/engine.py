"""Assembly: from data collection to the full result, in pure Python.

This module knows nothing about Excel. The workbook redoes the same
computations with formulas; `checkpoints` lists the figures compared between the two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .data import (DataError, EdgarClient, FredClient, Industry, MarketData, Profile, Quote,
                   industry_for_sic, load_industries)
from .data import fred as F
from .model import (Assumptions, MarketInputs, ModelConfig, Projection, Settings, apply_overrides,
                    default_assumptions, project)
from .restatement import Company, build_company, load_adjustments
from .valuation import (Comparable, Comps, Dcf, Lbo, Sensitivities, compute_dcf, compute_lbo,
                        compute_sensitivities, compute_statistics, football_field, value_target)

DEFAULT_CAP = 40.0
BASE = "base"


@dataclass
class Inputs:
    """Everything collected for a run, before any assumption is made."""

    target: Company
    quote: Quote
    market: MarketInputs
    peers: list[Comparable]
    profile: Profile | None = None
    sources: list[str] = field(default_factory=list)      # where each market input came from
    notes: list[str] = field(default_factory=list)        # what could not be read


@dataclass
class Result:
    target: Company
    a: Assumptions
    proj: Projection
    dcf: Dcf
    comps: Comps
    lbo: Lbo
    sens: Sensitivities
    football: list[tuple[str, float | None, float | None]]
    overrides: list[str]
    settings: Settings
    scenario: str = BASE
    sources: list[str] = field(default_factory=list)

    def checkpoints(self) -> dict[str, float]:
        """Key figures computed by Python, to be reconciled with the workbook's formulas."""
        a, p, d, lbo = self.a, self.proj, self.dcf, self.lbo
        points = {
            "proj.revenue_end": p.revenue[-1],
            "proj.ebitda_end": p.ebitda[-1],
            "proj.net_income_end": p.net_income[-1],
            "proj.cash_end": p.cash[-1],
            "proj.total_assets_end": p.total_assets[-1],
            "market.diluted_shares": a.diluted_shares,
            "dcf.wacc": a.wacc,
            "dcf.fcf_end": d.fcf[-1],
            "dcf.ev_gordon": d.ev_gordon,
            "dcf.ev_multiple": d.ev_multiple,
            "dcf.share_gordon": d.share_gordon,
            "dcf.share_multiple": d.share_multiple,
            "lbo.equity_purchase": lbo.equity_purchase,
            "lbo.entry_ev": lbo.entry_ev,
            "lbo.sponsor_equity": lbo.sponsor_equity,
            "lbo.debt_end": lbo.debt_end[-1],
            "lbo.exit_equity": lbo.exit_equity,
            "lbo.moic": lbo.moic,
            "lbo.irr": lbo.irr,
            "lbo.max_price_target": lbo.max_price[a.target_irr],
            "lbo.max_price_high": lbo.max_price[a.target_irr_high],
        }
        median = self.comps.stats["ev_ebitda"]["median"]
        if median is not None:
            points["comps.median_ev_ebitda"] = median
            points["comps.share_median_ev_ebitda"] = self.comps.implied["ev_ebitda"]["median"]
        return points


def _industry(settings: Settings, profile: Profile | None, cache: Path, notes: list[str]) -> Industry | None:
    table = load_industries(cache)
    if settings.industry:
        if settings.industry not in table:
            close = [n for n in table if settings.industry.lower()[:4] in n.lower()]
            raise ValueError(f"Unknown industry {settings.industry!r}. "
                             + (f"Did you mean: {', '.join(close)}? " if close else "")
                             + "Run `talanton industries` for the list.")
        return table[settings.industry]
    if profile is None or not profile.sic:
        return None
    industry = industry_for_sic(profile.sic, table)
    if industry is None:
        notes.append(f"No sector reference mapped to SIC code {profile.sic} ({profile.sic_description}): "
                     "set `industry` in the config to get a sector beta and multiple.")
    return industry


def _market_inputs(ticker: str, quote: Quote, market: MarketData, fred: FredClient, industry: Industry | None,
                   sources: list[str], notes: list[str], log) -> MarketInputs:
    def observe(series: str):
        try:
            return fred.latest(series, on_or_before=quote.date)
        except DataError as exc:
            notes.append(str(exc))
            return None

    risk_free = observe(F.RISK_FREE)
    if risk_free is not None:
        rf, rf_source = risk_free.fraction, f"10-year Treasury yield. {risk_free.source}"
    else:
        fallback = market.ten_year_yield()
        rf, rf_source = fallback.price, f"10-year Treasury yield. {fallback.source}"
    sources.append(rf_source)
    sofr, spread, breakeven = observe(F.SOFR), observe(F.LOAN_SPREAD), observe(F.BREAKEVEN)
    rates_source = ""
    if sofr is not None and spread is not None:
        rates_source = f"{sofr.source}; {spread.source}"
        sources.append(f"LBO debt rate: {rates_source}")
    try:
        beta = market.beta(ticker)
    except DataError as exc:
        log(f"  beta unavailable: {exc}")
        notes.append(f"Regression beta unavailable: {exc}")
        beta = None
    if industry is not None:
        sources.append(f"Sector reference: {industry.source}")
    return MarketInputs(
        risk_free=rf, risk_free_source=rf_source, beta=beta,
        sofr=sofr.fraction if sofr is not None and spread is not None else None,
        loan_spread=spread.fraction if sofr is not None and spread is not None else None,
        rates_source=rates_source,
        breakeven_inflation=breakeven.fraction if breakeven is not None else None, industry=industry)


def collect(ticker: str, peers: list[str], cache: Path, offline: bool, adjustments_file: Path | None = None,
            settings: Settings | None = None, log=print) -> Inputs:
    """Fetches and restates the target, its comparables and the market data."""
    settings = settings or Settings()
    edgar = EdgarClient(cache, offline=offline)
    market = MarketData(cache, offline=offline)
    fred = FredClient(cache, offline=offline)
    sources: list[str] = []
    notes: list[str] = []

    log(f"Collecting the accounts of {ticker} (SEC EDGAR)")
    target = build_company(ticker, edgar.facts(ticker), settings.history_years, load_adjustments(adjustments_file))
    sources.append("Accounts: SEC EDGAR, " + "; ".join(target.filings.values()))
    quote = market.quote(ticker)
    sources.append(f"Share price: {quote.source}")
    try:
        profile = edgar.profile(ticker)
    except DataError as exc:
        profile = None
        notes.append(f"Company profile unavailable: {exc}")
    industry = _industry(settings, profile, cache, notes)
    inputs_market = _market_inputs(ticker, quote, market, fred, industry, sources, notes, log)

    comparables: list[Comparable] = []
    for t in peers:
        log(f"Collecting the comparable {t}")
        try:
            company = build_company(t, edgar.facts(t), 1, None, detailed_balance=False)
            comparables.append(Comparable(company, market.quote(t)))
        except Exception as exc:     # an unusable comparable does not stop the model
            log(f"  {t} dropped: {exc}")
            notes.append(f"Comparable {t} dropped: {exc}")
    notes += market.log
    return Inputs(target, quote, inputs_market, comparables, profile, sources, notes)


def compute(inputs: Inputs, config: ModelConfig | None = None, scenario: str | None = None,
            overrides: dict | None = None) -> Result:
    """Assumptions, projections and valuations, from the restated data.

    Order of precedence: defaults < config file < named scenario < `overrides`
    (the values set live in the app).
    """
    config = config or ModelConfig()
    settings = config.settings
    scenario = scenario or BASE
    if scenario != BASE and scenario not in config.scenarios:
        raise ValueError(f"Unknown scenario {scenario!r}. Defined: {', '.join([BASE, *config.scenarios])}.")
    industry = inputs.market.industry
    comps = compute_statistics(inputs.peers, DEFAULT_CAP, industry)
    a = default_assumptions(inputs.target, inputs.quote, inputs.market, comps.stats["ev_ebitda"]["median"], settings)
    changed = apply_overrides(a, config.overrides, config.origin)
    if scenario != BASE:
        changed += apply_overrides(a, config.scenarios[scenario], f"the scenario '{scenario}'")
    if overrides:
        changed += apply_overrides(a, overrides, "the app")
    if a.multiple_cap != DEFAULT_CAP:
        comps = compute_statistics(inputs.peers, a.multiple_cap, industry)
        if "exit_multiple" not in changed and comps.stats["ev_ebitda"]["median"] is not None:
            a.exit_multiple = comps.stats["ev_ebitda"]["median"]
    value_target(comps, inputs.target, a)
    proj = project(inputs.target, a)
    dcf = compute_dcf(proj, a)
    lbo = compute_lbo(inputs.target, proj, a)
    sens = compute_sensitivities(inputs.target, proj, a, dcf, lbo)
    return Result(inputs.target, a, proj, dcf, comps, lbo, sens, football_field(a, comps, sens, lbo),
                  list(dict.fromkeys(changed)), settings, scenario, list(inputs.sources))


def compute_scenarios(inputs: Inputs, config: ModelConfig | None = None, overrides: dict | None = None
                      ) -> dict[str, Result]:
    """The base case and every scenario of the config, side by side."""
    config = config or ModelConfig()
    return {name: compute(inputs, config, name, overrides) for name in [BASE, *config.scenarios]}
