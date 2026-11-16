"""LBO: buyout of the company by a fund, partly financed with debt.

Structure:
  - the deal closes at the end of the current fiscal year (year 1 of the plan);
  - the fund holds the company until the end of the plan and sells it then;
  - a senior tranche at a fixed rate, repaid by a mandatory amortisation and
    then by excess cash (cash sweep);
  - an optional subordinated tranche (mezzanine), with cash interest and/or
    capitalised interest (PIK), repaid in one go at exit;
  - interest is computed on the opening balance of the year (no circularity);
  - fees are expensed at closing;
  - the equity is bought at the offer price: options are counted with the
    treasury stock method at that price.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.assumptions import Assumptions
from ..model.projections import Projection
from ..restatement.statements import Company

MIN_YEARS = 6


@dataclass
class Lbo:
    # entry
    offer_price: float
    diluted_shares: float            # at the offer price
    equity_purchase: float
    refinanced_debt: float
    closing_cash: float
    entry_net_debt: float            # refinanced debt - cash + minorities + other adjustments
    entry_ev: float
    entry_multiple: float            # EV / LTM adjusted EBITDA
    # financing
    senior_debt: float
    sub_debt: float
    transaction_fees: float
    financing_fees: float
    total_uses: float
    sponsor_equity: float
    # plan (the fiscal years after closing)
    senior_interest: list[float]
    sub_interest: list[float]        # cash interest of the subordinated tranche
    sub_pik: list[float]             # capitalised interest
    net_income: list[float]
    fcf: list[float]                 # cash available to repay debt
    amortization: list[float]
    sweep: list[float]
    senior_end: list[float]
    sub_end: list[float]
    cash_end: list[float]
    # exit
    exit_multiple: float
    exit_ev: float
    exit_equity: float
    moic: float
    irr: float
    # maximum price per share for a target IRR
    max_price: dict[float, float]

    @property
    def new_debt(self) -> float:
        return self.senior_debt + self.sub_debt

    @property
    def debt_end(self) -> list[float]:
        return [s + m for s, m in zip(self.senior_end, self.sub_end)]


def equity_purchase_at(price: float, a: Assumptions) -> float:
    """Cost of all the shares at a given price per share (piecewise linear in the price)."""
    return price * a.diluted_shares_at(price)


def price_for_equity(equity_purchase: float, a: Assumptions) -> float:
    """Inverse of `equity_purchase_at`: price per share that costs this amount in total."""
    base = a.base_shares
    price = equity_purchase / base
    if a.options > 0 and price > a.option_strike:           # options in the money at that price
        price = (equity_purchase + a.options * a.option_strike) / (base + a.options)
    return price


def _debt_schedule(proj: Projection, a: Assumptions, senior0: float, sub0: float):
    cols: dict[str, list[float]] = {k: [] for k in (
        "senior_interest", "sub_interest", "sub_pik", "net_income", "fcf", "amortization", "sweep",
        "senior_end", "sub_end", "cash_end")}
    senior, sub, cash = senior0, sub0, a.min_cash
    for i in range(1, a.holding_period + 1):       # index in the projection (0 = closing year)
        senior_interest = senior * a.senior_rate
        sub_interest = sub * a.sub_rate
        pik = sub * a.sub_pik_rate
        pretax = proj.ebit[i] - senior_interest - sub_interest - pik
        net_income = pretax - max(0.0, pretax) * a.tax_rate
        fcf = net_income + pik + proj.da[i] - proj.capex[i] - proj.change_nwc[i]
        amortization = min(senior, senior0 * a.senior_amortization)
        sweep = max(0.0, min(senior - amortization, (fcf - amortization) * a.cash_sweep))
        cash = cash + fcf - amortization - sweep
        senior = senior - amortization - sweep
        sub = sub + pik
        for key, v in (("senior_interest", senior_interest), ("sub_interest", sub_interest), ("sub_pik", pik),
                       ("net_income", net_income), ("fcf", fcf), ("amortization", amortization),
                       ("sweep", sweep), ("senior_end", senior), ("sub_end", sub), ("cash_end", cash)):
            cols[key].append(v)
    return cols


def compute_lbo(company: Company, proj: Projection, a: Assumptions) -> Lbo:
    if a.n < MIN_YEARS:
        raise ValueError(f"The LBO needs at least {MIN_YEARS} projected fiscal years.")
    hold = a.holding_period
    ltm_ebitda = company.ltm["ebitda_adjusted"]
    offer = a.price * (1 + a.acquisition_premium)
    diluted = a.diluted_shares_at(offer)
    equity_purchase = offer * diluted
    refinanced, closing_cash = proj.debt, proj.cash[0]
    other = a.minorities + a.other_adjustments
    net_debt = refinanced - closing_cash + other
    ev = equity_purchase + net_debt
    senior0, sub0 = a.senior_leverage * ltm_ebitda, a.sub_leverage * ltm_ebitda
    tx_fees = a.transaction_fees * ev
    fin_fees = a.financing_fees * (senior0 + sub0)
    uses = equity_purchase + refinanced + tx_fees + fin_fees + a.min_cash
    sponsor = uses - senior0 - sub0 - closing_cash

    s = _debt_schedule(proj, a, senior0, sub0)

    entry_multiple = ev / ltm_ebitda
    exit_multiple = entry_multiple + a.exit_multiple_delta
    exit_ebitda = proj.ebitda[hold]
    exit_ev = exit_ebitda * exit_multiple
    exit_liabilities = s["senior_end"][-1] + s["sub_end"][-1] - s["cash_end"][-1] + other
    exit_equity = exit_ev - exit_liabilities
    moic = exit_equity / sponsor
    irr = moic ** (1 / hold) - 1 if moic > 0 else float("nan")

    # Maximum price: the sponsor's cheque and the exit value are both linear in the amount
    # paid for the shares (debt only depends on EBITDA), hence an exact solution.
    ratio = exit_ebitda / ltm_ebitda
    k = exit_ebitda * a.exit_multiple_delta - exit_liabilities
    c0 = (refinanced + a.transaction_fees * net_debt + fin_fees + a.min_cash
          - senior0 - sub0 - closing_cash)
    max_price = {}
    for target in (a.target_irr, a.target_irr_high):
        r = (1 + target) ** hold
        max_equity = (r * c0 - ratio * net_debt - k) / (ratio - r * (1 + a.transaction_fees))
        max_price[target] = price_for_equity(max_equity, a)

    return Lbo(
        offer_price=offer, diluted_shares=diluted, equity_purchase=equity_purchase,
        refinanced_debt=refinanced, closing_cash=closing_cash, entry_net_debt=net_debt, entry_ev=ev,
        entry_multiple=entry_multiple, senior_debt=senior0, sub_debt=sub0,
        transaction_fees=tx_fees, financing_fees=fin_fees, total_uses=uses, sponsor_equity=sponsor,
        exit_multiple=exit_multiple, exit_ev=exit_ev, exit_equity=exit_equity, moic=moic, irr=irr,
        max_price=max_price, **s,
    )


def irr_at(company: Company, proj: Projection, a: Assumptions, lbo: Lbo, *, premium: float | None = None,
           exit_multiple: float | None = None, year: int | None = None) -> float | None:
    """IRR for another premium, another exit multiple or another exit year.

    The debt schedule does not change: only the cheque at entry and the sale price move.
    """
    year = a.holding_period if year is None else year
    offer = a.price * (1 + (a.acquisition_premium if premium is None else premium))
    constant = lbo.sponsor_equity - (1 + a.transaction_fees) * lbo.equity_purchase
    cheque = (1 + a.transaction_fees) * equity_purchase_at(offer, a) + constant
    m = lbo.exit_multiple if exit_multiple is None else exit_multiple
    proceeds = (proj.ebitda[year] * m - lbo.senior_end[year - 1] - lbo.sub_end[year - 1]
                + lbo.cash_end[year - 1] - a.minorities - a.other_adjustments)
    if proceeds <= 0 or cheque <= 0:
        return None
    return (proceeds / cheque) ** (1 / year) - 1
