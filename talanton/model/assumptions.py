"""Model assumptions and the default values proposed for them.

Defaults are mechanical: they start from the last published figure and converge
towards a normal situation. They are a starting point, not a forecast. Each one
appears in blue on the "Assumptions" sheet of the workbook and can be changed in
Excel, in the interactive app, or in a TOML config file passed to Talanton.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..data.base import Quote
from ..data.damodaran import Industry, relever
from ..restatement.statements import Company
from .settings import Settings

STATUTORY_TAX_RATE = 0.25        # US federal tax (21%) plus state taxes
EQUITY_RISK_PREMIUM = 0.0441     # implied premium of the S&P 500 (Damodaran, 1 Nov. 2026)
EQUITY_RISK_PREMIUM_SOURCE = ("Implied equity risk premium of the S&P 500 published by A. Damodaran "
                              "(NYU Stern), 1 November 2026: 4.41%")
TERMINAL_GROWTH = 0.02
BLUME_WEIGHT = 0.67              # adjusted beta = 0.67 x raw beta + 0.33 x 1
WEAK_R2 = 0.15                   # below this R², a regression beta is considered unreliable
FALLBACK_LOAN_MARGIN = 0.04      # leveraged-loan margin over the risk-free rate, when FRED is unavailable
SUBORDINATED_PREMIUM = 0.03      # extra yield of subordinated debt over senior debt (convention)

ANNUAL = ("revenue_growth", "ebitda_margin", "da_pct", "capex_pct", "nwc_pct", "distributions")


@dataclass
class MarketInputs:
    """Market data the defaults are built from, each with its source."""

    risk_free: float                                  # fraction
    risk_free_source: str
    beta: tuple[float, int, float] | None = None      # regression: (beta, returns, R²)
    sofr: float | None = None
    loan_spread: float | None = None
    rates_source: str = ""
    breakeven_inflation: float | None = None
    industry: Industry | None = None
    equity_risk_premium: float = EQUITY_RISK_PREMIUM
    equity_risk_premium_source: str = EQUITY_RISK_PREMIUM_SOURCE


def _clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


def _ramp(start: float, end: float, n: int) -> list[float]:
    """n values going linearly from `start` (year 1) to `end` (year n)."""
    if n == 1:
        return [start]
    return [start + (end - start) * k / (n - 1) for k in range(n)]


@dataclass
class Assumptions:
    n: int
    # --- market and bridge from enterprise value to equity value ---
    valuation_date: date
    price: float
    shares: float
    options: float
    option_strike: float
    rsus: float
    other_dilution: float
    debt: float
    cash: float
    minorities: float
    other_adjustments: float
    # --- operations (one value per projected year) ---
    revenue_growth: list[float]
    ebitda_margin: list[float]
    da_pct: list[float]
    capex_pct: list[float]
    nwc_pct: list[float]
    distributions: list[float]
    op_liabilities_pct: float
    tax_rate: float
    cost_of_debt: float
    cash_yield: float
    # --- cost of capital and terminal value ---
    risk_free_rate: float
    equity_risk_premium: float
    raw_beta: float
    blume_weight: float
    specific_premium: float
    debt_weight: float
    terminal_growth: float
    exit_multiple: float
    mid_year: int
    # --- LBO ---
    acquisition_premium: float
    senior_leverage: float
    senior_rate: float
    senior_amortization: float
    cash_sweep: float
    sub_leverage: float
    sub_rate: float
    sub_pik_rate: float
    min_cash: float
    transaction_fees: float
    financing_fees: float
    exit_multiple_delta: float
    target_irr: float
    target_irr_high: float
    # --- steps of the sensitivity tables and cap on multiples ---
    wacc_step: float = 0.005
    growth_step: float = 0.005
    multiple_step: float = 1.0
    premium_step: float = 0.05
    multiple_cap: float = 40.0
    # --- justification shown next to each assumption ---
    notes: dict[str, str] = field(default_factory=dict)

    # derived quantities (same formulas as in the workbook)
    @property
    def holding_period(self) -> int:
        """Years the fund holds the company: from the end of year 1 to the end of the plan."""
        return self.n - 1

    @property
    def base_shares(self) -> float:
        """Shares plus dilutive securities that do not depend on the share price."""
        return self.shares + self.rsus + self.other_dilution

    def option_shares(self, price: float) -> float:
        """Treasury stock method: net new shares if options are exercised and the proceeds buy back stock."""
        if price <= 0 or self.options <= 0:
            return 0.0
        return max(0.0, self.options * (1 - self.option_strike / price))

    def diluted_shares_at(self, price: float) -> float:
        return self.base_shares + self.option_shares(price)

    @property
    def diluted_shares(self) -> float:
        return self.diluted_shares_at(self.price)

    @property
    def market_cap(self) -> float:
        return self.price * self.diluted_shares

    @property
    def net_debt(self) -> float:
        return self.debt - self.cash

    @property
    def bridge(self) -> float:
        """Amount deducted from enterprise value to get equity value."""
        return self.net_debt + self.minorities + self.other_adjustments

    @property
    def enterprise_value(self) -> float:
        return self.market_cap + self.bridge

    @property
    def beta(self) -> float:
        return self.blume_weight * self.raw_beta + (1 - self.blume_weight)

    @property
    def cost_of_equity(self) -> float:
        return self.risk_free_rate + self.beta * self.equity_risk_premium + self.specific_premium

    @property
    def wacc(self) -> float:
        return ((1 - self.debt_weight) * self.cost_of_equity
                + self.debt_weight * self.cost_of_debt * (1 - self.tax_rate))


def _choose_beta(market: MarketInputs, settings: Settings, debt_to_equity: float, notes: dict[str, str]
                 ) -> tuple[float, float]:
    """Returns (raw beta, Blume weight) and writes the justification."""
    regression = market.beta
    industry = market.industry
    sector = None
    if industry is not None and industry.unlevered_beta_cash_corrected:
        sector = relever(industry.unlevered_beta_cash_corrected, debt_to_equity, STATUTORY_TAX_RATE)
    method = settings.beta_method
    if method == "auto":
        weak = regression is None or regression[2] < WEAK_R2
        method = "sector" if (weak and sector is not None) else "regression"

    if regression is not None:
        b, n_obs, r2 = regression
        regression_text = f"Regression of {n_obs} monthly returns on the S&P 500: beta {b:.2f}, R² {r2:.2f}."
    else:
        regression_text = "No price history: no regression beta."

    if method == "sector" and sector is not None:
        notes["raw_beta"] = (
            f"Sector beta: unlevered beta {industry.unlevered_beta_cash_corrected:.2f} ({industry.source}), "
            f"re-levered at this company's debt/equity of {debt_to_equity:.0%} and a {STATUTORY_TAX_RATE:.0%} tax rate. "
            f"Preferred to the regression, judged unreliable. {regression_text}")
        notes["blume_weight"] = "1: a sector beta is already an average, no Blume adjustment."
        return sector, 1.0
    notes["blume_weight"] = ("Blume adjustment: adjusted beta = weight x raw beta + (1 - weight) x 1. "
                             "Set to 1 to keep the raw beta.")
    if regression is not None:
        extra = ""
        if regression[2] < WEAK_R2:
            extra = " A low R² signals an unreliable beta: consider a sector beta (beta_method = \"sector\")."
        if sector is not None:
            extra += f" For reference, the re-levered sector beta is {sector:.2f}."
        notes["raw_beta"] = regression_text + extra
        return regression[0], BLUME_WEIGHT
    notes["raw_beta"] = "Price history unavailable and no sector reference: beta of 1 by default, to be entered."
    return 1.0, BLUME_WEIGHT


def default_assumptions(company: Company, quote: Quote, market: MarketInputs,
                        peer_multiple: float | None, settings: Settings | None = None) -> Assumptions:
    settings = settings or Settings()
    n = settings.years
    h, last, ltm = company.hist, company.last, company.ltm
    notes: dict[str, str] = {}
    as_of = company.balance_date.isoformat()

    # Growth: pace of the last twelve months, then convergence towards the long term.
    g1 = _clamp(ltm["revenue"] / last["revenue"] - 1, -0.05, 0.10)
    growth = _ramp(g1, TERMINAL_GROWTH, n)
    notes["revenue_growth"] = (f"Year 1: LTM revenue over the last fiscal year ({g1:+.1%}), "
                               f"then linear convergence towards {TERMINAL_GROWTH:.1%}.")

    # Margin: LTM margin, then back to the three-year average.
    margins = [e / r for e, r in zip(h["ebitda_adjusted"][-3:], h["revenue"][-3:])]
    normal_margin = sum(margins) / len(margins)
    ltm_margin = ltm["ebitda_adjusted"] / ltm["revenue"]
    margin = _ramp(ltm_margin, normal_margin, n)
    notes["ebitda_margin"] = (f"Year 1: LTM adjusted EBITDA margin ({ltm_margin:.1%}), then linear return "
                              f"to the average of the last {len(margins)} fiscal years ({normal_margin:.1%}).")

    da_pct = last["da"] / last["revenue"]
    notes["da_pct"] = "Ratio of the last fiscal year, held constant."
    capex = [c / r for c, r in zip(h["capex"][-3:], h["revenue"][-3:]) if c is not None]
    capex_pct = sum(capex) / len(capex) if capex else da_pct
    notes["capex_pct"] = f"Average of the last {len(capex)} fiscal years, held constant."
    nwc_pct = last["nwc"] / last["revenue"]
    notes["nwc_pct"] = "Ratio of the last fiscal year, held constant."
    distributions = [company.distributions_ytd] + [0.0] * (n - 1)
    notes["distributions"] = ("Year 1: buybacks and dividends already paid since the year end "
                              f"(to {as_of}). Afterwards: none, cash accumulates.")

    avg_debt = (h["debt"][-1] + h["debt"][-2]) / 2 if len(h["debt"]) > 1 else h["debt"][-1]
    cost_of_debt = (_clamp(last["interest_expense"] / avg_debt, 0.02, 0.12)
                    if last["interest_expense"] and avg_debt else 0.06)
    notes["cost_of_debt"] = "Interest expense of the last fiscal year over average debt."
    avg_cash = (h["cash"][-1] + h["cash"][-2]) / 2 if len(h["cash"]) > 1 else h["cash"][-1]
    cash_yield = _clamp((last["interest_income"] or 0.0) / avg_cash, 0.0, 0.05) if avg_cash else 0.0
    notes["cash_yield"] = "Interest income of the last fiscal year over average cash."
    notes["tax_rate"] = "Statutory rate: US federal tax of 21% plus state taxes."

    market_cap = quote.price * company.shares
    debt_to_equity = company.balance["debt"] / market_cap if market_cap else 0.0
    raw_beta, blume_weight = _choose_beta(market, settings, debt_to_equity, notes)
    notes["risk_free_rate"] = market.risk_free_source + "."
    notes["equity_risk_premium"] = market.equity_risk_premium_source + "."

    debt_weight = company.balance["debt"] / (company.balance["debt"] + market_cap)
    notes["debt_weight"] = "Current structure: financial debt / (debt + market capitalisation)."
    notes["terminal_growth"] = "Close to long-term inflation; must stay below the WACC."
    if market.breakeven_inflation is not None:
        notes["terminal_growth"] += (f" Market-implied 10-year inflation: {market.breakeven_inflation:.2%} "
                                     "(FRED, T10YIE).")

    other_adjustments = 0.0
    notes["other_adjustments"] = "Unfunded pensions, lease liabilities, equity investments... (0 by default)."
    if company.lease_liabilities:
        if settings.include_leases:
            other_adjustments = company.lease_liabilities
            notes["other_adjustments"] = (f"Operating lease liabilities at the last year end "
                                          f"({company.lease_liabilities:,.1f}), included at your request. "
                                          "Note: under US GAAP the lease cost stays inside EBITDA.")
        else:
            notes["other_adjustments"] += (f" Operating lease liabilities are {company.lease_liabilities:,.1f} "
                                           "and are left out: under US GAAP their cost stays inside EBITDA.")

    ev = (market_cap + company.balance["debt"] - company.balance["cash"] + company.balance["minorities"]
          + other_adjustments)
    if peer_multiple is None:
        peer_multiple = ev / ltm["ebitda_adjusted"]
        notes["exit_multiple"] = "Current EV/EBITDA of the company (no usable comparable)."
    else:
        notes["exit_multiple"] = "Median EV/EBITDA of the comparables (Comps sheet)."
    if market.industry is not None and market.industry.ev_ebitda:
        notes["exit_multiple"] += f" Sector reference: {market.industry.ev_ebitda:.1f}x ({market.industry.source})."

    if market.sofr is not None and market.loan_spread is not None:
        senior_rate = round(market.sofr + market.loan_spread, 4)
        notes["senior_rate"] = (f"SOFR ({market.sofr:.2%}) + single-B high-yield spread ({market.loan_spread:.2%}), "
                                f"a market proxy for a leveraged-loan margin. {market.rates_source}.")
    else:
        senior_rate = round(market.risk_free + FALLBACK_LOAN_MARGIN, 4)
        notes["senior_rate"] = (f"Risk-free rate + {FALLBACK_LOAN_MARGIN:.0%}: order of magnitude of a leveraged loan "
                                "(FRED rates unavailable).")
    notes["sub_leverage"] = ("Second tranche (subordinated or mezzanine debt), in multiples of LTM EBITDA. "
                             "0: single-tranche financing.")
    notes["sub_rate"] = (f"Cash interest of the subordinated tranche: senior rate + {SUBORDINATED_PREMIUM:.0%} "
                         "(convention, to be adjusted).")
    notes["sub_pik_rate"] = "Interest capitalised into the subordinated principal instead of paid in cash (PIK)."
    notes["acquisition_premium"] = "Premium paid over the share price to take the company private (usual: 20% to 40%)."
    notes["senior_leverage"] = "Senior acquisition debt, in multiples of LTM adjusted EBITDA."
    notes["senior_amortization"] = "Mandatory annual repayment, in % of the initial senior debt."
    notes["cash_sweep"] = "Share of excess cash used to repay senior debt early."
    min_cash = float(round(0.02 * ltm["revenue"]))
    notes["min_cash"] = "Cash left in the company at closing (about 2% of revenue)."
    notes["transaction_fees"] = "Advisers, legal: in % of enterprise value. Expensed."
    notes["financing_fees"] = "Arrangement fees: in % of the new debt. Expensed."
    notes["exit_multiple_delta"] = "Exit multiple = entry multiple + this delta. Zero: usual prudent assumption."
    notes["target_irr"] = "IRR targeted by a fund: used to compute the maximum price it can pay."
    notes["valuation_date"] = "Date of the last published balance sheet: later cash flows are in the DCF."
    notes["price"] = quote.source + "."
    notes["shares"] = company.shares_source[:1].upper() + company.shares_source[1:] + "."
    notes["options"] = company.dilution_source or "Stock options outstanding (treasury stock method)."
    notes["option_strike"] = ("Options add shares only when the share price exceeds the strike: "
                              "options x (1 - strike / price).")
    notes["rsus"] = "Unvested restricted stock units: counted in full."
    notes["other_dilution"] = "Convertible bonds, warrants... to be estimated."
    notes["debt"] = f"Financial debt at {as_of} (excluding lease liabilities)."
    notes["cash"] = f"Cash and short-term investments at {as_of}."
    notes["minorities"] = "Non-controlling interests on the last balance sheet."
    notes["op_liabilities_pct"] = "Ratio of the last fiscal year: used to lay out the balance sheet, no effect on cash flows."
    notes["mid_year"] = "1: cash flows fall in the middle of the year. 0: at year end."

    return Assumptions(
        n=n, valuation_date=company.balance_date, price=quote.price, shares=company.shares,
        options=company.options, option_strike=company.option_strike, rsus=company.rsus, other_dilution=0.0,
        debt=company.balance["debt"], cash=company.balance["cash"],
        minorities=company.balance["minorities"], other_adjustments=other_adjustments,
        revenue_growth=growth, ebitda_margin=margin, da_pct=[da_pct] * n, capex_pct=[capex_pct] * n,
        nwc_pct=[nwc_pct] * n, distributions=distributions,
        op_liabilities_pct=last["operating_current_liabilities"] / last["revenue"],
        tax_rate=STATUTORY_TAX_RATE, cost_of_debt=cost_of_debt, cash_yield=cash_yield,
        risk_free_rate=market.risk_free, equity_risk_premium=market.equity_risk_premium, raw_beta=raw_beta,
        blume_weight=blume_weight, specific_premium=0.0, debt_weight=debt_weight,
        terminal_growth=TERMINAL_GROWTH, exit_multiple=peer_multiple, mid_year=1,
        acquisition_premium=0.30, senior_leverage=5.0, senior_rate=senior_rate, senior_amortization=0.01,
        cash_sweep=1.0, sub_leverage=0.0, sub_rate=round(senior_rate + SUBORDINATED_PREMIUM, 4),
        sub_pik_rate=0.0, min_cash=min_cash, transaction_fees=0.02, financing_fees=0.025,
        exit_multiple_delta=0.0, target_irr=0.20, target_irr_high=0.25, notes=notes,
    )
