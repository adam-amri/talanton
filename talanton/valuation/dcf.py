"""DCF: discounting free cash flows.

Two terminal values are computed side by side: perpetual growth (Gordon-Shapiro)
and exit multiple. The first year is prorated: only the part of the fiscal year
after the valuation date counts.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.assumptions import Assumptions
from ..model.projections import Projection


@dataclass
class Dcf:
    fcf: list[float]                 # free cash flows, full fiscal years
    stub: float                      # fraction of the first fiscal year still to run
    weights: list[float]
    times: list[float]               # discounting periods, in years
    factors: list[float]
    pv_fcf: float                    # sum of discounted cash flows
    end_time: float                  # time to the end of the last fiscal year
    tv_gordon: float
    pv_tv_gordon: float
    ev_gordon: float
    tv_multiple: float
    pv_tv_multiple: float
    ev_multiple: float
    equity_gordon: float
    equity_multiple: float
    share_gordon: float
    share_multiple: float

    @property
    def tv_share_gordon(self) -> float:
        return self.pv_tv_gordon / self.ev_gordon

    @property
    def tv_share_multiple(self) -> float:
        return self.pv_tv_multiple / self.ev_multiple


def free_cash_flows(proj: Projection, a: Assumptions) -> list[float]:
    return [e * (1 - a.tax_rate) + d - c - v
            for e, d, c, v in zip(proj.ebit, proj.da, proj.capex, proj.change_nwc)]


def timeline(proj: Projection, a: Assumptions) -> tuple[float, list[float], list[float], float]:
    """Returns (stub, weights, discounting periods, time to the end of the plan)."""
    n = a.n
    stub = max(0.0, min(1.0, (proj.ends[0] - a.valuation_date).days / 365))
    mid = a.mid_year
    weights = [stub] + [1.0] * (n - 1)
    times = [stub * (1 - 0.5 * mid)] + [stub + (k - 1) - 0.5 * mid for k in range(2, n + 1)]
    return stub, weights, times, stub + n - 1


def value_per_share(ev: float, a: Assumptions) -> float:
    return (ev - a.bridge) / a.diluted_shares


def ev_gordon(fcf, weights, times, wacc: float, g: float) -> float:
    """Enterprise value, perpetual growth method (also used by the sensitivities)."""
    pv = sum(x * w / (1 + wacc) ** t for x, w, t in zip(fcf, weights, times))
    return pv + fcf[-1] * (1 + g) / (wacc - g) / (1 + wacc) ** times[-1]


def ev_multiple(fcf, weights, times, end_time: float, final_ebitda: float, wacc: float, multiple: float) -> float:
    """Enterprise value, exit multiple method (also used by the sensitivities)."""
    pv = sum(x * w / (1 + wacc) ** t for x, w, t in zip(fcf, weights, times))
    return pv + final_ebitda * multiple / (1 + wacc) ** end_time


def compute_dcf(proj: Projection, a: Assumptions) -> Dcf:
    fcf = free_cash_flows(proj, a)
    stub, weights, times, end_time = timeline(proj, a)
    w, g = a.wacc, a.terminal_growth
    factors = [(1 + w) ** -t for t in times]
    pv = sum(x * p * f for x, p, f in zip(fcf, weights, factors))
    tv_g = fcf[-1] * (1 + g) / (w - g)
    pv_tv_g = tv_g * factors[-1]
    tv_m = proj.ebitda[-1] * a.exit_multiple
    pv_tv_m = tv_m / (1 + w) ** end_time
    ev_g, ev_m = pv + pv_tv_g, pv + pv_tv_m
    return Dcf(
        fcf=fcf, stub=stub, weights=weights, times=times, factors=factors, pv_fcf=pv,
        end_time=end_time, tv_gordon=tv_g, pv_tv_gordon=pv_tv_g, ev_gordon=ev_g,
        tv_multiple=tv_m, pv_tv_multiple=pv_tv_m, ev_multiple=ev_m,
        equity_gordon=ev_g - a.bridge, equity_multiple=ev_m - a.bridge,
        share_gordon=value_per_share(ev_g, a), share_multiple=value_per_share(ev_m, a),
    )
