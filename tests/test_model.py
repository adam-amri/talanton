"""Calculation engine: accounting and financial identities that must always hold."""

import copy
from datetime import date

import pytest

from talanton.engine import compute, compute_scenarios
from talanton.model import ModelConfig, Settings, apply_overrides, edate, load_config, project
from talanton.valuation import MergerTerms, compute_dcf, compute_lbo, compute_merger, irr_at, quartile, simulate
from talanton.valuation.dcf import ev_gordon
from talanton.valuation.lbo import equity_purchase_at, price_for_equity

from .conftest import CONFIG


def test_projected_balance_sheet_balances(result):
    p = result.proj
    for assets, le in zip(p.total_assets, p.total_liabilities_equity):
        assert assets == pytest.approx(le, rel=1e-12)


def test_cash_follows_the_flows(result):
    p, a = result.proj, result.a
    cash = result.target.last["cash"]
    for t in range(a.n):
        flow = p.net_income[t] + p.da[t] - p.change_nwc[t] - p.capex[t] - a.distributions[t]
        assert p.change_cash[t] == pytest.approx(flow)
        cash += flow
        assert p.cash[t] == pytest.approx(cash)


def test_first_year_anchored_on_the_last_twelve_months(result):
    target, p = result.target, result.proj
    assert p.revenue[0] == pytest.approx(target.ltm["revenue"])
    assert p.ebitda[0] == pytest.approx(target.ltm["ebitda_adjusted"])


def test_market_inputs_come_from_fred(inputs, result):
    a = result.a
    assert a.risk_free_rate == pytest.approx(0.0488)                    # DGS10 on the share price date
    assert a.senior_rate == pytest.approx(0.0388 + 0.0350)              # SOFR + single-B spread
    assert a.sub_rate == pytest.approx(a.senior_rate + 0.03)
    assert "2.22%" in a.notes["terminal_growth"]                        # breakeven inflation, for reference


def test_auto_beta_prefers_the_sector_when_the_regression_is_weak(inputs, result):
    a = result.a
    d_e = inputs.target.balance["debt"] / (15.59 * 285.5)
    assert inputs.market.beta[2] < 0.15 and inputs.market.industry.name == "Recreation"
    assert (a.raw_beta, a.blume_weight) == (pytest.approx(0.74 * (1 + 0.75 * d_e)), 1.0)
    regression = compute(inputs, ModelConfig(settings=Settings(beta_method="regression"))).a
    assert regression.raw_beta == pytest.approx(inputs.market.beta[0]) and regression.blume_weight == 0.67
    assert regression.wacc < a.wacc


def test_wacc(result):
    a = result.a
    ke = a.risk_free_rate + (a.blume_weight * a.raw_beta + 1 - a.blume_weight) * a.equity_risk_premium
    assert a.wacc == pytest.approx((1 - a.debt_weight) * ke + a.debt_weight * a.cost_of_debt * 0.75)


def test_treasury_stock_method(result):
    a = copy.deepcopy(result.a)
    assert a.option_shares(15.59) == 0.0 and a.diluted_shares == pytest.approx(285.5)    # strike 19.31: out of the money
    assert a.option_shares(25.0) == pytest.approx(8.022 * (1 - 19.31 / 25.0))
    a.rsus, a.other_dilution = 2.0, 1.0
    assert a.diluted_shares_at(25.0) == pytest.approx(288.5 + 8.022 * (1 - 19.31 / 25.0))
    for price in (10.0, 19.31, 30.0):                                                    # both sides of the strike
        assert price_for_equity(equity_purchase_at(price, a), a) == pytest.approx(price)


def test_dcf_recomputed_by_hand(result):
    a, p, d = result.a, result.proj, result.dcf
    assert d.stub == pytest.approx((date(2026, 12, 31) - date(2026, 9, 30)).days / 365)
    fcf = [(p.ebit[t] * (1 - a.tax_rate) + p.da[t] - p.capex[t] - p.change_nwc[t]) for t in range(a.n)]
    f, w, g = d.stub, a.wacc, a.terminal_growth
    value = fcf[0] * f / (1 + w) ** (f / 2)
    value += sum(fcf[k] / (1 + w) ** (f + k - 0.5) for k in range(1, a.n))
    value += fcf[-1] * (1 + g) / (w - g) / (1 + w) ** (f + a.n - 1.5)
    assert d.ev_gordon == pytest.approx(value)
    assert d.share_gordon == pytest.approx((value - a.debt + a.cash) / a.diluted_shares)
    assert ev_gordon(d.fcf, d.weights, d.times, w, g) == pytest.approx(d.ev_gordon)


