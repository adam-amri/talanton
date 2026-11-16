"""Writing the Excel workbook: nine sheets linked by real formulas.

Python only hard-codes published data and assumptions (in blue). Everything
else is a formula: changing a blue cell recalculates the model. The registry
returned maps each key figure to its cell, for the reconciliation with the
Python engine.
"""

from __future__ import annotations

from datetime import date

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter as L

from .. import __version__
from ..data.bloomberg import bdp
from ..engine import BASE, Result
from ..valuation.sensitivities import STEPS
from . import styles as S

SUMMARY, ASSUMPTIONS, HISTORICAL, PROJECTIONS, DCF, COMPS, LBO, SENSITIVITIES, CHECKS = (
    "Summary", "Assumptions", "Historical", "Projections", "DCF", "Comps", "LBO", "Sensitivities", "Checks")
SHEETS = (SUMMARY, ASSUMPTIONS, HISTORICAL, PROJECTIONS, DCF, COMPS, LBO, SENSITIVITIES, CHECKS)
NM = '"n.m."'            # "not meaningful", as written inside formulas


class Sheet:
    """One sheet, remembering the row of each line."""

    def __init__(self, wb: Workbook, name: str, tab_color: str):
        self.ws = wb.create_sheet(name)
        self.name = name
        self.rows: dict[str, int] = {}
        self.ws.sheet_view.showGridLines = False
        self.ws.sheet_properties.tabColor = tab_color

    def r(self, key: str) -> int:
        return self.rows[key]

    def a(self, key: str, col: str, fixed: bool = False) -> str:
        """Address inside the sheet itself."""
        return f"${col}${self.rows[key]}" if fixed else f"{col}{self.rows[key]}"

    def x(self, key: str, col: str) -> str:
        """Address seen from another sheet (always absolute)."""
        return f"'{self.name}'!${col}${self.rows[key]}"

    def xr(self, key: str, c1: str, c2: str) -> str:
        """Range of one row seen from another sheet."""
        r = self.rows[key]
        return f"'{self.name}'!${c1}${r}:${c2}${r}"

    def write(self, ref: str, value, style: str = "calc", fmt: str | None = None, **kw):
        cell = self.ws[ref]
        cell.value = value
        S.apply(cell, style, fmt, **kw)
        return cell

    def title(self, text: str, subtitle: str = "") -> None:
        self.ws["A1"].value = text
        self.ws["A1"].font = S.font(S.theme().ink, bold=True, size=14)
        if subtitle:
            self.ws["A2"].value = subtitle
            self.ws["A2"].font = S.font(S.theme().note, italic=True)

    def layout(self, lines: list[tuple], start: int, width: int, unit_col: str | None = "B") -> int:
        """Stacks the lines and writes their labels.

        ("#", text): section band; ("",): blank row; (key, label[, unit]): line.
        """
        r = start
        for line in lines:
            if line[0] == "#":
                S.band(self.ws, r, line[1], width)
            elif line[0]:
                self.rows[line[0]] = r
                self.ws.cell(row=r, column=1, value=line[1]).font = S.font()
                if len(line) > 2 and unit_col:
                    self.write(f"{unit_col}{r}", line[2], "note")
            r += 1
        return r


