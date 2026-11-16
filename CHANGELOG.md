# Changelog

## 0.2.0 (November 2026)

- Whole project in English: code, workbook, messages, documentation.
- Data: FRED (risk-free rate, SOFR, credit spreads, breakeven inflation), Damodaran sector betas and
  multiples, SEC industry codes and peer suggestions, a chain of price providers (Yahoo Finance,
  Alpha Vantage, Finnhub) with API keys in a `.env` file, experimental Bloomberg Terminal provider.
- Model: sector beta when the regression is unreliable, treasury stock method for options, two-tranche
  LBO (senior + subordinated with PIK), 6 to 10 projected years, optional lease liabilities.
- Customisation: one TOML config (overrides, settings, theme, scenarios with relative moves),
  four workbook themes, optional live Bloomberg formulas in Excel.
- New analyses: scenarios side by side, Monte Carlo on the DCF, merger accretion / dilution.
- Interactive app (Streamlit + Plotly). Commands: `peers`, `merger`, `sources`, `industries`, `app`.
- 76 tests; continuous integration with GitHub Actions.

## 0.1.0 (November 2026)

- First prototype, in French: SEC EDGAR accounts, three-statement projection, DCF, comparables,
  single-tranche LBO, Excel workbook with formulas, Python / Excel reconciliation.