def test_dcf_without_stub_or_mid_year(result):
    a = copy.deepcopy(result.a)
    a.valuation_date, a.mid_year = date(2025, 12, 31), 0
    d = compute_dcf(project(result.target, a), a)
    assert d.times == pytest.approx([1, 2, 3, 4, 5, 6]) and d.weights == [1.0] * 6


def test_lbo_sources_equal_uses(result):
    lbo = result.lbo
    assert lbo.senior_debt + lbo.sub_debt + lbo.closing_cash + lbo.sponsor_equity == pytest.approx(lbo.total_uses)
    assert lbo.senior_debt == pytest.approx(5.0 * result.target.ltm["ebitda_adjusted"]) and lbo.sub_debt == 0.0
    offer = 15.59 * 1.30                                               # above the strike: options count
    assert lbo.diluted_shares == pytest.approx(285.5 + 8.022 * (1 - 19.31 / offer))
    assert lbo.equity_purchase == pytest.approx(offer * lbo.diluted_shares)


def test_lbo_debt_falls_by_the_cash_available(result):
    lbo, a = result.lbo, result.a
    debt = lbo.senior_debt
    for k in range(a.holding_period):
        assert lbo.senior_interest[k] == pytest.approx(debt * a.senior_rate)
        assert lbo.amortization[k] + lbo.sweep[k] == pytest.approx(lbo.fcf[k])   # 100% sweep
        debt -= lbo.fcf[k]
        assert lbo.senior_end[k] == pytest.approx(debt)
        assert lbo.cash_end[k] == pytest.approx(a.min_cash)


def test_lbo_two_tranches_with_pik(result):
    a = copy.deepcopy(result.a)
    a.senior_leverage, a.sub_leverage, a.sub_pik_rate, a.cash_sweep = 4.0, 1.5, 0.04, 0.5
    lbo = compute_lbo(result.target, result.proj, a)
    ebitda = result.target.ltm["ebitda_adjusted"]
    assert lbo.sub_debt == pytest.approx(1.5 * ebitda)
    assert lbo.financing_fees == pytest.approx(a.financing_fees * 5.5 * ebitda)
    assert lbo.sub_end[-1] == pytest.approx(lbo.sub_debt * 1.04 ** a.holding_period)   # PIK compounds, no repayment
    assert lbo.sub_interest[0] == pytest.approx(lbo.sub_debt * a.sub_rate)
    pretax = result.proj.ebit[1] - lbo.senior_interest[0] - lbo.sub_interest[0] - lbo.sub_pik[0]
    assert lbo.net_income[0] == pytest.approx(pretax * 0.75)
    assert lbo.fcf[0] == pytest.approx(lbo.net_income[0] + lbo.sub_pik[0] + result.proj.da[1]
                                       - result.proj.capex[1] - result.proj.change_nwc[1])
    assert lbo.cash_end[-1] > a.min_cash                                               # half the excess cash is kept
    assert lbo.senior_debt + lbo.sub_debt + lbo.closing_cash + lbo.sponsor_equity == pytest.approx(lbo.total_uses)


def test_lbo_irr_solves_the_net_present_value(result):
    lbo, h = result.lbo, result.a.holding_period
    assert -lbo.sponsor_equity + lbo.exit_equity / (1 + lbo.irr) ** h == pytest.approx(0.0, abs=1e-6)
    assert lbo.moic == pytest.approx((1 + lbo.irr) ** h)


