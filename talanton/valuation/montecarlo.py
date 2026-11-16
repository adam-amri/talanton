"""Monte Carlo on the DCF: a distribution of values instead of a single figure.

Each draw moves four assumptions at once, with independent normal shocks:
the revenue growth path and the EBITDA margin path (shifted in parallel), the
WACC and the perpetual growth rate. The model is projected again and valued
with the perpetual-growth DCF. The standard deviations are inputs: they state
how uncertain you think each assumption is, they are not estimated from data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from ..model.assumptions import Assumptions
from ..model.projections import project
from ..restatement.statements import Company
from .comps import quartile
from .dcf import ev_gordon, free_cash_flows, timeline, value_per_share

MIN_SPREAD = 0.005          # a draw where WACC - g falls below this is discarded


@dataclass
class MonteCarlo:
    values: list[float]              # value per share, sorted
    draws: int
    discarded: int
    mean: float
    p5: float
    p25: float
    median: float
    p75: float
    p95: float
    prob_above_price: float          # share of draws worth more than the current share price
    base_case: float
    shocks: dict[str, float]


def simulate(company: Company, a: Assumptions, draws: int = 2000, seed: int = 7, growth_sd: float = 0.01,
             margin_sd: float = 0.01, wacc_sd: float = 0.005, terminal_growth_sd: float = 0.0025) -> MonteCarlo:
    rng = random.Random(seed)
    values, discarded = [], 0
    for _ in range(draws):
        dg, dm = rng.gauss(0, growth_sd), rng.gauss(0, margin_sd)
        wacc = a.wacc + rng.gauss(0, wacc_sd)
        g = a.terminal_growth + rng.gauss(0, terminal_growth_sd)
        if wacc - g < MIN_SPREAD:
            discarded += 1
            continue
        shocked = replace(a, revenue_growth=[x + dg for x in a.revenue_growth],
                          ebitda_margin=[x + dm for x in a.ebitda_margin])
        proj = project(company, shocked)
        _, weights, times, _ = timeline(proj, shocked)
        values.append(value_per_share(ev_gordon(free_cash_flows(proj, shocked), weights, times, wacc, g), a))
    if not values:
        raise ValueError("Monte Carlo: every draw was discarded (WACC too close to the perpetual growth rate).")
    values.sort()
    base = project(company, a)
    _, weights, times, _ = timeline(base, a)
    base_case = value_per_share(ev_gordon(free_cash_flows(base, a), weights, times, a.wacc, a.terminal_growth), a)
    return MonteCarlo(
        values=values, draws=draws, discarded=discarded, mean=sum(values) / len(values),
        p5=quartile(values, 0.05), p25=quartile(values, 0.25), median=quartile(values, 0.5),
        p75=quartile(values, 0.75), p95=quartile(values, 0.95),
        prob_above_price=sum(v > a.price for v in values) / len(values), base_case=base_case,
        shocks={"revenue_growth": growth_sd, "ebitda_margin": margin_sd, "wacc": wacc_sd,
                "terminal_growth": terminal_growth_sd},
    )
