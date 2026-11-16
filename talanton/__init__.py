"""Talanton: from a ticker to an M&A / LBO valuation model in Excel.

Pipeline:
    data         -> published accounts (SEC EDGAR), prices, rates, sector references
    restatement  -> bank-format financial statements, LTM, analyst adjustments
    model        -> default assumptions, scenarios, three-statement projection
    valuation    -> DCF, trading comparables, LBO, sensitivities, Monte Carlo, merger
    excel        -> workbook with live formulas
    checks       -> consistency checks and Python / Excel reconciliation
    app          -> interactive interface (Streamlit)
"""

__version__ = "0.2.0"