@pytest.mark.parametrize("delta,sub,strike", [(0.0, 0.0, 19.31), (-1.0, 1.0, 19.31), (1.5, 0.0, 8.0), (3.0, 0.5, 19.31)])
def test_lbo_maximum_price_round_trip(result, delta, sub, strike):
    """Buying at the computed maximum price must give exactly the targeted IRR."""
    a = copy.deepcopy(result.a)
    a.exit_multiple_delta, a.sub_leverage, a.sub_pik_rate, a.option_strike = delta, sub, 0.03, strike
    proj = project(result.target, a)
    for target_irr, price in compute_lbo(result.target, proj, a).max_price.items():
        a2 = copy.deepcopy(a)
        a2.acquisition_premium = price / a.price - 1
        assert compute_lbo(result.target, proj, a2).irr == pytest.approx(target_irr, abs=1e-10)


def test_sensitivities_central_cell_is_the_base_case(result):
    s, d, lbo = result.sens, result.dcf, result.lbo
    assert s.dcf_gordon[2][2] == pytest.approx(d.share_gordon)
    assert s.dcf_multiple[2][2] == pytest.approx(d.share_multiple)
    assert s.lbo_exit[2][2] == pytest.approx(lbo.irr) and s.lbo_premium[2][2] == pytest.approx(lbo.irr)
    assert s.exit_years == (3, 4, 5)
    assert s.lbo_premium[0][2] > s.lbo_premium[4][2]            # the more you pay, the less the fund earns
    assert s.lbo_premium[2][0] < s.lbo_premium[2][4]            # the higher the exit multiple, the more it earns


def test_irr_at_matches_a_full_recomputation(result):
    a = copy.deepcopy(result.a)
    a.acquisition_premium = 0.40
    full = compute_lbo(result.target, result.proj, a)
    fast = irr_at(result.target, result.proj, result.a, result.lbo, premium=0.40, exit_multiple=full.exit_multiple)
    assert fast == pytest.approx(full.irr)


def test_quartiles_like_excel():
    assert quartile([1, 2, 3, 4, 5], 0.25) == 2
    assert quartile([1, 2, 3, 4], 0.25) == 1.75
    assert quartile([4, 1, 3, 2], 0.5) == 2.5
    assert quartile([], 0.5) is None


def test_non_meaningful_multiples_are_excluded(result):
    comps = result.comps
    funko = next(p for p in comps.peers if p.company.ticker == "FNKO")
    assert funko.multiple("pe", comps.cap) is None                # P/E above the cap
    ev = 57.111136 * 7.125 + (178.657 + 17.207 + 1.5) - 41.605 + 0.352
    ebitda = (-45.543 + 27.458 + 51.517) + (59.097 + 45.567 - 44.319)
    assert funko.multiple("ev_ebitda", comps.cap) == pytest.approx(ev / ebitda)
    assert len(comps.values("ev_ebitda")) == 5 and len(comps.values("pe")) == 4
    assert comps.industry.ev_ebitda == 10.39


def test_football_field_bounds_are_ordered(result):
    for label, low, high in result.football:
        assert low is not None and high is not None and low <= high, label


def test_edate():
    assert edate(date(2025, 12, 31), 12) == date(2026, 12, 31)
    assert edate(date(2024, 2, 29), 12) == date(2025, 2, 28)


def test_overrides_absolute_and_relative(result):
    a = copy.deepcopy(result.a)
    base_growth = list(a.revenue_growth)
    changed = apply_overrides(a, {"acquisition_premium": 0.4, "ebitda_margin": 0.13,
                                  "revenue_growth": {"shift": 0.01}, "senior_leverage": {"scale": 0.8},
                                  "valuation_date": date(2026, 11, 9)})
    assert changed == ["acquisition_premium", "ebitda_margin", "revenue_growth", "senior_leverage", "valuation_date"]
    assert a.acquisition_premium == 0.4 and a.ebitda_margin == [0.13] * 6 and a.senior_leverage == 4.0
    assert a.revenue_growth == pytest.approx([g + 0.01 for g in base_growth])
    assert "Moved from the default" in a.notes["revenue_growth"]
    for bad in ({"unknown": 1}, {"n": 8}, {"ebitda_margin": [0.1, 0.2]}, {"tax_rate": {"shifted": 1}}):
        with pytest.raises(ValueError):
            apply_overrides(a, bad)


