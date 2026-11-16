"""Sensitivity tables and ranges of the "football field".

Same computations as the formulas of the Sensitivities sheet: each cell redoes
the valuation with two assumptions moved.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.assumptions import Assumptions
from ..model.projections import Projection
from ..restatement.statements import Company
from .comps import Comps
from .dcf import Dcf, ev_gordon, ev_multiple, value_per_share
from .lbo import Lbo, irr_at

STEPS = (-2, -1, 0, 1, 2)


def exit_years(a: Assumptions) -> tuple[int, int, int]:
    h = a.holding_period
    return h - 2, h - 1, h


@dataclass
class Sensitivities:
    wacc: list[float]
    growth: list[float]
    dcf_multiples: list[float]
    lbo_multiples: list[float]
    premiums: list[float]
    exit_years: tuple[int, int, int]
    dcf_gordon: list[list[float]]            # rows: WACC; columns: perpetual growth
    dcf_multiple: list[list[float]]          # rows: WACC; columns: exit multiple
    lbo_exit: list[list[float | None]]       # rows: exit multiple; columns: exit year
    lbo_premium: list[list[float | None]]    # rows: premium; columns: exit multiple


def compute_sensitivities(company: Company, proj: Projection, a: Assumptions, dcf: Dcf, lbo: Lbo) -> Sensitivities:
    wacc = [a.wacc + k * a.wacc_step for k in STEPS]
    growth = [a.terminal_growth + k * a.growth_step for k in STEPS]
    m_dcf = [a.exit_multiple + k * a.multiple_step for k in STEPS]
    m_lbo = [lbo.exit_multiple + k * a.multiple_step for k in STEPS]
    premiums = [a.acquisition_premium + k * a.premium_step for k in STEPS]
    years = exit_years(a)
    t1 = [[value_per_share(ev_gordon(dcf.fcf, dcf.weights, dcf.times, w, g), a) for g in growth] for w in wacc]
    t2 = [[value_per_share(ev_multiple(dcf.fcf, dcf.weights, dcf.times, dcf.end_time,
                                       proj.ebitda[-1], w, m), a) for m in m_dcf] for w in wacc]
    t3 = [[irr_at(company, proj, a, lbo, exit_multiple=m, year=y) for y in years] for m in m_lbo]
    t4 = [[irr_at(company, proj, a, lbo, premium=p, exit_multiple=m) for m in m_lbo] for p in premiums]
    return Sensitivities(wacc, growth, m_dcf, m_lbo, premiums, years, t1, t2, t3, t4)


def football_field(a: Assumptions, comps: Comps, sens: Sensitivities, lbo: Lbo
                   ) -> list[tuple[str, float | None, float | None]]:
    """Ranges of value per share, method by method: (label, low, high)."""
    def core(table):                                     # 3 x 3 central cells
        cells = [table[i][j] for i in (1, 2, 3) for j in (1, 2, 3)]
        return min(cells), max(cells)

    rows = []
    for name, label in (("ev_ebitda", "Comps: EV / EBITDA"), ("ev_ebit", "Comps: EV / EBIT"), ("pe", "Comps: P/E")):
        implied = comps.implied.get(name, {})
        rows.append((label, implied.get("q1"), implied.get("q3")))
    rows.append(("DCF: perpetual growth", *core(sens.dcf_gordon)))
    rows.append(("DCF: exit multiple", *core(sens.dcf_multiple)))
    rows.append(("LBO: maximum price for a fund", lbo.max_price[a.target_irr_high], lbo.max_price[a.target_irr]))
    rows.append(("Current share price", a.price, a.price))
    return rows
