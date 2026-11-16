"""Merger model: is buying the target accretive or dilutive to the acquirer's earnings per share?

A deliberately simple, first-pass analysis on last-twelve-month earnings:
  - the acquirer pays a premium over the target's share price, partly in new
    shares issued at its own share price and partly in cash raised as new debt;
  - the target's existing debt is assumed (its interest is already in its earnings);
  - synergies are a pre-tax, run-rate amount;
  - transaction fees are financed with debt but kept out of run-rate earnings.
Not modelled: purchase price allocation (no amortisation of acquired
intangibles), refinancing of the target's debt, integration costs.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.assumptions import Assumptions
from ..restatement.statements import Company
from .comps import Comparable
from .lbo import equity_purchase_at


@dataclass
class MergerTerms:
    premium: float = 0.30            # over the target's share price
    stock_pct: float = 0.5           # share of the price paid in acquirer shares
    synergies: float = 0.0           # pre-tax, run-rate, in millions
    debt_rate: float = 0.065         # pre-tax cost of the acquisition debt
    tax_rate: float = 0.25
    fees_pct: float = 0.02           # transaction fees, in % of the price paid for the shares


@dataclass
class Merger:
    offer_price: float
    equity_purchase: float
    stock_consideration: float
    cash_consideration: float
    fees: float
    new_debt: float
    new_shares: float
    exchange_ratio: float            # acquirer shares received per target share
    target_ownership: float          # share of the combined company held by former target holders
    acquirer_eps: float
    pro_forma_net_income: float
    pro_forma_shares: float
    pro_forma_eps: float
    accretion: float                 # pro forma EPS / standalone EPS - 1
    breakeven_synergies: float       # pre-tax synergies that leave EPS unchanged
    pro_forma_net_debt: float
    pro_forma_ebitda: float
    pro_forma_leverage: float


def compute_merger(acquirer: Comparable, target: Company, a: Assumptions, terms: MergerTerms) -> Merger:
    if not 0 <= terms.stock_pct <= 1:
        raise ValueError("stock_pct must be between 0 and 1.")
    acq = acquirer.company
    ni_a, ni_t = acq.ltm["net_income_adjusted"], target.ltm["net_income_adjusted"]
    if acquirer.quote.price <= 0 or acq.shares <= 0:
        raise ValueError("The acquirer needs a positive share price and share count.")
    offer = a.price * (1 + terms.premium)
    equity_purchase = equity_purchase_at(offer, a)
    stock = terms.stock_pct * equity_purchase
    cash = equity_purchase - stock
    fees = terms.fees_pct * equity_purchase
    new_debt = cash + fees
    new_shares = stock / acquirer.quote.price
    after_tax = 1 - terms.tax_rate
    interest = new_debt * terms.debt_rate * after_tax
    pf_ni = ni_a + ni_t + terms.synergies * after_tax - interest
    pf_shares = acq.shares + new_shares
    eps_a = ni_a / acq.shares
    pf_eps = pf_ni / pf_shares
    breakeven = (eps_a * pf_shares - ni_a - ni_t + interest) / after_tax
    net_debt = (acq.balance["debt"] - acq.balance["cash"] + acq.balance["minorities"]
                + a.net_debt + a.minorities + new_debt)
    ebitda = acq.ltm["ebitda_adjusted"] + target.ltm["ebitda_adjusted"] + terms.synergies
    return Merger(
        offer_price=offer, equity_purchase=equity_purchase, stock_consideration=stock,
        cash_consideration=cash, fees=fees, new_debt=new_debt, new_shares=new_shares,
        exchange_ratio=terms.stock_pct * offer / acquirer.quote.price,
        target_ownership=new_shares / pf_shares, acquirer_eps=eps_a, pro_forma_net_income=pf_ni,
        pro_forma_shares=pf_shares, pro_forma_eps=pf_eps,
        accretion=pf_eps / eps_a - 1 if eps_a > 0 else float("nan"),
        breakeven_synergies=breakeven, pro_forma_net_debt=net_debt, pro_forma_ebitda=ebitda,
        pro_forma_leverage=net_debt / ebitda if ebitda > 0 else float("nan"),
    )