def test_config_file_settings_and_scenarios(inputs, tmp_path):
    cfg = load_config(CONFIG)
    assert list(cfg.scenarios) == ["bull", "bear", "mezzanine"] and cfg.settings.years == 6
    results = compute_scenarios(inputs, cfg)
    assert results["bear"].dcf.share_gordon < results["base"].dcf.share_gordon < results["bull"].dcf.share_gordon
    assert results["mezzanine"].lbo.sub_debt > 0 and results["mezzanine"].lbo.irr > results["base"].lbo.irr
    assert results["bull"].scenario == "bull" and "revenue_growth" in results["bull"].overrides
    with pytest.raises(ValueError, match="Unknown scenario"):
        compute(inputs, cfg, "boom")
    for text in ("[settings]\nyears = 12\n", "[settings]\nbeta_method = 'guess'\n", "[settings]\ncolour = 1\n",
                 "[scenarios]\nbull = 1\n"):
        bad = tmp_path / "bad.toml"
        bad.write_text(text)
        with pytest.raises(ValueError):
            load_config(bad)


def test_live_overrides_take_precedence(inputs):
    cfg = load_config(CONFIG)
    r = compute(inputs, cfg, "bull", overrides={"exit_multiple_delta": 2.0})
    assert r.a.exit_multiple_delta == 2.0 and r.a.notes["exit_multiple_delta"] == "Value set by the app."


def test_more_projection_years_lengthen_the_holding_period(inputs):
    r = compute(inputs, ModelConfig(settings=Settings(years=8)))
    assert r.a.n == 8 and len(r.proj.revenue) == 8 and r.a.holding_period == 7
    assert len(r.lbo.senior_end) == 7 and r.sens.exit_years == (5, 6, 7)
    assert r.lbo.moic == pytest.approx((1 + r.lbo.irr) ** 7)


def test_leases_can_be_added_to_the_bridge(inputs, result):
    r = compute(inputs, ModelConfig(settings=Settings(include_leases=True)))
    assert r.a.other_adjustments == pytest.approx(351.593)
    assert r.dcf.share_gordon == pytest.approx(result.dcf.share_gordon - 351.593 / 285.5)
    with pytest.raises(ValueError, match="Unknown industry"):
        from talanton.engine import collect
        from .conftest import ADJUSTMENTS, CACHE
        collect("MAT", [], CACHE, True, ADJUSTMENTS, Settings(industry="Toys"), log=lambda *a: None)


def test_monte_carlo_is_reproducible_and_centred(result):
    mc = simulate(result.target, result.a, draws=400, seed=1)
    again = simulate(result.target, result.a, draws=400, seed=1)
    assert mc.values == again.values and mc.values == sorted(mc.values)
    assert mc.base_case == pytest.approx(result.dcf.share_gordon)
    assert mc.p5 < mc.p25 < mc.median < mc.p75 < mc.p95 and mc.p25 < mc.base_case < mc.p75
    assert 0 <= mc.prob_above_price <= 1 and len(mc.values) + mc.discarded == 400
    flat = simulate(result.target, result.a, draws=20, growth_sd=0, margin_sd=0, wacc_sd=0, terminal_growth_sd=0)
    assert flat.values == pytest.approx([result.dcf.share_gordon] * 20)


def test_merger_accretion(inputs, result):
    has = next(p for p in inputs.peers if p.company.ticker == "HAS")
    terms = MergerTerms(premium=0.30, stock_pct=0.5, synergies=150.0)
    m = compute_merger(has, inputs.target, result.a, terms)
    assert m.stock_consideration + m.cash_consideration == pytest.approx(m.equity_purchase)
    assert m.new_shares == pytest.approx(m.stock_consideration / 120.92)
    ni = (has.company.ltm["net_income_adjusted"] + inputs.target.ltm["net_income_adjusted"]
          + 150 * 0.75 - m.new_debt * 0.065 * 0.75)
    assert m.pro_forma_eps == pytest.approx(ni / (has.company.shares + m.new_shares))
    at_breakeven = compute_merger(has, inputs.target, result.a,
                                  MergerTerms(premium=0.30, stock_pct=0.5, synergies=m.breakeven_synergies))
    assert at_breakeven.accretion == pytest.approx(0.0, abs=1e-12)
    all_cash = compute_merger(has, inputs.target, result.a, MergerTerms(stock_pct=0.0))
    assert all_cash.new_shares == 0 and all_cash.new_debt > m.new_debt
