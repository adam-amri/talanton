"""Projection of the three financial statements (income statement, cash flows, balance sheet).

"Standalone" case, with no transaction: debt stays constant and cash absorbs
the flows. The projected balance sheet balances by construction; the Checks
sheet of the workbook and the tests verify it.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from ..restatement.statements import Company
from .assumptions import Assumptions


def edate(d: date, months: int) -> date:
    """Equivalent of Excel's EDATE: same day, `months` later."""
    total = d.month - 1 + months
    year, m = d.year + total // 12, total % 12 + 1
    return date(year, m, min(d.day, calendar.monthrange(year, m)[1]))


@dataclass
class Projection:
    ends: list[date]                 # ends of the projected fiscal years
    revenue: list[float]
    ebitda: list[float]
    da: list[float]
    ebit: list[float]
    interest_expense: list[float]
    interest_income: list[float]
    pretax_income: list[float]
    income_tax: list[float]
    net_income: list[float]
    capex: list[float]
    nwc: list[float]
    change_nwc: list[float]
    change_cash: list[float]
    cash: list[float]
    operating_current_assets: list[float]
    net_fixed_assets: list[float]
    operating_current_liabilities: list[float]
    equity: list[float]
    total_assets: list[float]
    total_liabilities_equity: list[float]
    # constant lines
    debt: float
    goodwill: float
    other_assets: float
    other_liabilities: float


def project(company: Company, a: Assumptions) -> Projection:
    last = company.last
    debt, goodwill = last["debt"], last["goodwill"]
    other_assets, other_liabilities = last["other_assets"], last["other_liabilities"]
    revenue_p, cash_p, nwc_p = last["revenue"], last["cash"], last["nwc"]
    fixed_p, equity_p = last["net_fixed_assets"], last["equity"]
    end_p = company.fiscal_years[-1]
    p = Projection(*[[] for _ in range(21)], debt=debt, goodwill=goodwill,
                   other_assets=other_assets, other_liabilities=other_liabilities)
    for t in range(a.n):
        revenue = revenue_p * (1 + a.revenue_growth[t])
        ebitda = revenue * a.ebitda_margin[t]
        da = revenue * a.da_pct[t]
        ebit = ebitda - da
        interest_expense = debt * a.cost_of_debt
        interest_income = cash_p * a.cash_yield
        pretax = ebit - interest_expense + interest_income
        tax = max(0.0, pretax) * a.tax_rate
        net_income = pretax - tax
        capex = revenue * a.capex_pct[t]
        nwc = revenue * a.nwc_pct[t]
        change_nwc = nwc - nwc_p
        change_cash = net_income + da - change_nwc - capex - a.distributions[t]
        cash = cash_p + change_cash
        op_liabilities = revenue * a.op_liabilities_pct
        op_assets = nwc + op_liabilities
        fixed = fixed_p + capex - da
        equity = equity_p + net_income - a.distributions[t]
        end = edate(end_p, 12)
        for name, value in (
            ("ends", end), ("revenue", revenue), ("ebitda", ebitda), ("da", da), ("ebit", ebit),
            ("interest_expense", interest_expense), ("interest_income", interest_income),
            ("pretax_income", pretax), ("income_tax", tax), ("net_income", net_income), ("capex", capex),
            ("nwc", nwc), ("change_nwc", change_nwc), ("change_cash", change_cash), ("cash", cash),
            ("operating_current_assets", op_assets), ("net_fixed_assets", fixed),
            ("operating_current_liabilities", op_liabilities), ("equity", equity),
            ("total_assets", cash + op_assets + fixed + goodwill + other_assets),
            ("total_liabilities_equity", op_liabilities + debt + other_liabilities + equity),
        ):
            getattr(p, name).append(value)
        revenue_p, cash_p, nwc_p, fixed_p, equity_p, end_p = revenue, cash, nwc, fixed, equity, end
    return p
