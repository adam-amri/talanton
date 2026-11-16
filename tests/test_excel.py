"""Excel workbook: the formulas must give back exactly the figures of the Python engine.

The reconciliation has LibreOffice recalculate the workbook. Without LibreOffice
on the machine these tests are skipped (the others still run).
"""

from datetime import date

import pytest
from openpyxl import load_workbook

from talanton.checks import find_libreoffice, recalculate, reconcile, verify
from talanton.engine import compute
from talanton.excel import SHEETS, build_workbook
from talanton.excel import styles as S
from talanton.model import ModelConfig, Settings

needs_libreoffice = pytest.mark.skipif(find_libreoffice() is None, reason="LibreOffice not installed")


def _write(res, folder):
    wb, registry = build_workbook(res, date(2026, 11, 16))
    file = folder / "model.xlsx"
    wb.save(file)
    return file, registry


def _check(res, folder):
    file, registry = _write(res, folder)
    assert recalculate(file)
    rec = reconcile(file, registry, res.checkpoints())
    assert rec.gaps == {} and rec.formula_errors == [] and rec.empty_cells == []
    return file, rec


def test_workbook_structure(result, tmp_path):
    file, registry = _write(result, tmp_path)
    wb = load_workbook(file)
    assert wb.sheetnames == list(SHEETS)
    formulas = [c.value for ws in wb for row in ws.iter_rows() for c in row
                if isinstance(c.value, str) and c.value.startswith("=")]
    assert len(formulas) > 800
    assert not [f for f in formulas if "#REF" in f]
    assert set(result.checkpoints()) <= set(registry)


def test_no_hard_coded_figure_in_the_computation_sheets(result, tmp_path):
    file, _ = _write(result, tmp_path)
    for sheet in ("Projections", "DCF", "LBO", "Sensitivities"):
        for row in load_workbook(file)[sheet].iter_rows(min_row=5):
            for c in row[1:]:
                if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                    # only exception: the exit years of the sensitivity table
                    assert sheet == "Sensitivities" and c.value in result.sens.exit_years, f"{sheet}!{c.coordinate}"


def test_python_verifications(result):
    assert "ERROR" not in [level for level, _ in verify(result)]


def test_themes(result, inputs, tmp_path):
    assert S.make_theme("midnight", {"ink": "#0b3d2e"}).ink == "0B3D2E"
    for bad in (("neon", {}), ("classic", {"ink": "blue"}), ("classic", {"paper": "FFFFFF"})):
        with pytest.raises(ValueError):
            S.make_theme(*bad)
    res = compute(inputs, ModelConfig(settings=Settings(theme="forest", theme_overrides={"accent": "AA0000"})))
    file, _ = _write(res, tmp_path)
    wb = load_workbook(file)
    assert wb["DCF"].sheet_properties.tabColor.rgb.endswith("AA0000")
    assert wb["Summary"]["A1"].font.color.rgb.endswith("14532D") and wb["Summary"]["A1"].font.name == "Calibri"
    S.use(S.THEMES["classic"])


@needs_libreoffice
def test_excel_equals_python_base_case(result, tmp_path):
    _, rec = _check(result, tmp_path)
    assert rec.status.startswith("Consistent") and rec.n_formulas > 900


@needs_libreoffice
def test_excel_equals_python_after_changing_the_assumptions(inputs, tmp_path):
    """Same reconciliation after shaking the assumptions: the formulas follow."""
    overrides = {
        "revenue_growth": [0.06, 0.05, 0.04, 0.03, 0.03, 0.025], "ebitda_margin": [0.12, 0.125, 0.13, 0.135, 0.14, 0.145],
        "distributions": [308.408, 200, 200, 200, 200, 200], "other_dilution": 6.5, "rsus": 3.0, "option_strike": 12.0,
        "other_adjustments": 120, "tax_rate": 0.27, "mid_year": 0, "valuation_date": date(2026, 11, 9),
        "terminal_growth": 0.025, "exit_multiple": 10.0, "acquisition_premium": 0.4, "senior_leverage": 3.5,
        "senior_rate": 0.095, "senior_amortization": 0.05, "cash_sweep": 0.5, "sub_leverage": 1.5, "sub_rate": 0.11,
        "sub_pik_rate": 0.03, "exit_multiple_delta": -1.0, "target_irr": 0.18, "transaction_fees": 0.03,
        "wacc_step": 0.0025, "multiple_step": 0.5, "blume_weight": 0.8, "specific_premium": 0.01}
    res = compute(inputs, overrides=overrides)
    assert res.lbo.cash_end[-1] > res.a.min_cash and res.a.option_shares(res.a.price) > 0
    _check(res, tmp_path)


@needs_libreoffice
def test_excel_equals_python_with_eight_projected_years(inputs, tmp_path):
    res = compute(inputs, ModelConfig(settings=Settings(years=8)), overrides={"sub_leverage": 1.0})
    file, _ = _check(res, tmp_path)
    assert load_workbook(file)["Projections"]["J4"].value == "2033E"


@needs_libreoffice
def test_maximum_price_when_options_are_in_the_money(inputs, tmp_path):
    """Second branch of the maximum-price formula: the price exceeds the option strike."""
    res = compute(inputs, overrides={"option_strike": 5.0, "options": 20.0})
    assert res.lbo.max_price[res.a.target_irr] > 5.0
    _check(res, tmp_path)


@needs_libreoffice
def test_sensitivity_tables_and_summary(result, tmp_path):
    file, _ = _write(result, tmp_path)
    recalculate(file)
    wb = load_workbook(file, data_only=True)
    se, sm = wb["Sensitivities"], wb["Summary"]
    tables = ((5, result.sens.dcf_gordon), (13, result.sens.dcf_multiple),
              (21, result.sens.lbo_exit), (29, result.sens.lbo_premium))
    for top, expected in tables:
        for i, row in enumerate(expected):
            for j, value in enumerate(row[:3] if top == 21 else row):
                assert se.cell(row=top + 1 + i, column=3 + j).value == pytest.approx(value, rel=1e-9)
    rows = {sm.cell(row=r, column=1).value: (sm.cell(row=r, column=2).value, sm.cell(row=r, column=3).value)
            for r in range(1, 40)}
    for label, low, high in result.football:
        found = next(v for k, v in rows.items() if k and (k == label or k.startswith(label + " (")))
        assert found == pytest.approx((low, high), rel=1e-9)


@needs_libreoffice
def test_bloomberg_formulas_fall_back_on_the_recorded_price(inputs, tmp_path):
    """Without a Terminal the live formulas must show the price of the generation date."""
    res = compute(inputs, ModelConfig(settings=Settings(bloomberg_formulas=True)))
    file, registry = _write(res, tmp_path)
    cell = load_workbook(file)["Assumptions"]["C6"].value
    assert cell == '=IF(ISNUMBER(_xll.BDP("MAT US Equity","PX_LAST")),_xll.BDP("MAT US Equity","PX_LAST"),15.59)'
    assert recalculate(file)
    assert load_workbook(file, data_only=True)["Assumptions"]["C6"].value == 15.59
    rec = reconcile(file, registry, res.checkpoints())
    assert rec.gaps == {} and rec.formula_errors == []
