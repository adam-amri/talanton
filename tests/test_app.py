"""Interactive app: every chart builds, and the whole page runs on the example data."""

from pathlib import Path

import pytest

pytest.importorskip("plotly")

from talanton.app import charts                                   # noqa: E402
from talanton.engine import compute_scenarios                     # noqa: E402
from talanton.valuation import simulate                           # noqa: E402


def test_every_chart_builds(result, inputs):
    s = result.sens
    figures = [
        charts.football_field(result), charts.revenue_and_ebitda(result), charts.margins(result),
        charts.free_cash_flows(result), charts.value_bridge(result), charts.value_bridge(result, "multiple"),
        charts.heatmap(s.lbo_exit, ["a"] * 5, ["x", "y", "z"], "t", "x", "y", ".1%"),
        charts.comps_multiples(result), charts.debt_paydown(result), charts.sources_and_uses(result),
        charts.scenarios(compute_scenarios(inputs)), charts.monte_carlo(simulate(result.target, result.a, 200), 15.59),
        charts.accretion([(0.0, 0.05), (1.0, -0.02)]),
    ]
    assert all(len(f.data) >= 1 for f in figures)
    field = charts.football_field(result)
    assert list(field.data[0].y)[-1] == "Comps: EV / EBITDA"       # first method at the top
    assert field.data[0].base[-1] == pytest.approx(result.football[0][1])


def test_the_app_runs_on_the_example_and_reacts_to_a_slider():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "talanton" / "app" / "main.py"), default_timeout=120)
    app.run()
    assert not app.exception and "Mattel Inc. (MAT)" in [t.value for t in app.title]
    before = next(m.value for m in app.metric if m.label.startswith("Max price"))
    rate = next(s for s in app.slider if s.label == "Senior interest rate")
    rate.set_value(12.0).run()
    assert not app.exception and next(m.value for m in app.metric if m.label.startswith("Max price")) != before