def build_workbook(res: Result, generated_on: date) -> tuple[Workbook, dict[str, tuple[str, str]]]:
    company, a, proj = res.target, res.a, res.proj
    n, nh = a.n, len(company.fiscal_years)
    theme = S.make_theme(res.settings.theme, res.settings.theme_overrides)
    S.use(theme)
    live = res.settings.bloomberg_formulas
    wb = Workbook()
    wb.remove(wb.active)
    sheets = {name: Sheet(wb, name, color) for name, color in (
        (SUMMARY, theme.ink), (ASSUMPTIONS, theme.tab_assumptions), (HISTORICAL, theme.tab_data),
        (PROJECTIONS, theme.tab_data), (DCF, theme.accent), (COMPS, theme.accent), (LBO, theme.accent),
        (SENSITIVITIES, theme.accent), (CHECKS, theme.tab_checks))}
    sm, asm, hi, pr, dcf, co, lbo, se, ck = (sheets[x] for x in SHEETS)

    HC = [L(3 + i) for i in range(nh)]         # columns of the historical fiscal years
    HL, HS = L(3 + nh), L(4 + nh)              # LTM column, sources column
    HD = HC[-1]                                # last closed fiscal year
    PB, PC = "B", [L(3 + i) for i in range(n)]  # base column, projected columns
    P1, PN = PC[0], PC[-1]
    C, D = "C", "D"
    years_h = [f"{d.year}A" for d in company.fiscal_years]
    years_p = [f"{d.year}E" for d in proj.ends]
    name = company.short_name
    registry: dict[str, tuple[str, str]] = {}

    def price_value(ticker: str, fallback: float):
        """A share price: a plain number, or a live Bloomberg formula that falls back on it."""
        if not live:
            return fallback
        f = bdp(ticker)
        return f"=IF(ISNUMBER({f}),{f},{fallback!r})"

    # ------------------------------------------------------------------ layouts
    asm.layout([
        ("#", "Market and bridge from enterprise value to equity value"),
        ("valuation_date", "Valuation date", "date"),
        ("price", "Share price", "$"),
        ("shares", "Shares outstanding", "millions"),
        ("options", "Stock options outstanding", "millions"),
        ("option_strike", "Average exercise price of the options", "$"),
        ("option_shares", "Net shares from options (treasury stock method)", "millions"),
        ("rsus", "Unvested restricted stock units", "millions"),
        ("other_dilution", "Other dilutive securities", "millions"),
        ("diluted_shares", "Diluted shares", "millions"),
        ("market_cap", "Market capitalisation", "$m"),
        ("debt", "Financial debt", "$m"),
        ("cash", "Cash and short-term investments", "$m"),
        ("minorities", "Non-controlling interests", "$m"),
        ("other_adjustments", "Other adjustments (pensions, leases...)", "$m"),
        ("net_debt", "Net financial debt", "$m"),
        ("bridge", "Total deducted from enterprise value", "$m"),
        ("enterprise_value", "Enterprise value at the current share price", "$m"),
        ("",),
        ("#", "Operations: one assumption per projected fiscal year"),
        ("years", "Fiscal year"),
        ("revenue_growth", "Revenue growth", "%"),
        ("ebitda_margin", "EBITDA margin", "% of revenue"),
        ("da_pct", "Depreciation and amortisation", "% of revenue"),
        ("capex_pct", "Capital expenditure", "% of revenue"),
        ("nwc_pct", "Net working capital", "% of revenue"),
        ("distributions", "Dividends and share buybacks", "$m"),
        ("",),
        ("op_liabilities_pct", "Operating current liabilities", "% of revenue"),
        ("tax_rate", "Corporate tax rate", "%"),
        ("cost_of_debt", "Pre-tax cost of debt", "%"),
        ("cash_yield", "Yield on cash", "%"),
        ("",),
        ("#", "Cost of capital and terminal value"),
        ("risk_free_rate", "Risk-free rate", "%"),
        ("equity_risk_premium", "Equity risk premium", "%"),
        ("raw_beta", "Raw beta", "x"),
        ("blume_weight", "Weight of the raw beta (Blume adjustment)", "x"),
        ("beta", "Beta used", "x"),
        ("specific_premium", "Company-specific risk premium", "%"),
        ("cost_of_equity", "Cost of equity", "%"),
        ("debt_weight", "Weight of debt in the financing", "%"),
        ("wacc", "Weighted average cost of capital (WACC)", "%"),
        ("terminal_growth", "Perpetual growth", "%"),
        ("exit_multiple", "Exit multiple EV/EBITDA (DCF)", "x"),
        ("mid_year", "Mid-year convention (1 = yes, 0 = no)", ""),
        ("",),
        ("#", "LBO"),
        ("acquisition_premium", "Acquisition premium over the share price", "%"),
        ("senior_leverage", "Senior acquisition debt", "x LTM EBITDA"),
        ("senior_rate", "Interest rate of the senior debt", "%"),
        ("senior_amortization", "Mandatory annual amortisation", "% initial senior"),
        ("cash_sweep", "Excess cash used for early repayment", "%"),
        ("sub_leverage", "Subordinated debt (mezzanine)", "x LTM EBITDA"),
        ("sub_rate", "Cash interest rate of the subordinated debt", "%"),
        ("sub_pik_rate", "Capitalised (PIK) interest rate of the subordinated debt", "%"),
        ("min_cash", "Minimum cash kept in the company", "$m"),
        ("transaction_fees", "Transaction fees", "% of EV"),
        ("financing_fees", "Financing fees", "% of new debt"),
        ("exit_multiple_delta", "Exit multiple minus entry multiple", "x"),
        ("target_irr", "IRR targeted by the fund", "%"),
        ("target_irr_high", "Targeted IRR, demanding case", "%"),
        ("",),
        ("#", "Sensitivity tables and cap on multiples"),
        ("wacc_step", "Step of the WACC", "%"),
        ("growth_step", "Step of perpetual growth", "%"),
        ("multiple_step", "Step of the multiples", "x"),
        ("premium_step", "Step of the acquisition premium", "%"),
        ("multiple_cap", "Highest multiple considered meaningful", "x"),
    ], start=4, width=3 + n)

    hi.layout([
        ("end", "Fiscal year ended"),
        ("#", "Income statement"),
        ("revenue", "Revenue"),
        ("growth", "  growth"),
        ("gross_profit", "Gross profit"),
        ("gross_margin", "  in % of revenue"),
        ("ebit", "Reported operating income (EBIT)"),
        ("da", "Depreciation and amortisation (D&A)"),
        ("ebitda_reported", "Reported EBITDA"),
        ("impairments", "Asset impairments added back"),
        ("ebitda_adj", "Analyst adjustments"),
        ("ebitda_adjusted", "Adjusted EBITDA"),
        ("ebitda_margin", "  adjusted EBITDA margin"),
        ("ebit_adjusted", "Adjusted EBIT"),
        ("interest_expense", "Interest expense"),
        ("interest_income", "Interest income"),
        ("pretax_income", "Pre-tax income"),
        ("income_tax", "Income tax"),
        ("effective_tax", "  effective tax rate"),
        ("net_income", "Net income attributable to shareholders"),
        ("net_income_adj", "Analyst adjustments (after tax)"),
        ("net_income_adjusted", "Adjusted net income"),
        ("sbc", "Memo: stock-based compensation"),
        ("#", "Cash flows"),
        ("cfo", "Cash flow from operations"),
        ("capex", "Capital expenditure"),
        ("fcf", "Free cash flow (operations - capex)"),
        ("buybacks", "Share buybacks"),
        ("dividends", "Dividends paid"),
        ("da_pct", "  D&A in % of revenue"),
        ("capex_pct", "  capex in % of revenue"),
        ("#", "Simplified balance sheet"),
        ("cash", "Cash and short-term investments"),
        ("operating_current_assets", "Operating current assets"),
        ("net_fixed_assets", "Net fixed assets (excluding goodwill)"),
        ("goodwill", "Goodwill"),
        ("other_assets", "Other non-current assets"),
        ("total_assets", "Total assets"),
        ("operating_current_liabilities", "Operating current liabilities"),
        ("debt", "Financial debt"),
        ("other_liabilities", "Other non-current liabilities"),
        ("equity", "Shareholders' equity"),
        ("total_liabilities_equity", "Total liabilities and equity"),
        ("gap", "Check: assets - liabilities and equity"),
        ("nwc", "Net working capital (NWC)"),
        ("nwc_pct", "  NWC in % of revenue"),
        ("op_liabilities_pct", "  operating liabilities in % of revenue"),
    ], start=5, width=4 + nh, unit_col=None)

    pr.layout([
        ("end", "Fiscal year ended"),
        ("#", "Income statement"),
        ("revenue", "Revenue"),
        ("growth", "  growth"),
        ("ebitda", "EBITDA"),
        ("margin", "  EBITDA margin"),
        ("da", "Depreciation and amortisation"),
        ("ebit", "Operating income (EBIT)"),
        ("interest_expense", "Interest expense"),
        ("interest_income", "Interest income"),
        ("pretax_income", "Pre-tax income"),
        ("income_tax", "Income tax"),
        ("net_income", "Net income"),
        ("#", "Cash flows"),
        ("capex", "Capital expenditure"),
        ("change_nwc", "Change in NWC"),
        ("distributions", "Dividends and share buybacks"),
        ("change_cash", "Change in cash"),
        ("#", "Balance sheet"),
        ("cash", "Cash and short-term investments"),
        ("operating_current_assets", "Operating current assets"),
        ("net_fixed_assets", "Net fixed assets (excluding goodwill)"),
        ("goodwill", "Goodwill"),
        ("other_assets", "Other non-current assets"),
        ("total_assets", "Total assets"),
        ("operating_current_liabilities", "Operating current liabilities"),
        ("debt", "Financial debt"),
        ("other_liabilities", "Other non-current liabilities"),
        ("equity", "Shareholders' equity"),
        ("total_liabilities_equity", "Total liabilities and equity"),
        ("gap", "Check: assets - liabilities and equity"),
        ("nwc", "Net working capital (NWC)"),
    ], start=5, width=2 + n, unit_col=None)

    dcf.layout([
        ("#", "Free cash flows"),
        ("ebit", "Operating income (EBIT)"),
        ("tax_on_ebit", "Tax on EBIT"),
        ("nopat", "Operating income after tax (NOPAT)"),
        ("da", "Depreciation and amortisation"),
        ("capex", "Capital expenditure"),
        ("change_nwc", "Change in NWC"),
        ("fcf", "Free cash flow"),
        ("",),
        ("weight", "Share of the fiscal year counted"),
        ("time", "Discounting period (years)"),
        ("factor", "Discount factor"),
        ("pv", "Discounted cash flow"),
        ("",),
        ("#", "Parameters"),
        ("wacc", "WACC"),
        ("g", "Perpetual growth"),
        ("multiple", "Exit multiple EV/EBITDA"),
        ("stub", "Fraction of the first fiscal year still to run"),
        ("end_time", "Time to the end of the plan (years)"),
        ("",),
        ("#", "Enterprise value and value per share"),
        ("method", "Terminal value method"),
        ("pv_fcf", "Sum of discounted cash flows"),
        ("tv", "Terminal value"),
        ("pv_tv", "Discounted terminal value"),
        ("ev", "Enterprise value"),
        ("tv_share", "  of which terminal value"),
        ("bridge", "Net debt and other items deducted"),
        ("equity", "Equity value"),
        ("shares", "Diluted shares (millions)"),
        ("share", "Value per share ($)"),
        ("price", "Current share price ($)"),
        ("upside", "Gap to the share price"),
        ("ev_ebitda", "Implied EV / LTM adjusted EBITDA"),
        ("implied_multiple", "Implied exit multiple"),
        ("implied_g", "Implied perpetual growth"),
    ], start=5, width=2 + n, unit_col=None)

    lbo.layout([
        ("#", "Acquisition price (deal closing at the end of the current fiscal year)"),
        ("price", "Share price ($)"),
        ("premium", "Acquisition premium"),
        ("offer_price", "Offer price per share ($)"),
        ("shares", "Diluted shares at the offer price (millions)"),
        ("equity_purchase", "Price paid for the shares"),
        ("refinanced", "Existing debt to refinance"),
        ("closing_cash", "Company cash at closing"),
        ("other", "Minorities and other adjustments"),
        ("net_debt", "Net debt taken over"),
        ("entry_ev", "Enterprise value at entry"),
        ("ltm_ebitda", "LTM adjusted EBITDA"),
        ("entry_multiple", "Entry multiple (EV / LTM EBITDA)"),
        ("ebitda_y1", "EBITDA of the current fiscal year (projected)"),
        ("entry_multiple_y1", "Entry multiple (EV / projected EBITDA)"),
        ("",),
        ("#", "Sources and uses"),
        ("head_su", "Uses"),
        ("su1", "Purchase of the shares"),
        ("su2", "Refinancing of existing debt"),
        ("su3", "Transaction fees"),
        ("su4", "Financing fees"),
        ("su5", "Minimum cash left in the company"),
        ("su_total", "Total"),
        ("su_gap", "Check: sources - uses"),
        ("",),
        ("#", "Debt schedule after the deal"),
        ("head_plan", "Fiscal year"),
        ("revenue", "Revenue"),
        ("ebitda", "EBITDA"),
        ("da", "Depreciation and amortisation"),
        ("ebit", "Operating income (EBIT)"),
        ("senior_interest", "Interest on senior debt"),
        ("sub_interest", "Cash interest on subordinated debt"),
        ("sub_pik", "Capitalised (PIK) interest on subordinated debt"),
        ("pretax", "Pre-tax income"),
        ("tax", "Income tax"),
        ("net_income", "Net income"),
        ("capex", "Capital expenditure"),
        ("change_nwc", "Change in NWC"),
        ("fcf", "Cash available to repay debt"),
        ("",),
        ("senior_begin", "Senior debt, beginning of year"),
        ("amortization", "Mandatory amortisation"),
        ("sweep", "Early repayment (cash sweep)"),
        ("senior_end", "Senior debt, end of year"),
        ("sub_end", "Subordinated debt, end of year"),
        ("cash_end", "Cash, end of year"),
        ("leverage", "Total debt / EBITDA"),
        ("coverage", "EBITDA / cash interest"),
        ("",),
        ("#", "Exit at the end of the plan"),
        ("exit_ebitda", "EBITDA of the last year"),
        ("exit_multiple", "Exit multiple (EV / EBITDA)"),
        ("exit_ev", "Enterprise value at exit"),
        ("exit_liabilities", "Net debt and other items deducted"),
        ("exit_equity", "Equity value at exit"),
        ("moic", "Multiple of invested capital (MOIC)"),
        ("irr", "IRR of the fund"),
        ("",),
        ("#", "Maximum price a fund can pay to reach its IRR"),
        ("mp_irr", "Targeted IRR"),
        ("mp_r", "Required multiple of invested capital"),
        ("mp_ratio", "Exit EBITDA / LTM EBITDA"),
        ("mp_k", "Exit items independent of the price"),
        ("mp_c0", "Sponsor equity independent of the price"),
        ("mp_equity", "Maximum price for all the shares"),
        ("mp_price", "Maximum price per share ($)"),
        ("mp_premium", "Corresponding premium over the share price"),
    ], start=4, width=2 + n, unit_col=None)

    # ------------------------------------------------------------- Assumptions
    scenario_text = "" if res.scenario == BASE else f" Scenario: {res.scenario}."
    asm.title("Assumptions", "Blue cells on a coloured fill: edit them. The rest of the workbook recalculates. "
                             "Amounts in millions of dollars." + scenario_text)
    S.header(asm.ws, 3, {"A": "Assumption", "B": "Unit", "C": "Value", "D": "Why this value is proposed"},
             left=("B", "D"))

    def note(key: str, col: str = "D") -> None:
        if key in a.notes:
            asm.write(f"{col}{asm.r(key)}", a.notes[key], "note")

    def entry(key: str, value, fmt: str) -> None:
        asm.write(asm.a(key, C), value, "assumption", fmt)
        note(key)

    g = asm.a
    entry("valuation_date", a.valuation_date, S.FMT_DATE)
    entry("price", price_value(company.ticker, a.price), S.FMT_PRICE)
    entry("shares", a.shares, S.FMT_M)
    entry("options", a.options, S.FMT_NB3)
    entry("option_strike", a.option_strike, S.FMT_PRICE)
    asm.write(g("option_shares", C),
              f"=IF({g('price', C)}>0,MAX(0,{g('options', C)}*(1-{g('option_strike', C)}/{g('price', C)})),0)",
              fmt=S.FMT_NB3)
    entry("rsus", a.rsus, S.FMT_NB3)
    entry("other_dilution", a.other_dilution, S.FMT_NB3)
    asm.write(g("diluted_shares", C),
              f"={g('shares', C)}+{g('option_shares', C)}+{g('rsus', C)}+{g('other_dilution', C)}", fmt=S.FMT_M)
    asm.write(g("market_cap", C), f"={g('price', C)}*{g('diluted_shares', C)}", fmt=S.FMT_M)
    for key in ("debt", "cash", "minorities", "other_adjustments"):
        entry(key, getattr(a, key), S.FMT_M)
    asm.write(g("net_debt", C), f"={g('debt', C)}-{g('cash', C)}", fmt=S.FMT_M)
    asm.write(g("bridge", C), f"={g('net_debt', C)}+{g('minorities', C)}+{g('other_adjustments', C)}", fmt=S.FMT_M)
    asm.write(g("enterprise_value", C), f"={g('market_cap', C)}+{g('bridge', C)}", fmt=S.FMT_M, total=True)
    base_shares = f"({asm.x('shares', C)}+{asm.x('rsus', C)}+{asm.x('other_dilution', C)})"

    S.header(asm.ws, asm.r("years"), {"A": "Fiscal year", "B": "Unit", **dict(zip(PC, years_p)),
                                      L(3 + n): "Why this value is proposed"}, left=("B", L(3 + n)))
    for key, fmt in (("revenue_growth", S.FMT_PCT), ("ebitda_margin", S.FMT_PCT), ("da_pct", S.FMT_PCT),
                     ("capex_pct", S.FMT_PCT), ("nwc_pct", S.FMT_PCT), ("distributions", S.FMT_M)):
        for col, v in zip(PC, getattr(a, key)):
            asm.write(g(key, col), v, "assumption", fmt)
        note(key, L(3 + n))
    for key in ("op_liabilities_pct", "tax_rate"):
        entry(key, getattr(a, key), S.FMT_PCT)
    for key in ("cost_of_debt", "cash_yield", "risk_free_rate", "equity_risk_premium"):
        entry(key, getattr(a, key), S.FMT_PCT2)
    entry("raw_beta", a.raw_beta, S.FMT_NB)
    entry("blume_weight", a.blume_weight, S.FMT_NB)
    asm.write(g("beta", C), f"={g('blume_weight', C)}*{g('raw_beta', C)}+(1-{g('blume_weight', C)})", fmt=S.FMT_NB)
    entry("specific_premium", a.specific_premium, S.FMT_PCT2)
    asm.write(g("cost_of_equity", C),
              f"={g('risk_free_rate', C)}+{g('beta', C)}*{g('equity_risk_premium', C)}+{g('specific_premium', C)}",
              fmt=S.FMT_PCT2)
    asm.write(f"D{asm.r('cost_of_equity')}", "CAPM: risk-free rate + beta x equity risk premium + specific premium.", "note")
    entry("debt_weight", a.debt_weight, S.FMT_PCT)
    asm.write(g("wacc", C),
              f"=(1-{g('debt_weight', C)})*{g('cost_of_equity', C)}"
              f"+{g('debt_weight', C)}*{g('cost_of_debt', C)}*(1-{g('tax_rate', C)})",
              fmt=S.FMT_PCT2, total=True)
    asm.write(f"D{asm.r('wacc')}", "Equity and after-tax debt, weighted by their share of the financing.", "note")
    entry("terminal_growth", a.terminal_growth, S.FMT_PCT2)
    entry("mid_year", a.mid_year, S.FMT_INT)
    for key, fmt in (("acquisition_premium", S.FMT_PCT), ("senior_leverage", S.FMT_X), ("senior_rate", S.FMT_PCT2),
                     ("senior_amortization", S.FMT_PCT), ("cash_sweep", S.FMT_PCT), ("sub_leverage", S.FMT_X),
                     ("sub_rate", S.FMT_PCT2), ("sub_pik_rate", S.FMT_PCT2), ("min_cash", S.FMT_M),
                     ("transaction_fees", S.FMT_PCT), ("financing_fees", S.FMT_PCT),
                     ("exit_multiple_delta", S.FMT_X), ("target_irr", S.FMT_PCT),
                     ("target_irr_high", S.FMT_PCT), ("wacc_step", S.FMT_PCT2), ("growth_step", S.FMT_PCT2),
                     ("multiple_step", S.FMT_X), ("premium_step", S.FMT_PCT), ("multiple_cap", S.FMT_X)):
        entry(key, getattr(a, key), fmt)
    S.widths(asm.ws, 54, 13, 3 + n, {"B": 18})
    asm.ws.freeze_panes = "C4"

    # ------------------------------------------------------------- Historical
    filings = "; ".join(company.filings.values())
    hi.title(f"{name}: restated published accounts",
             f"Millions of dollars. Source: SEC EDGAR, {filings}. Blue figures: published data.")
    S.header(hi.ws, 4, {"A": "", **dict(zip(HC, years_h)), HL: "Last 12 months",
                        HS: "Source (SEC XBRL tag, or how the line is computed)"}, left=(HS,))
    for col, d in zip(HC, company.fiscal_years):
        hi.write(hi.a("end", col), d, "input", S.FMT_DATE)
    hi.write(hi.a("end", HL), company.ltm_date, "input", S.FMT_DATE)
    adj = company.adjustments
    src = company.sources
    sources = {
        "revenue": src.get("revenue", ""), "gross_profit": src.get("gross_profit", ""), "ebit": src.get("ebit", ""),
        "da": src.get("da", ""), "ebitda_reported": "EBIT + D&A",
        "impairments": "Asset impairments: non-cash, non-recurring charge",
        "ebitda_adj": adj.ebitda_source or "No adjustment (adjustments file)",
        "ebitda_adjusted": "Reported EBITDA + impairments + adjustments",
        "ebit_adjusted": "Adjusted EBITDA - D&A", "interest_expense": src.get("interest_expense", ""),
        "interest_income": src.get("interest_income", ""), "pretax_income": src.get("pretax_income", ""),
        "income_tax": src.get("income_tax", ""), "net_income": src.get("net_income", ""),
        "net_income_adj": adj.net_income_source or "No adjustment (adjustments file)",
        "net_income_adjusted": "Net income + adjustments: used for the P/E", "sbc": src.get("sbc", ""),
        "cfo": src.get("cfo", ""),
        "capex": (adj.capex_source if adj.capex else src.get("capex", "")),
        "buybacks": src.get("buybacks", ""), "dividends": src.get("dividends", ""),
        "cash": src.get("cash_equivalents", "") + (" + " + src["short_term_investments"]
                                                    if "short_term_investments" in src else ""),
        "operating_current_assets": "AssetsCurrent - cash and short-term investments",
        "net_fixed_assets": " + ".join(x for x in (src.get("ppe"), src.get("intangibles")) if x),
        "goodwill": src.get("goodwill", ""),
        "other_assets": "Balancing line: published total assets - lines above (right-of-use assets, deferred tax...)",
        "operating_current_liabilities": "LiabilitiesCurrent - current portion of financial debt",
        "debt": "Long-term debt + current portion + short-term borrowings (excluding lease liabilities)",
        "other_liabilities": "Balancing line: published total - other lines (lease liabilities, provisions...)",
        "equity": "Shareholders' equity, non-controlling interests included",
        "total_assets": "Sum; equal to the Assets tag by construction",
        "total_liabilities_equity": "Sum; equal to LiabilitiesAndStockholdersEquity by construction",
    }
    for key, text in sources.items():
        hi.write(hi.a(key, HS), text, "note")

    data_lines = ("revenue", "gross_profit", "ebit", "da", "impairments", "ebitda_adj", "interest_expense",
                  "interest_income", "pretax_income", "income_tax", "net_income", "sbc", "cfo", "capex",
                  "buybacks", "dividends", "cash", "operating_current_assets", "net_fixed_assets", "goodwill",
                  "other_assets", "operating_current_liabilities", "debt", "other_liabilities", "equity")
    for key in data_lines:
        for col, v in zip(HC, company.hist[key]):
            if v is None and key in ("buybacks", "dividends"):
                v = 0.0                      # line absent from the accounts: nothing paid
            if v is not None:
                hi.write(hi.a(key, col), v, "input", S.FMT_M)
    for col, d in zip(HC, company.fiscal_years):
        hi.write(hi.a("net_income_adj", col), adj.net_income.get(d.isoformat(), 0.0), "input", S.FMT_M)
    for key in ("revenue", "gross_profit", "ebit", "da", "impairments", "ebitda_adj", "net_income", "net_income_adj"):
        if company.ltm.get(key) is not None:
            hi.write(hi.a(key, HL), company.ltm[key], "input", S.FMT_M)
    hi.write(hi.a("cash", HL), company.balance["cash"], "input", S.FMT_M)
    hi.write(hi.a("debt", HL), company.balance["debt"], "input", S.FMT_M)

    has_gross = company.hist["gross_profit"][-1] is not None
    g = hi.a
    for i, col in enumerate(HC + [HL]):
        is_ltm = col == HL
        if i > 0:
            hi.write(g("growth", col), f"={g('revenue', col)}/{g('revenue', HC[i - 1] if not is_ltm else HD)}-1", fmt=S.FMT_PCT)
        if has_gross and (not is_ltm or company.ltm.get("gross_profit") is not None):
            hi.write(g("gross_margin", col), f"={g('gross_profit', col)}/{g('revenue', col)}", fmt=S.FMT_PCT)
        hi.write(g("ebitda_reported", col), f"={g('ebit', col)}+{g('da', col)}", fmt=S.FMT_M)
        hi.write(g("ebitda_adjusted", col), f"={g('ebitda_reported', col)}+{g('impairments', col)}+{g('ebitda_adj', col)}",
                 fmt=S.FMT_M, total=True)
        hi.write(g("ebitda_margin", col), f"={g('ebitda_adjusted', col)}/{g('revenue', col)}", fmt=S.FMT_PCT)
        hi.write(g("ebit_adjusted", col), f"={g('ebitda_adjusted', col)}-{g('da', col)}", fmt=S.FMT_M)
        hi.write(g("net_income_adjusted", col), f"={g('net_income', col)}+{g('net_income_adj', col)}", fmt=S.FMT_M)
        hi.write(g("da_pct", col), f"={g('da', col)}/{g('revenue', col)}", fmt=S.FMT_PCT)
        if is_ltm:
            continue
        hi.write(g("effective_tax", col), f'=IF({g("pretax_income", col)}>0,{g("income_tax", col)}/{g("pretax_income", col)},{NM})',
                 fmt=S.FMT_PCT)
        hi.write(g("fcf", col), f"={g('cfo', col)}-{g('capex', col)}", fmt=S.FMT_M)
        hi.write(g("capex_pct", col), f"={g('capex', col)}/{g('revenue', col)}", fmt=S.FMT_PCT)
        hi.write(g("total_assets", col), f"=SUM({g('cash', col)}:{g('other_assets', col)})", fmt=S.FMT_M, total=True)
        hi.write(g("total_liabilities_equity", col),
                 f"=SUM({g('operating_current_liabilities', col)}:{g('equity', col)})", fmt=S.FMT_M, total=True)
        hi.write(g("gap", col), f"={g('total_assets', col)}-{g('total_liabilities_equity', col)}", fmt=S.FMT_M)
        hi.write(g("nwc", col), f"={g('operating_current_assets', col)}-{g('operating_current_liabilities', col)}", fmt=S.FMT_M)
        hi.write(g("nwc_pct", col), f"={g('nwc', col)}/{g('revenue', col)}", fmt=S.FMT_PCT)
        hi.write(g("op_liabilities_pct", col), f"={g('operating_current_liabilities', col)}/{g('revenue', col)}", fmt=S.FMT_PCT)
    hi.write(f"A{hi.r('op_liabilities_pct') + 2}",
             "\"Last 12 months\" column: flows = last fiscal year + current year to date - same period one year earlier; "
             f"cash and debt from the last published balance sheet ({company.balance_date.isoformat()}).", "note")
    S.widths(hi.ws, 50, 13, 3 + nh, {"B": 3, HL: 17, HS: 70})
    hi.ws.freeze_panes = "C5"

    # ------------------------------------------------------------ Projections
    pr.title(f"{name}: projection of the three financial statements",
             "Millions of dollars. Standalone company, no transaction: debt stays constant, cash absorbs the flows.")
    S.header(pr.ws, 4, {"A": "", PB: years_h[-1], **dict(zip(PC, years_p))})
    pr.write(pr.a("end", PB), f"={hi.x('end', HD)}", "link", S.FMT_DATE)
    base_links = {"revenue": "revenue", "growth": "growth", "ebitda": "ebitda_adjusted", "da": "da",
                  "ebit": "ebit_adjusted", "interest_expense": "interest_expense",
                  "interest_income": "interest_income", "pretax_income": "pretax_income",
                  "income_tax": "income_tax", "net_income": "net_income", "capex": "capex", "cash": "cash",
                  "operating_current_assets": "operating_current_assets", "net_fixed_assets": "net_fixed_assets",
                  "goodwill": "goodwill", "other_assets": "other_assets",
                  "operating_current_liabilities": "operating_current_liabilities", "debt": "debt",
                  "other_liabilities": "other_liabilities", "equity": "equity", "nwc": "nwc"}
    for key, hist_key in base_links.items():
        pr.write(pr.a(key, PB), f"={hi.x(hist_key, HD)}", "link", S.FMT_PCT if key == "growth" else S.FMT_M)
    pr.write(pr.a("margin", PB), f"={pr.a('ebitda', PB)}/{pr.a('revenue', PB)}", fmt=S.FMT_PCT)
    g = pr.a
    for i, col in enumerate(PC):
        p = PB if i == 0 else PC[i - 1]
        pr.write(g("end", col), f"=EDATE({g('end', p)},12)", fmt=S.FMT_DATE)
        pr.write(g("revenue", col), f"={g('revenue', p)}*(1+{asm.x('revenue_growth', col)})", fmt=S.FMT_M)
        pr.write(g("growth", col), f"={asm.x('revenue_growth', col)}", "link", S.FMT_PCT)
        pr.write(g("ebitda", col), f"={g('revenue', col)}*{asm.x('ebitda_margin', col)}", fmt=S.FMT_M, total=True)
        pr.write(g("margin", col), f"={g('ebitda', col)}/{g('revenue', col)}", fmt=S.FMT_PCT)
        pr.write(g("da", col), f"={g('revenue', col)}*{asm.x('da_pct', col)}", fmt=S.FMT_M)
        pr.write(g("ebit", col), f"={g('ebitda', col)}-{g('da', col)}", fmt=S.FMT_M)
        pr.write(g("interest_expense", col), f"={g('debt', p)}*{asm.x('cost_of_debt', C)}", fmt=S.FMT_M)
        pr.write(g("interest_income", col), f"={g('cash', p)}*{asm.x('cash_yield', C)}", fmt=S.FMT_M)
        pr.write(g("pretax_income", col), f"={g('ebit', col)}-{g('interest_expense', col)}+{g('interest_income', col)}", fmt=S.FMT_M)
        pr.write(g("income_tax", col), f"=MAX(0,{g('pretax_income', col)})*{asm.x('tax_rate', C)}", fmt=S.FMT_M)
        pr.write(g("net_income", col), f"={g('pretax_income', col)}-{g('income_tax', col)}", fmt=S.FMT_M, total=True)
        pr.write(g("capex", col), f"={g('revenue', col)}*{asm.x('capex_pct', col)}", fmt=S.FMT_M)
        pr.write(g("change_nwc", col), f"={g('nwc', col)}-{g('nwc', p)}", fmt=S.FMT_M)
        pr.write(g("distributions", col), f"={asm.x('distributions', col)}", "link", S.FMT_M)
        pr.write(g("change_cash", col),
                 f"={g('net_income', col)}+{g('da', col)}-{g('change_nwc', col)}-{g('capex', col)}-{g('distributions', col)}",
                 fmt=S.FMT_M, total=True)
        pr.write(g("cash", col), f"={g('cash', p)}+{g('change_cash', col)}", fmt=S.FMT_M)
        pr.write(g("operating_current_assets", col), f"={g('nwc', col)}+{g('operating_current_liabilities', col)}", fmt=S.FMT_M)
        pr.write(g("net_fixed_assets", col), f"={g('net_fixed_assets', p)}+{g('capex', col)}-{g('da', col)}", fmt=S.FMT_M)
        for constant in ("goodwill", "other_assets", "debt", "other_liabilities"):
            pr.write(g(constant, col), f"={g(constant, p)}", fmt=S.FMT_M)
        pr.write(g("operating_current_liabilities", col), f"={g('revenue', col)}*{asm.x('op_liabilities_pct', C)}", fmt=S.FMT_M)
        pr.write(g("equity", col), f"={g('equity', p)}+{g('net_income', col)}-{g('distributions', col)}", fmt=S.FMT_M)
        pr.write(g("nwc", col), f"={g('revenue', col)}*{asm.x('nwc_pct', col)}", fmt=S.FMT_M)
    for col in [PB] + PC:
        pr.write(g("total_assets", col), f"=SUM({g('cash', col)}:{g('other_assets', col)})", fmt=S.FMT_M, total=True)
        pr.write(g("total_liabilities_equity", col),
                 f"=SUM({g('operating_current_liabilities', col)}:{g('equity', col)})", fmt=S.FMT_M, total=True)
        pr.write(g("gap", col), f"={g('total_assets', col)}-{g('total_liabilities_equity', col)}", fmt=S.FMT_M)
    S.widths(pr.ws, 46, 13, 2 + n)
    pr.ws.freeze_panes = "B5"

    # -------------------------------------------------------------------- DCF
    dcf.title(f"{name}: discounted cash flow valuation (DCF)",
              "Millions of dollars. Two terminal values computed side by side.")
    S.header(dcf.ws, 4, {"A": "", "B": "", **dict(zip(PC, years_p))})
    g = dcf.a
    for key, fmt, ref in (("wacc", S.FMT_PCT2, asm.x("wacc", C)), ("g", S.FMT_PCT2, asm.x("terminal_growth", C)),
                          ("multiple", S.FMT_X, asm.x("exit_multiple", C))):
        dcf.write(g(key, C), f"={ref}", "link", fmt)
    dcf.write(g("stub", C), f"=MAX(0,MIN(1,({pr.x('end', P1)}-{asm.x('valuation_date', C)})/365))", fmt=S.FMT_NB)
    dcf.write(g("end_time", C), f"={g('stub', C)}+COUNT({g('fcf', P1)}:{g('fcf', PN)})-1", fmt=S.FMT_NB)
    for i, col in enumerate(PC):
        for key in ("ebit", "da", "capex", "change_nwc"):
            dcf.write(g(key, col), f"={pr.x(key, col).replace('$' + col, col)}", "link", S.FMT_M)
        dcf.write(g("tax_on_ebit", col), f"={g('ebit', col)}*{asm.x('tax_rate', C)}", fmt=S.FMT_M)
        dcf.write(g("nopat", col), f"={g('ebit', col)}-{g('tax_on_ebit', col)}", fmt=S.FMT_M)
        dcf.write(g("fcf", col), f"={g('nopat', col)}+{g('da', col)}-{g('capex', col)}-{g('change_nwc', col)}",
                  fmt=S.FMT_M, total=True)
        stub, mid = g("stub", C, True), asm.x("mid_year", C)
        if i == 0:
            dcf.write(g("weight", col), f"={stub}", fmt=S.FMT_NB)
            dcf.write(g("time", col), f"={stub}*(1-0.5*{mid})", fmt=S.FMT_NB)
        else:
            dcf.write(g("weight", col), "=1", fmt=S.FMT_NB)
            dcf.write(g("time", col), f"={stub}+1-0.5*{mid}" if i == 1 else f"={g('time', PC[i - 1])}+1", fmt=S.FMT_NB)
        dcf.write(g("factor", col), f"=1/(1+{g('wacc', C, True)})^{g('time', col)}", fmt=S.FMT_NB3)
        dcf.write(g("pv", col), f"={g('fcf', col)}*{g('weight', col)}*{g('factor', col)}", fmt=S.FMT_M)
    S.header(dcf.ws, dcf.r("method"), {"A": "Terminal value method", "B": "", C: "Perpetual growth",
                                       D: "Exit multiple"})
    w = g("wacc", C, True)
    for col in (C, D):
        dcf.write(g("pv_fcf", col), f"=SUM({g('pv', P1, True)}:{g('pv', PN, True)})", fmt=S.FMT_M)
        dcf.write(g("ev", col), f"={g('pv_fcf', col)}+{g('pv_tv', col)}", fmt=S.FMT_M, total=True)
        dcf.write(g("tv_share", col), f"={g('pv_tv', col)}/{g('ev', col)}", fmt=S.FMT_PCT)
        dcf.write(g("bridge", col), f"={asm.x('bridge', C)}", "link", S.FMT_M)
        dcf.write(g("equity", col), f"={g('ev', col)}-{g('bridge', col)}", fmt=S.FMT_M, total=True)
        dcf.write(g("shares", col), f"={asm.x('diluted_shares', C)}", "link", S.FMT_M)
        dcf.write(g("share", col), f"={g('equity', col)}/{g('shares', col)}", fmt=S.FMT_PRICE, bold=True)
        dcf.write(g("price", col), f"={asm.x('price', C)}", "link", S.FMT_PRICE)
        dcf.write(g("upside", col), f"={g('share', col)}/{g('price', col)}-1", fmt=S.FMT_PCT)
        dcf.write(g("ev_ebitda", col), f"={g('ev', col)}/{hi.x('ebitda_adjusted', HL)}", fmt=S.FMT_X)
    dcf.write(g("tv", C), f"={g('fcf', PN)}*(1+{g('g', C)})/({w}-{g('g', C)})", fmt=S.FMT_M)
    dcf.write(g("pv_tv", C), f"={g('tv', C)}*{g('factor', PN)}", fmt=S.FMT_M)
    dcf.write(g("tv", D), f"={pr.x('ebitda', PN)}*{g('multiple', C)}", fmt=S.FMT_M)
    dcf.write(g("pv_tv", D), f"={g('tv', D)}/(1+{w})^{g('end_time', C)}", fmt=S.FMT_M)
    dcf.write(g("implied_multiple", C), f"={g('tv', C)}/{pr.x('ebitda', PN)}", fmt=S.FMT_X)
    dcf.write(g("implied_g", D), f"=({g('tv', D)}*{w}-{g('fcf', PN)})/({g('tv', D)}+{g('fcf', PN)})", fmt=S.FMT_PCT2)
    S.widths(dcf.ws, 46, 4, 2 + n, {c: 18 for c in PC})
    dcf.ws.freeze_panes = "C5"

    # ------------------------------------------------------------------ Comps
    co.title("Trading comparables",
             "Millions of dollars, last-twelve-month (LTM) aggregates. EBITDA and EBIT before asset impairments. "
             "\"n.m.\": multiple not meaningful (negative denominator or multiple above the cap).")
    K = dict(zip(("name", "ticker", "price", "shares", "cap", "debt", "cash", "min", "ev", "revenue",
                  "ebitda", "ebit", "ni", "ev_revenue", "ev_ebitda", "ev_ebit", "pe", "date", "note"),
                 "ABCDEFGHIJKLMNOPQRS"))
    S.header(co.ws, 4, {K["name"]: "Company", K["ticker"]: "Ticker", K["price"]: "Price ($)",
                        K["shares"]: "Shares (m)", K["cap"]: "Market cap", K["debt"]: "Financial debt",
                        K["cash"]: "Cash", K["min"]: "Minorities", K["ev"]: "Enterprise value",
                        K["revenue"]: "Revenue", K["ebitda"]: "EBITDA", K["ebit"]: "EBIT", K["ni"]: "Net income",
                        K["ev_revenue"]: "EV / Revenue", K["ev_ebitda"]: "EV / EBITDA", K["ev_ebit"]: "EV / EBIT",
                        K["pe"]: "P/E", K["date"]: "LTM to", K["note"]: "Source and remarks"},
             left=(K["ticker"], K["note"]))
    peers = res.comps.peers
    first, row = 5, 5
    cap_ref = asm.x("multiple_cap", C)

    def multiples(r: int) -> None:
        ev, cap = f"{K['ev']}{r}", f"{K['cap']}{r}"
        co.write(f"{K['ev_revenue']}{r}", f'=IF({K["revenue"]}{r}>0,{ev}/{K["revenue"]}{r},{NM})', fmt=S.FMT_X)
        for key, num, den in (("ev_ebitda", ev, f"{K['ebitda']}{r}"), ("ev_ebit", ev, f"{K['ebit']}{r}"),
                              ("pe", cap, f"{K['ni']}{r}")):
            co.write(f"{K[key]}{r}", f'=IF({den}>0,IF({num}/{den}<={cap_ref},{num}/{den},{NM}),{NM})', fmt=S.FMT_X)

    for p in peers:
        c = p.company
        co.rows[f"peer_{c.ticker}"] = row
        co.write(f"{K['name']}{row}", c.name.title())
        co.write(f"{K['ticker']}{row}", c.ticker)
        co.write(f"{K['price']}{row}", price_value(c.ticker, p.quote.price), "input", S.FMT_PRICE)
        for key, v, fmt in (("shares", c.shares, S.FMT_M), ("debt", c.balance["debt"], S.FMT_M),
                            ("cash", c.balance["cash"], S.FMT_M), ("min", c.balance["minorities"], S.FMT_M),
                            ("revenue", c.ltm["revenue"], S.FMT_M), ("ebitda", c.ltm["ebitda_adjusted"], S.FMT_M),
                            ("ebit", c.ltm["ebit_adjusted"], S.FMT_M), ("ni", c.ltm["net_income_adjusted"], S.FMT_M)):
            co.write(f"{K[key]}{row}", v, "input", fmt)
        co.write(f"{K['cap']}{row}", f"={K['price']}{row}*{K['shares']}{row}", fmt=S.FMT_M)
        co.write(f"{K['ev']}{row}", f"={K['cap']}{row}+{K['debt']}{row}-{K['cash']}{row}+{K['min']}{row}", fmt=S.FMT_M)
        multiples(row)
        co.write(f"{K['date']}{row}", c.ltm_date, "input", S.FMT_DATE)
        remarks = [f"{p.quote.source}; {c.filings.get('quarterly') or c.filings.get('annual', '')}"]
        remarks += [w.replace(f"{c.ticker}: ", "") for w in c.warnings]
        co.write(f"{K['note']}{row}", " | ".join(remarks), "note")
        row += 1
    last = row - 1
    row += 1
    for key, label, formula in (("max", "Maximum", "MAX({p})"), ("q3", "3rd quartile", "QUARTILE({p},3)"),
                                ("median", "Median", "MEDIAN({p})"), ("q1", "1st quartile", "QUARTILE({p},1)"),
                                ("min", "Minimum", "MIN({p})")):
        co.rows[key] = row
        co.write(f"A{row}", label, bold=(key == "median"))
        for m in ("ev_revenue", "ev_ebitda", "ev_ebit", "pe"):
            rng = f"{K[m]}{first}:{K[m]}{last}" if peers else f"{K[m]}{first}"
            co.write(f"{K[m]}{row}", f'=IF(COUNT({rng})=0,{NM},{formula.format(p=rng)})', fmt=S.FMT_X,
                     bold=(key == "median"))
        row += 1
    industry = res.comps.industry
    if industry is not None:
        co.rows["sector"] = row
        co.write(f"A{row}", f"Sector reference: {industry.name}", "note")
        for key, v in (("ev_ebitda", industry.ev_ebitda), ("ev_ebit", industry.ev_ebit)):
            if v is not None:
                co.write(f"{K[key]}{row}", v, "input", S.FMT_X)
        co.write(f"{K['note']}{row}", f"{industry.source}. Firms with positive EBITDA. For comparison only: "
                                      "not used in the statistics above.", "note")
        row += 1
    row += 1
    co.rows["target"] = row
    co.write(f"{K['name']}{row}", f"{name} (target)", bold=True)
    co.write(f"{K['ticker']}{row}", company.ticker, bold=True)
    for key, ref, fmt in (("price", asm.x("price", C), S.FMT_PRICE), ("shares", asm.x("diluted_shares", C), S.FMT_M),
                          ("cap", asm.x("market_cap", C), S.FMT_M), ("debt", asm.x("debt", C), S.FMT_M),
                          ("cash", asm.x("cash", C), S.FMT_M), ("min", asm.x("minorities", C), S.FMT_M),
                          ("ev", asm.x("enterprise_value", C), S.FMT_M), ("revenue", hi.x("revenue", HL), S.FMT_M),
                          ("ebitda", hi.x("ebitda_adjusted", HL), S.FMT_M), ("ebit", hi.x("ebit_adjusted", HL), S.FMT_M),
                          ("ni", hi.x("net_income_adjusted", HL), S.FMT_M), ("date", hi.x("end", HL), S.FMT_DATE)):
        co.write(f"{K[key]}{row}", f"={ref}", "link", fmt)
    multiples(row)
    co.write(f"{K['note']}{row}", "Adjusted aggregates of the Historical sheet (Last 12 months column).", "note")
    row += 2
    S.band(co.ws, row, "Value of the target when the multiples of the comparables are applied to it", 12)
    row += 1
    S.header(co.ws, row, {"A": "Multiple applied", "B": "", "C": "LTM aggregate", "D": "1st quartile",
                          "E": "Median", "F": "3rd quartile", "G": "EV (1st q.)", "H": "EV (median)",
                          "I": "EV (3rd q.)", "J": "$/share (1st q.)", "K": "$/share (median)",
                          "L": "$/share (3rd q.)"})
    row += 1
    rt = co.rows["target"]
    for key, label, aggregate in (("ev_ebitda", "EV / EBITDA", f"{K['ebitda']}{rt}"),
                                  ("ev_ebit", "EV / EBIT", f"{K['ebit']}{rt}"), ("pe", "P/E", f"{K['ni']}{rt}")):
        co.rows[f"imp_{key}"] = row
        co.write(f"A{row}", label)
        co.write(f"C{row}", f"={aggregate}", fmt=S.FMT_M)
        for q, cm, cv, cs in (("q1", "D", "G", "J"), ("median", "E", "H", "K"), ("q3", "F", "I", "L")):
            co.write(f"{cm}{row}", f"={K[key]}{co.rows[q]}", fmt=S.FMT_X)
            if key == "pe":
                co.write(f"{cs}{row}", f'=IFERROR({cm}{row}*$C{row}/{asm.x("diluted_shares", C)},{NM})', fmt=S.FMT_PRICE)
            else:
                co.write(f"{cv}{row}", f'=IFERROR({cm}{row}*$C{row},{NM})', fmt=S.FMT_M)
                co.write(f"{cs}{row}",
                         f'=IFERROR(({cv}{row}-{asm.x("bridge", C)})/{asm.x("diluted_shares", C)},{NM})', fmt=S.FMT_PRICE)
        row += 1
    S.widths(co.ws, 34, 13, 18, {"B": 9, "S": 90})
    co.ws.freeze_panes = "C5"

    if res.comps.stats["ev_ebitda"]["median"] is not None and "exit_multiple" not in res.overrides:
        asm.write(asm.a("exit_multiple", C), f"={co.x('median', K['ev_ebitda'])}", "link", S.FMT_X)
        S.fill_assumption(asm.ws[asm.a("exit_multiple", C)])
        note("exit_multiple")
    else:
        entry("exit_multiple", a.exit_multiple, S.FMT_X)

    # -------------------------------------------------------------------- LBO
    PL = PC[1:]                     # fiscal years of the plan, after closing
    L1, LN = PL[0], PL[-1]
    E, G = "E", "G"                 # sources table, to the right of the uses
    lbo.title(f"{name}: leveraged buyout (LBO)",
              "Millions of dollars. Deal closing at the end of the current fiscal year, sale at the end of the plan.")
    g = lbo.a
    for key, ref, fmt in (("price", asm.x("price", C), S.FMT_PRICE), ("premium", asm.x("acquisition_premium", C), S.FMT_PCT),
                          ("refinanced", pr.x("debt", P1), S.FMT_M), ("closing_cash", pr.x("cash", P1), S.FMT_M),
                          ("ltm_ebitda", hi.x("ebitda_adjusted", HL), S.FMT_M), ("ebitda_y1", pr.x("ebitda", P1), S.FMT_M)):
        lbo.write(g(key, C), f"={ref}", "link", fmt)
    lbo.write(g("other", C), f"={asm.x('minorities', C)}+{asm.x('other_adjustments', C)}", "link", S.FMT_M)
    lbo.write(g("offer_price", C), f"={g('price', C)}*(1+{g('premium', C)})", fmt=S.FMT_PRICE)
    lbo.write(g("shares", C),
              f"={base_shares}+MAX(0,{asm.x('options', C)}*(1-{asm.x('option_strike', C)}/{g('offer_price', C)}))",
              fmt=S.FMT_M)
    lbo.write(g("equity_purchase", C), f"={g('offer_price', C)}*{g('shares', C)}", fmt=S.FMT_M)
    lbo.write(g("net_debt", C), f"={g('refinanced', C)}-{g('closing_cash', C)}+{g('other', C)}", fmt=S.FMT_M)
    lbo.write(g("entry_ev", C), f"={g('equity_purchase', C)}+{g('net_debt', C)}", fmt=S.FMT_M, total=True)
    lbo.write(g("entry_multiple", C), f"={g('entry_ev', C)}/{g('ltm_ebitda', C)}", fmt=S.FMT_X, bold=True)
    lbo.write(g("entry_multiple_y1", C), f"={g('entry_ev', C)}/{g('ebitda_y1', C)}", fmt=S.FMT_X)

    S.header(lbo.ws, lbo.r("head_su"), {"A": "Uses", C: "$m", E: "Sources", "F": "", G: "$m"}, left=(E,))
    lbo.write(g("su1", C), f"={g('equity_purchase', C)}", fmt=S.FMT_M)
    lbo.write(g("su2", C), f"={g('refinanced', C)}", fmt=S.FMT_M)
    lbo.write(g("su3", C), f"={asm.x('transaction_fees', C)}*{g('entry_ev', C)}", fmt=S.FMT_M)
    lbo.write(g("su4", C), f"={asm.x('financing_fees', C)}*({g('su1', G)}+{g('su2', G)})", fmt=S.FMT_M)
    lbo.write(g("su5", C), f"={asm.x('min_cash', C)}", "link", S.FMT_M)
    lbo.write(g("su_total", C), f"=SUM({g('su1', C)}:{g('su5', C)})", fmt=S.FMT_M, total=True)
    for key, label in (("su1", "Senior debt"), ("su2", "Subordinated debt"), ("su3", "Company cash"),
                       ("su4", "Equity from the fund"), ("su5", "  share of equity in the financing"),
                       ("su_total", "Total")):
        lbo.write(g(key, E), label)
    lbo.write(g("su1", G), f"={asm.x('senior_leverage', C)}*{g('ltm_ebitda', C)}", fmt=S.FMT_M)
    lbo.write(g("su2", G), f"={asm.x('sub_leverage', C)}*{g('ltm_ebitda', C)}", fmt=S.FMT_M)
    lbo.write(g("su3", G), f"={g('closing_cash', C)}", fmt=S.FMT_M)
    lbo.write(g("su4", G), f"={g('su_total', C)}-{g('su1', G)}-{g('su2', G)}-{g('su3', G)}", fmt=S.FMT_M, bold=True)
    lbo.write(g("su5", G), f"={g('su4', G)}/{g('su_total', G)}", fmt=S.FMT_PCT)
    lbo.write(g("su_total", G), f"=SUM({g('su1', G)}:{g('su4', G)})", fmt=S.FMT_M, total=True)
    lbo.write(g("su_gap", C), f"={g('su_total', G)}-{g('su_total', C)}", fmt=S.FMT_M)
    senior0, sub0, sponsor = g("su1", G, True), g("su2", G, True), g("su4", G, True)

    S.header(lbo.ws, lbo.r("head_plan"), {"A": "Fiscal year", "B": "", P1: "Closing", **dict(zip(PL, years_p[1:]))})
    for i, col in enumerate(PL):
        p = P1 if i == 0 else PL[i - 1]
        for key in ("revenue", "ebitda", "da", "ebit", "capex", "change_nwc"):
            lbo.write(g(key, col), f"={pr.x(key, col).replace('$' + col, col)}", "link", S.FMT_M)
        lbo.write(g("senior_begin", col), f"={g('senior_end', p)}", fmt=S.FMT_M)
        lbo.write(g("senior_interest", col), f"={g('senior_begin', col)}*{asm.x('senior_rate', C)}", fmt=S.FMT_M)
        lbo.write(g("sub_interest", col), f"={g('sub_end', p)}*{asm.x('sub_rate', C)}", fmt=S.FMT_M)
        lbo.write(g("sub_pik", col), f"={g('sub_end', p)}*{asm.x('sub_pik_rate', C)}", fmt=S.FMT_M)
        lbo.write(g("pretax", col),
                  f"={g('ebit', col)}-{g('senior_interest', col)}-{g('sub_interest', col)}-{g('sub_pik', col)}", fmt=S.FMT_M)
        lbo.write(g("tax", col), f"=MAX(0,{g('pretax', col)})*{asm.x('tax_rate', C)}", fmt=S.FMT_M)
        lbo.write(g("net_income", col), f"={g('pretax', col)}-{g('tax', col)}", fmt=S.FMT_M)
        lbo.write(g("fcf", col),
                  f"={g('net_income', col)}+{g('sub_pik', col)}+{g('da', col)}-{g('capex', col)}-{g('change_nwc', col)}",
                  fmt=S.FMT_M, total=True)
        lbo.write(g("amortization", col), f"=MIN({g('senior_begin', col)},{senior0}*{asm.x('senior_amortization', C)})", fmt=S.FMT_M)
        lbo.write(g("sweep", col),
                  f"=MAX(0,MIN({g('senior_begin', col)}-{g('amortization', col)},"
                  f"({g('fcf', col)}-{g('amortization', col)})*{asm.x('cash_sweep', C)}))", fmt=S.FMT_M)
        lbo.write(g("senior_end", col), f"={g('senior_begin', col)}-{g('amortization', col)}-{g('sweep', col)}",
                  fmt=S.FMT_M, total=True)
        lbo.write(g("sub_end", col), f"={g('sub_end', p)}+{g('sub_pik', col)}", fmt=S.FMT_M)
        lbo.write(g("cash_end", col), f"={g('cash_end', p)}+{g('fcf', col)}-{g('amortization', col)}-{g('sweep', col)}",
                  fmt=S.FMT_M)
        lbo.write(g("leverage", col), f"=({g('senior_end', col)}+{g('sub_end', col)})/{g('ebitda', col)}", fmt=S.FMT_X)
        interest = f"({g('senior_interest', col)}+{g('sub_interest', col)})"
        lbo.write(g("coverage", col), f"=IF({interest}>0,{g('ebitda', col)}/{interest},{NM})", fmt=S.FMT_X)
    lbo.write(g("senior_end", P1), f"={senior0}", fmt=S.FMT_M, total=True)
    lbo.write(g("sub_end", P1), f"={sub0}", fmt=S.FMT_M)
    lbo.write(g("cash_end", P1), f"={g('su5', C)}", fmt=S.FMT_M)
    lbo.write(g("leverage", P1), f"=({g('senior_end', P1)}+{g('sub_end', P1)})/{g('ltm_ebitda', C)}", fmt=S.FMT_X)

    duration = f"COUNT({g('fcf', L1, True)}:{g('fcf', LN, True)})"
    lbo.write(g("exit_ebitda", C), f"={g('ebitda', LN)}", fmt=S.FMT_M)
    lbo.write(g("exit_multiple", C), f"={g('entry_multiple', C)}+{asm.x('exit_multiple_delta', C)}", fmt=S.FMT_X)
    lbo.write(g("exit_ev", C), f"={g('exit_ebitda', C)}*{g('exit_multiple', C)}", fmt=S.FMT_M)
    lbo.write(g("exit_liabilities", C),
              f"={g('senior_end', LN)}+{g('sub_end', LN)}-{g('cash_end', LN)}+{g('other', C)}", fmt=S.FMT_M)
    lbo.write(g("exit_equity", C), f"={g('exit_ev', C)}-{g('exit_liabilities', C)}", fmt=S.FMT_M, total=True)
    lbo.write(g("moic", C), f"={g('exit_equity', C)}/{sponsor}", fmt=S.FMT_X2, bold=True)
    lbo.write(g("irr", C), f"=IF({g('moic', C)}>0,{g('moic', C)}^(1/{duration})-1,{NM})", fmt=S.FMT_PCT, bold=True)

    options, strike = asm.x("options", C), asm.x("option_strike", C)
    for col, irr_key in ((C, "target_irr"), (D, "target_irr_high")):
        lbo.write(g("mp_irr", col), f"={asm.x(irr_key, C)}", "link", S.FMT_PCT)
        lbo.write(g("mp_r", col), f"=(1+{g('mp_irr', col)})^{duration}", fmt=S.FMT_X2)
        lbo.write(g("mp_ratio", col), f"={g('exit_ebitda', C, True)}/{g('ltm_ebitda', C, True)}", fmt=S.FMT_NB)
        lbo.write(g("mp_k", col),
                  f"={g('exit_ebitda', C, True)}*{asm.x('exit_multiple_delta', C)}-{g('exit_liabilities', C, True)}",
                  fmt=S.FMT_M)
        lbo.write(g("mp_c0", col),
                  f"={g('su2', C, True)}+{asm.x('transaction_fees', C)}*{g('net_debt', C, True)}"
                  f"+{g('su4', C, True)}+{g('su5', C, True)}-{senior0}-{sub0}-{g('su3', G, True)}", fmt=S.FMT_M)
        lbo.write(g("mp_equity", col),
                  f"=({g('mp_r', col)}*{g('mp_c0', col)}-{g('mp_ratio', col)}*{g('net_debt', C, True)}-{g('mp_k', col)})"
                  f"/({g('mp_ratio', col)}-{g('mp_r', col)}*(1+{asm.x('transaction_fees', C)}))", fmt=S.FMT_M)
        eq = g("mp_equity", col)
        lbo.write(g("mp_price", col),
                  f"=IF(AND({options}>0,{eq}/{base_shares}>{strike}),"
                  f"({eq}+{options}*{strike})/({base_shares}+{options}),{eq}/{base_shares})",
                  fmt=S.FMT_PRICE, bold=True)
        lbo.write(g("mp_premium", col), f"={g('mp_price', col)}/{g('price', C, True)}-1", fmt=S.FMT_PCT)
    lbo.write(f"A{lbo.r('mp_premium') + 2}",
              "Debt only depends on EBITDA: the fund's cheque and the sale value both move in a straight line with the "
              "amount paid, which gives the maximum price by an exact formula, with no trial and error.", "note")
    S.widths(lbo.ws, 50, 4, 2 + n, {**{c: 15 for c in PC}, "E": 15, "F": 15, "G": 15})

    # ----------------------------------------------------------- Sensitivities
    se.title("Sensitivity tables",
             "Each cell redoes the computation with two assumptions moved. The central cell is the base case.")
    VAL = ["C", "D", "E", "F", "G"]
    fcf_r, weight_r, time_r = dcf.xr("fcf", P1, PN), dcf.xr("weight", P1, PN), dcf.xr("time", P1, PN)
    bridge, shares = asm.x("bridge", C), asm.x("diluted_shares", C)

    def table(key: str, start: int, title: str, corner: str) -> int:
        se.rows[key] = start + 1
        S.band(se.ws, start, title, 7)
        se.write(f"B{start + 1}", corner, "note")
        return start + 1

    def headers(top: int, base_col: str, step_col: str | None, base_row: str, step_row: str,
                fmt_col: str, fmt_row: str) -> None:
        for k, col in zip(STEPS, VAL):
            if step_col is not None:
                se.write(f"{col}{top}", f"={base_col}{k:+d}*{step_col}", fmt=fmt_col, bold=True)
            se.write(f"B{top + 3 + k}", f"={base_row}{k:+d}*{step_row}", fmt=fmt_row, bold=True, center=True)

    t = table("t1", 4, "Value per share ($), DCF with perpetual growth", "WACC \\ perpetual growth")
    headers(t, asm.x("terminal_growth", C), asm.x("growth_step", C), asm.x("wacc", C), asm.x("wacc_step", C),
            S.FMT_PCT2, S.FMT_PCT2)
    for i in range(1, 6):
        for col in VAL:
            se.write(f"{col}{t + i}",
                     f"=(SUMPRODUCT({fcf_r}*{weight_r}/(1+$B{t + i})^{time_r})"
                     f"+{dcf.x('fcf', PN)}*(1+{col}${t})/($B{t + i}-{col}${t})/(1+$B{t + i})^{dcf.x('time', PN)}"
                     f"-{bridge})/{shares}", fmt=S.FMT_PRICE)

    t = table("t2", 12, "Value per share ($), DCF with exit multiple", "WACC \\ exit multiple")
    headers(t, asm.x("exit_multiple", C), asm.x("multiple_step", C), asm.x("wacc", C), asm.x("wacc_step", C),
            S.FMT_X, S.FMT_PCT2)
    for i in range(1, 6):
        for col in VAL:
            se.write(f"{col}{t + i}",
                     f"=(SUMPRODUCT({fcf_r}*{weight_r}/(1+$B{t + i})^{time_r})"
                     f"+{pr.x('ebitda', PN)}*{col}${t}/(1+$B{t + i})^{dcf.x('end_time', C)}"
                     f"-{bridge})/{shares}", fmt=S.FMT_PRICE)

    t = table("t3", 20, "IRR of the fund by exit multiple and exit year", "Exit multiple \\ exit year")
    headers(t, "", None, lbo.x("exit_multiple", C), asm.x("multiple_step", C), S.FMT_INT, S.FMT_X)
    plan = lambda key: lbo.xr(key, L1, LN)     # noqa: E731
    for year, col in zip(res.sens.exit_years, VAL):
        se.write(f"{col}{t}", year, "input", S.FMT_INT, bold=True)
        for i in range(1, 6):
            se.write(f"{col}{t + i}",
                     f'=IFERROR(((INDEX({plan("ebitda")},{col}${t})*$B{t + i}-INDEX({plan("senior_end")},{col}${t})'
                     f'-INDEX({plan("sub_end")},{col}${t})+INDEX({plan("cash_end")},{col}${t})-{lbo.x("other", C)})'
                     f'/{lbo.x("su4", G)})^(1/{col}${t})-1,{NM})', fmt=S.FMT_PCT)

    t = table("t4", 28, "IRR of the fund by premium paid and exit multiple", "Acquisition premium \\ exit multiple")
    headers(t, lbo.x("exit_multiple", C), asm.x("multiple_step", C), asm.x("acquisition_premium", C),
            asm.x("premium_step", C), S.FMT_X, S.FMT_PCT)
    duration_x = f"COUNT({lbo.xr('fcf', L1, LN)})"
    for i in range(1, 6):
        offer = f"({asm.x('price', C)}*(1+$B{t + i}))"
        purchase = f"{offer}*({base_shares}+MAX(0,{options}*(1-{strike}/{offer})))"
        for col in VAL:
            se.write(f"{col}{t + i}",
                     f'=IFERROR((({lbo.x("exit_ebitda", C)}*{col}${t}-{lbo.x("exit_liabilities", C)})'
                     f'/((1+{asm.x("transaction_fees", C)})*{purchase}+{lbo.x("mp_c0", C)}))'
                     f'^(1/{duration_x})-1,{NM})', fmt=S.FMT_PCT)
    S.widths(se.ws, 4, 14, 7, {"B": 36})

    # ---------------------------------------------------------------- Summary
    sm.title(f"{name} ({company.ticker}): M&A / LBO valuation",
             f"Model generated by Talanton {__version__} on {generated_on.isoformat()}. Millions of dollars, except per-share "
             "values. Educational document: neither investment advice nor a recommendation." + scenario_text)
    r = sm.layout([
        ("#", "Market"),
        ("price", "Share price ($)"),
        ("cap", "Market capitalisation"),
        ("net_debt", "Net financial debt"),
        ("ev", "Enterprise value"),
        ("ev_ebitda", "EV / LTM adjusted EBITDA"),
        ("",),
        ("#", "Value per share by method ($)"),
        ("head_ff", "Method"),
    ], start=4, width=6, unit_col=None)
    for key, ref, fmt in (("price", asm.x("price", C), S.FMT_PRICE), ("cap", asm.x("market_cap", C), S.FMT_M),
                          ("net_debt", asm.x("net_debt", C), S.FMT_M), ("ev", asm.x("enterprise_value", C), S.FMT_M)):
        sm.write(sm.a(key, "B"), f"={ref}", "link", fmt)
    sm.write(sm.a("ev_ebitda", "B"), f"={sm.a('ev', 'B')}/{hi.x('ebitda_adjusted', HL)}", fmt=S.FMT_X)
    S.header(sm.ws, sm.r("head_ff"), {"A": "Method", "B": "Low", "C": "High", "D": "Range", "E": "Midpoint",
                                      "F": "Gap to price"})
    r1, r2 = se.r("t1"), se.r("t2")
    core = lambda t: f"'{SENSITIVITIES}'!$D${t + 2}:$F${t + 4}"     # noqa: E731
    ff_rows = [
        ("Comps: EV / EBITDA (1st to 3rd quartile)", f"={co.x('imp_ev_ebitda', 'J')}", f"={co.x('imp_ev_ebitda', 'L')}"),
        ("Comps: EV / EBIT (1st to 3rd quartile)", f"={co.x('imp_ev_ebit', 'J')}", f"={co.x('imp_ev_ebit', 'L')}"),
        ("Comps: P/E (1st to 3rd quartile)", f"={co.x('imp_pe', 'J')}", f"={co.x('imp_pe', 'L')}"),
        ("DCF: perpetual growth (WACC and growth one step either way)", f"=MIN({core(r1)})", f"=MAX({core(r1)})"),
        ("DCF: exit multiple (WACC and multiple one step either way)", f"=MIN({core(r2)})", f"=MAX({core(r2)})"),
        ("LBO: maximum price for a fund (demanding IRR, then target IRR)", f"={lbo.x('mp_price', D)}", f"={lbo.x('mp_price', C)}"),
        ("Current share price", f"={asm.x('price', C)}", f"={asm.x('price', C)}"),
    ]
    ff_first = r
    for label, low, high in ff_rows:
        sm.write(f"A{r}", label)
        sm.write(f"B{r}", low, "link", S.FMT_PRICE)
        sm.write(f"C{r}", high, "link", S.FMT_PRICE)
        sm.write(f"D{r}", f"=IFERROR(MAX(C{r}-B{r},{asm.x('price', C)}*0.01),0)", fmt=S.FMT_PRICE)
        sm.write(f"E{r}", f'=IFERROR((B{r}+C{r})/2,{NM})', fmt=S.FMT_PRICE)
        sm.write(f"F{r}", f'=IFERROR(E{r}/{asm.x("price", C)}-1,{NM})', fmt=S.FMT_PCT)
        r += 1
    ff_last = r - 1
    sm.write(f"A{r}", "Range: width of the bar on the chart (at least 1% of the share price, to stay visible).", "note")
    r = sm.layout([
        ("",),
        ("#", "LBO: what a fund earns at the offer price"),
        ("lbo_premium", "Acquisition premium"),
        ("lbo_price", "Offer price per share ($)"),
        ("lbo_multiple", "Entry multiple (EV / LTM EBITDA)"),
        ("lbo_leverage", "Acquisition debt / LTM EBITDA"),
        ("lbo_equity", "Share of equity in the financing"),
        ("lbo_moic", "Multiple of invested capital (MOIC)"),
        ("lbo_irr", "IRR of the fund"),
        ("",),
        ("#", "Reliability of the model"),
        ("status", "Consistency checks"),
        ("warnings", "Warnings to review"),
        ("python", "Reconciliation with the Python engine"),
        ("",),
        ("#", "Data sources"),
    ], start=r + 1, width=6, unit_col=None)
    for key, ref, fmt in (("lbo_premium", lbo.x("premium", C), S.FMT_PCT), ("lbo_price", lbo.x("offer_price", C), S.FMT_PRICE),
                          ("lbo_multiple", lbo.x("entry_multiple", C), S.FMT_X), ("lbo_leverage", lbo.x("leverage", P1), S.FMT_X),
                          ("lbo_equity", lbo.x("su5", G), S.FMT_PCT), ("lbo_moic", lbo.x("moic", C), S.FMT_X2),
                          ("lbo_irr", lbo.x("irr", C), S.FMT_PCT)):
        sm.write(sm.a(key, "B"), f"={ref}", "link", fmt)
    for line in res.sources:
        sm.write(f"A{r}", line, "note")
        r += 1
    if live:
        sm.write(f"A{r}", "Share prices are live Bloomberg formulas (BDP): they refresh on a computer with a Terminal, "
                          "and show the values of the generation date elsewhere.", "note")

    chart = BarChart()
    chart.type, chart.grouping, chart.overlap = "bar", "stacked", 100
    chart.title = "Value per share by method ($)"
    chart.add_data(Reference(sm.ws, min_col=2, min_row=ff_first, max_row=ff_last), titles_from_data=False)
    chart.add_data(Reference(sm.ws, min_col=4, min_row=ff_first, max_row=ff_last), titles_from_data=False)
    chart.set_categories(Reference(sm.ws, min_col=1, min_row=ff_first, max_row=ff_last))
    chart.series[0].graphicalProperties.noFill = True
    chart.series[0].graphicalProperties.line.noFill = True
    chart.series[1].graphicalProperties.solidFill = theme.accent
    chart.legend = None
    chart.y_axis.number_format = "0"
    chart.y_axis.majorGridlines = None
    chart.x_axis.scaling.orientation = "maxMin"     # first method at the top
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.height, chart.width = 9.5, 24
    sm.ws.add_chart(chart, "H4")
    S.widths(sm.ws, 66, 14, 6, {"F": 17})

    # ----------------------------------------------------------------- Checks
    ck.title("Checks", "ERROR: the model is inconsistent, do not use it. WARNING: point of judgment to review. "
                       "OK: nothing to report.")
    S.header(ck.ws, 3, {"A": "Check", "B": "Value", "C": "Threshold", "D": "Status", "E": "How to read it"}, left=("E",))
    r = 4

    def check(label: str, formula: str, threshold, test: str, level: str, reading: str, fmt: str) -> None:
        nonlocal r
        ck.write(f"A{r}", label)
        ck.write(f"B{r}", formula, fmt=fmt)
        ck.write(f"C{r}", threshold, "input", fmt)
        ck.write(f"D{r}", f'=IF(B{r}{test}C{r},"OK","{level}")', bold=True, center=True)
        ck.write(f"E{r}", reading, "note")
        r += 1

    S.band(ck.ws, r, "Consistency of the model", 5)
    r += 1
    first_status = r
    check("Historical balance sheets balance (sum of gaps)",
          f"=SUMPRODUCT(ABS({hi.xr('gap', HC[0], HD)}))", 0.5, "<", "ERROR",
          "Assets = liabilities and equity for each published fiscal year.", S.FMT_NB)
    check("Projected balance sheets balance (sum of gaps)",
          f"=SUMPRODUCT(ABS({pr.xr('gap', PB, PN)}))", 0.5, "<", "ERROR",
          "The projected balance sheet must balance whatever the assumptions.", S.FMT_NB)
    check("LBO: sources = uses (gap)", f"=ABS({lbo.x('su_gap', C)})", 0.5, "<", "ERROR",
          "The financing must exactly cover the price and the fees.", S.FMT_NB)
    check("WACC above perpetual growth (spread)",
          f"={asm.x('wacc', C)}-{asm.x('terminal_growth', C)}", 0.005, ">", "ERROR",
          "Otherwise the terminal value is meaningless.", S.FMT_PCT2)
    check("LBO: positive equity from the fund", f"={lbo.x('su4', G)}", 0, ">", "ERROR",
          "A negative cheque means debt exceeds the price paid.", S.FMT_M)
    S.band(ck.ws, r, "Points of judgment", 5)
    r += 1
    check("Weight of the terminal value, DCF with perpetual growth", f"={dcf.x('tv_share', C)}", 0.8, "<", "WARNING",
          "Above 80%, the value rests almost entirely on long-term assumptions.", S.FMT_PCT)
    check("Weight of the terminal value, DCF with exit multiple", f"={dcf.x('tv_share', D)}", 0.8, "<", "WARNING",
          "Same reading.", S.FMT_PCT)
    check("Number of comparables with a meaningful EV / EBITDA",
          f"=COUNT('{co.name}'!${K['ev_ebitda']}${first}:${K['ev_ebitda']}${max(last, first)})", 4, ">=", "WARNING",
          "Below four, the median is fragile.", S.FMT_INT)
    check("Lowest projected cash (standalone)", f"=MIN({pr.xr('cash', P1, PN)})", 0, ">=", "WARNING",
          "Negative cash implies a financing that is not modelled.", S.FMT_M)
    check("LBO: lowest cash after the deal", f"=MIN({lbo.xr('cash_end', P1, LN)})", 0, ">=", "WARNING",
          "Negative cash means the debt is not sustainable.", S.FMT_M)
    check("LBO: total debt / EBITDA at closing", f"={lbo.x('leverage', P1)}", 6.5, "<=", "WARNING",
          "Above 6 to 7 times EBITDA, the financing becomes hard to raise.", S.FMT_X)
    check("LBO: weakest interest coverage (EBITDA / cash interest)",
          f"=IF(COUNT({lbo.xr('coverage', L1, LN)})=0,99,MIN({lbo.xr('coverage', L1, LN)}))", 2, ">=",
          "WARNING", "Below 2, the company struggles to pay its interest. 99: no cash interest.", S.FMT_X)
    S.band(ck.ws, r, "Data warnings (raised when the model was generated)", 5)
    r += 1
    warnings = list(company.warnings)
    for p in peers:
        warnings += p.company.warnings
    beta_note = a.notes.get("raw_beta", "")
    if "low R²" in beta_note or "beta of 1 by default" in beta_note:
        warnings.append("Beta: " + beta_note)
    for w in warnings:
        subject = w.split(": ")[0] if ": " in w[:40] else "Data"
        ck.write(f"A{r}", f"To check: {subject}")
        ck.write(f"D{r}", "WARNING", bold=True, center=True)
        ck.write(f"E{r}", w, "note")
        r += 1
    if not warnings:
        ck.write(f"A{r}", "No warning.", "note")
        r += 1
    last_status = r - 1
    statuses = f"$D${first_status}:$D${last_status}"
    r += 1
    ck.rows["status"] = r
    ck.write(f"A{r}", "Overall status", bold=True)
    ck.write(f"B{r}", f'=IF(COUNTIF({statuses},"ERROR")>0,"ERROR",'
                      f'IF(COUNTIF({statuses},"WARNING")>0,"Consistent, with warnings","Consistent"))', bold=True)
    r += 1
    ck.rows["warnings"] = r
    ck.write(f"A{r}", "Number of warnings")
    ck.write(f"B{r}", f'=COUNTIF({statuses},"WARNING")', fmt=S.FMT_INT)
    r += 2

    S.band(ck.ws, r, "Python / Excel reconciliation (the Python engine computed these figures without Excel)", 5)
    r += 1
    S.header(ck.ws, r, {"A": "Key figure", "B": "Excel formula", "C": "Python engine", "D": "Gap", "E": "Status"},
             left=("E",))
    r += 1
    places = {
        "proj.revenue_end": ("Revenue, last projected year", pr, "revenue", PN, S.FMT_M),
        "proj.ebitda_end": ("EBITDA, last projected year", pr, "ebitda", PN, S.FMT_M),
        "proj.net_income_end": ("Net income, last projected year", pr, "net_income", PN, S.FMT_M),
        "proj.cash_end": ("Cash, last projected year", pr, "cash", PN, S.FMT_M),
        "proj.total_assets_end": ("Total assets, last projected year", pr, "total_assets", PN, S.FMT_M),
        "market.diluted_shares": ("Diluted shares", asm, "diluted_shares", C, "0.0000"),
        "dcf.wacc": ("WACC", asm, "wacc", C, "0.0000%"),
        "dcf.fcf_end": ("Free cash flow, last year", dcf, "fcf", PN, S.FMT_M),
        "dcf.ev_gordon": ("Enterprise value, DCF with perpetual growth", dcf, "ev", C, S.FMT_M),
        "dcf.ev_multiple": ("Enterprise value, DCF with exit multiple", dcf, "ev", D, S.FMT_M),
        "dcf.share_gordon": ("Value per share, DCF with perpetual growth", dcf, "share", C, S.FMT_PRICE),
        "dcf.share_multiple": ("Value per share, DCF with exit multiple", dcf, "share", D, S.FMT_PRICE),
        "comps.median_ev_ebitda": ("Median EV / EBITDA of the comparables", co, "median", K["ev_ebitda"], S.FMT_NB3),
        "comps.share_median_ev_ebitda": ("Value per share at the median EV / EBITDA", co, "imp_ev_ebitda", "K", S.FMT_PRICE),
        "lbo.equity_purchase": ("LBO: price paid for the shares", lbo, "equity_purchase", C, S.FMT_M),
        "lbo.entry_ev": ("LBO: enterprise value at entry", lbo, "entry_ev", C, S.FMT_M),
        "lbo.sponsor_equity": ("LBO: equity from the fund", lbo, "su4", G, S.FMT_M),
        "lbo.debt_end": ("LBO: total debt at the end of the plan", None, None, None, S.FMT_M),
        "lbo.exit_equity": ("LBO: equity value at exit", lbo, "exit_equity", C, S.FMT_M),
        "lbo.moic": ("LBO: multiple of invested capital", lbo, "moic", C, "0.0000"),
        "lbo.irr": ("LBO: IRR", lbo, "irr", C, "0.0000%"),
        "lbo.max_price_target": ("LBO: maximum price per share, target IRR", lbo, "mp_price", C, S.FMT_PRICE),
        "lbo.max_price_high": ("LBO: maximum price per share, demanding IRR", lbo, "mp_price", D, S.FMT_PRICE),
    }
    points = res.checkpoints()
    first_py = r
    for key, value in points.items():
        label, sheet, line, col, fmt = places[key]
        ck.write(f"A{r}", label)
        if sheet is None:                               # total debt: computed here, from two lines of the LBO sheet
            registry[key] = (CHECKS, f"B{r}")
            ck.write(f"B{r}", f"={lbo.x('senior_end', LN)}+{lbo.x('sub_end', LN)}", "link", fmt)
        else:
            registry[key] = (sheet.name, f"{col}{sheet.r(line)}")
            ck.write(f"B{r}", f"={sheet.x(line, col)}", "link", fmt)
        ck.write(f"C{r}", value, "input", fmt)
        ck.write(f"D{r}", f'=IFERROR(B{r}-C{r},1)', fmt="0.000000")
        ck.write(f"E{r}", f'=IF(ABS(D{r})<=0.000001*MAX(1,ABS(C{r})),"Identical","Changed")', center=True)
        r += 1
    ck.rows["python"] = r + 1
    ck.write(f"A{r + 1}", "Overall reconciliation", bold=True)
    ck.write(f"B{r + 1}", f'=IF(COUNTIF($E${first_py}:$E${r - 1},"Changed")=0,"Excel = Python on {len(points)} key figures",'
                          f'"Assumptions changed since generation")', bold=True)
    ck.write(f"A{r + 3}", "\"Changed\" is normal as soon as a blue cell has been edited: the Python column keeps the values "
                          "of the generation date. Run Talanton again to redo the reconciliation.", "note")
    S.widths(ck.ws, 62, 16, 4, {"E": 90})
    registry["checks.status"] = (CHECKS, f"B{ck.r('status')}")
    registry["checks.python"] = (CHECKS, f"B{ck.r('python')}")

    sm.write(sm.a("status", "B"), f"={ck.x('status', 'B')}", "link")
    sm.write(sm.a("warnings", "B"), f"={ck.x('warnings', 'B')}", "link", S.FMT_INT)
    sm.write(sm.a("python", "B"), f"={ck.x('python', 'B')}", "link")

    for sheet in sheets.values():
        sheet.ws.page_setup.orientation = "landscape"
        sheet.ws.page_setup.fitToWidth = 1
        sheet.ws.page_setup.fitToHeight = 0
        sheet.ws.sheet_properties.pageSetUpPr.fitToPage = True
    wb.calculation.fullCalcOnLoad = True
    wb.properties.title = f"{name}: Talanton valuation model"
    wb.properties.creator = f"Talanton {__version__}"
    return wb, registry
