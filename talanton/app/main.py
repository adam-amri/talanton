"""Interactive interface. Run it with `talanton app` (or `streamlit run talanton/app/main.py`).

Every control feeds the same Python engine as the command line: moving a slider
recomputes the projections, the DCF, the comparables and the LBO, and the Excel
workbook you download carries the assumptions you set here.
"""

from __future__ import annotations

import io
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:                      # allows `streamlit run` without installing the package
    sys.path.insert(0, str(ROOT))

from talanton import __version__, config                                        # noqa: E402
from talanton.app import charts                                                   # noqa: E402
from talanton.checks import verify                                                # noqa: E402
from talanton.data import DataError, EdgarClient, load_industries, suggest_peers   # noqa: E402
from talanton.engine import BASE, collect, compute, compute_scenarios             # noqa: E402
from talanton.excel import build_workbook                                         # noqa: E402
from talanton.excel.styles import THEMES                                          # noqa: E402
from talanton.model import ModelConfig, Settings, load_config                     # noqa: E402
from talanton.restatement import RestatementError                                 # noqa: E402
from talanton.valuation import MergerTerms, compute_merger, simulate              # noqa: E402
from talanton.valuation.comps import LABELS, MULTIPLES                            # noqa: E402

EXAMPLES = ROOT / "examples"
EXAMPLE_TICKER, EXAMPLE_PEERS = "MAT", "HAS, FNKO, JAKK, YETI, GOLF"
DEFAULT_SCENARIOS = {
    "bull": {"revenue_growth": {"shift": 0.01}, "ebitda_margin": {"shift": 0.01}},
    "bear": {"revenue_growth": {"shift": -0.01}, "ebitda_margin": {"shift": -0.01}},
}

st.set_page_config(page_title="Talanton", page_icon=":material/balance:", layout="wide")
st.markdown("""
<style>
  .block-container {padding-top: 2.2rem; max-width: 1400px;}
  [data-testid="stMetric"] {border: 1px solid rgba(128,128,128,0.25); border-radius: 10px; padding: 0.7rem 0.9rem;}
  [data-testid="stMetricLabel"] p {font-size: 0.8rem; opacity: 0.75;}
  [data-testid="stMetricValue"] {font-size: 1.45rem;}
  h1 {letter-spacing: -0.02em;}
  .talanton-sub {opacity: 0.7; margin-top: -0.6rem; margin-bottom: 1rem;}
</style>""", unsafe_allow_html=True)
config.load_env(ROOT / ".env")


@st.cache_resource(show_spinner="Collecting accounts and market data...")
def load(ticker: str, peers: tuple[str, ...], cache: str, offline: bool, adjustments: str | None,
         history_years: int, industry: str | None):
    settings = Settings(history_years=history_years, industry=industry)
    return collect(ticker, list(peers), Path(cache), offline, Path(adjustments) if adjustments else None,
                   settings, log=lambda *a: None)


def money(v: float) -> str:
    return f"${v:,.0f}m"


def table(rows: dict[str, list], columns: list[str], fmt: str = "{:,.1f}") -> pd.DataFrame:
    frame = pd.DataFrame(rows, index=columns).T
    return frame.map(lambda v: "" if v is None else (fmt.format(v) if isinstance(v, (int, float)) else v))


# ------------------------------------------------------------------ sidebar: data
with st.sidebar:
    st.title("Talanton")
    st.caption(f"M&A / LBO valuation engine, version {__version__}")
    has_example = (EXAMPLES / "cache").exists()
    modes = (["Example (recorded data)"] if has_example else []) + ["Live data"]
    mode = st.radio("Data", modes, horizontal=True, help="The example replays Mattel on data recorded on "
                    "9 November 2026, with no network. Live data downloads from the SEC, FRED and Yahoo Finance.")
    offline = mode.startswith("Example")
    if offline:
        ticker, peers_text = EXAMPLE_TICKER, EXAMPLE_PEERS
        st.text_input("Ticker", ticker, disabled=True)
        st.text_input("Comparables", peers_text, disabled=True)
        cache = str(EXAMPLES / "cache")
    else:
        ticker = st.text_input("Ticker", EXAMPLE_TICKER, help="US-listed company filing 10-K / 10-Q reports").strip().upper()
        peers_text = st.text_input("Comparables", EXAMPLE_PEERS, help="Tickers separated by commas")
        cache = str(Path.cwd() / "data_cache")
        if not config.get(config.CONTACT):
            contact = st.text_input("Your name and e-mail (required by the SEC)", placeholder="First Last first.last@example.com")
            if contact:
                import os
                os.environ[config.CONTACT] = contact
        if st.button("Suggest comparables", width="stretch"):
            try:
                found, notes = suggest_peers(EdgarClient(Path(cache)), ticker, 15)
                st.session_state["suggestions"] = (ticker, found, notes)
            except DataError as exc:
                st.error(str(exc))
        if st.session_state.get("suggestions", (None,))[0] == ticker:
            _, found, notes = st.session_state["suggestions"]
            st.dataframe(pd.DataFrame([(s.ticker, s.name, s.reason) for s in found], columns=["Ticker", "Company", "Why"]),
                         hide_index=True, height=220)
            st.caption("Suggestions from the SEC industry code. Micro-caps included: choose the peers yourself.")
    peers = tuple(t.strip().upper() for t in peers_text.split(",") if t.strip())
    adjustments = next((str(p) for p in (EXAMPLES / "adjustments" / f"{ticker}.toml", Path.cwd() / "adjustments" / f"{ticker}.toml")
                        if p.exists()), None)
    config_file = st.file_uploader("Config file (optional)", type="toml", help="Assumption overrides, settings and scenarios")

    with st.expander("Model settings"):
        years = st.slider("Projected years", 6, 10, 6, help="The LBO holding period is this number minus one")
        beta_method = st.selectbox("Beta", ["auto", "regression", "sector"],
                                   help="auto: the sector beta replaces a regression beta with a low R²")
        industries = ["(from the SEC industry code)"] + list(load_industries())
        industry = st.selectbox("Sector reference", industries)
        industry = None if industry.startswith("(") else industry
        include_leases = st.toggle("Add lease liabilities to net debt", False)
        theme_name = st.selectbox("Workbook colours", list(THEMES))

try:
    file_config = ModelConfig()
    if config_file is not None:
        tmp = Path(st.session_state.setdefault("tmp_config", str(Path(cache) / "_uploaded_config.toml")))
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(config_file.getvalue())
        file_config = load_config(tmp)
    inputs = load(ticker, peers, cache, offline, adjustments, 5, industry)
except (DataError, RestatementError, ValueError) as exc:
    st.error(f"{exc}")
    st.stop()

settings = Settings(years=years, beta_method=beta_method, industry=industry, include_leases=include_leases,
                    theme=theme_name, theme_overrides=file_config.settings.theme_overrides)
model = ModelConfig(overrides=file_config.overrides, settings=settings,
                    scenarios=file_config.scenarios or DEFAULT_SCENARIOS, origin=file_config.origin)

# ------------------------------------------------------------- sidebar: assumptions
with st.sidebar:
    scenario = st.selectbox("Scenario", [BASE, *model.scenarios])
    start = compute(inputs, model, scenario)            # the scenario before any live change
    d = start.a
    key = f"{ticker}|{scenario}|{years}|{beta_method}|{industry}"
    live: dict = {}

    def pct(label: str, name: str, low: float, high: float, step: float = 0.25, help: str | None = None) -> None:
        default = round(getattr(d, name) * 100, 2)
        v = st.slider(label, low, high, float(min(max(default, low), high)), step, format="%.2f%%", key=f"{name}|{key}", help=help)
        if abs(v - default) > 1e-9:
            live[name] = v / 100

    def num(label: str, name: str, low: float, high: float, step: float, fmt: str = "%.1f", help: str | None = None) -> None:
        default = round(float(getattr(d, name)), 2)
        v = st.slider(label, low, high, float(min(max(default, low), high)), step, format=fmt, key=f"{name}|{key}", help=help)
        if abs(v - default) > 1e-9:
            live[name] = v

    st.subheader("Assumptions")
    with st.expander("Operations", expanded=True):
        dg = st.slider("Revenue growth, every year", -5.0, 5.0, 0.0, 0.25, format="%+.2f pts", key=f"dg|{key}",
                       help="Moves the whole growth path up or down")
        dm = st.slider("EBITDA margin, every year", -5.0, 5.0, 0.0, 0.25, format="%+.2f pts", key=f"dm|{key}")
        if dg:
            live["revenue_growth"] = [g + dg / 100 for g in d.revenue_growth]
        if dm:
            live["ebitda_margin"] = [m + dm / 100 for m in d.ebitda_margin]
        pct("Tax rate", "tax_rate", 10.0, 40.0, 0.5)
    with st.expander("Cost of capital"):
        pct("Risk-free rate", "risk_free_rate", 0.0, 8.0, 0.05)
        pct("Equity risk premium", "equity_risk_premium", 2.0, 9.0, 0.05)
        num("Raw beta", "raw_beta", 0.2, 2.5, 0.01, "%.2f", help=d.notes.get("raw_beta"))
        pct("Company-specific premium", "specific_premium", 0.0, 5.0)
        pct("Perpetual growth", "terminal_growth", 0.0, 4.0)
        num("Exit multiple (DCF)", "exit_multiple", 3.0, 25.0, 0.1, "%.1fx")
    with st.expander("LBO"):
        pct("Acquisition premium", "acquisition_premium", 0.0, 80.0, 1.0)
        num("Senior debt (x EBITDA)", "senior_leverage", 0.0, 8.0, 0.25, "%.2fx")
        pct("Senior interest rate", "senior_rate", 3.0, 14.0)
        pct("Cash sweep", "cash_sweep", 0.0, 100.0, 5.0)
        num("Subordinated debt (x EBITDA)", "sub_leverage", 0.0, 3.0, 0.25, "%.2fx")
        pct("Subordinated cash rate", "sub_rate", 5.0, 16.0)
        pct("Subordinated PIK rate", "sub_pik_rate", 0.0, 10.0)
        num("Exit multiple minus entry multiple", "exit_multiple_delta", -3.0, 3.0, 0.25, "%+.2fx")
        pct("Target IRR", "target_irr", 10.0, 30.0, 0.5)
    if live:
        st.caption(f"{len(live)} assumption(s) changed from the scenario defaults.")

try:
    res = compute(inputs, model, scenario, live)
    issues = verify(res)
except (ValueError, ZeroDivisionError) as exc:
    st.error(f"These assumptions cannot be computed: {exc}")
    st.stop()
a, c, lbo, dcf = res.a, res.target, res.lbo, res.dcf

# --------------------------------------------------------------------- header
st.title(f"{c.short_name} ({c.ticker})")
st.markdown(f"<p class='talanton-sub'>Accounts to {c.balance_date.isoformat()}, share price of {inputs.quote.date.isoformat()}. "
            f"Scenario: <b>{scenario}</b>. Amounts in millions of dollars. Educational tool, not investment advice.</p>",
            unsafe_allow_html=True)
errors = [m for level, m in issues if level == "ERROR"]
for m in errors:
    st.error(m)

k = st.columns(6)
k[0].metric("Share price", f"${a.price:.2f}")
k[1].metric("Enterprise value", money(a.enterprise_value), f"{a.enterprise_value / c.ltm['ebitda_adjusted']:.1f}x EBITDA", delta_color="off", delta_arrow="off")
k[2].metric("DCF, perpetual growth", f"${dcf.share_gordon:.2f}", f"{dcf.share_gordon / a.price - 1:+.0%} vs price")
k[3].metric("Comps, median EV/EBITDA", "n.m." if res.comps.implied["ev_ebitda"]["median"] is None
            else f"${res.comps.implied['ev_ebitda']['median']:.2f}",
            None if res.comps.implied["ev_ebitda"]["median"] is None
            else f"{res.comps.implied['ev_ebitda']['median'] / a.price - 1:+.0%} vs price")
k[4].metric(f"LBO IRR at {a.acquisition_premium:.0%} premium", "n.m." if lbo.irr != lbo.irr else f"{lbo.irr:.1%}",
            f"{lbo.moic:.2f}x MOIC", delta_color="off", delta_arrow="off")
k[5].metric(f"Max price for {a.target_irr:.0%} IRR", f"${lbo.max_price[a.target_irr]:.2f}",
            f"{lbo.max_price[a.target_irr] / a.price - 1:+.0%} vs price")

tabs = st.tabs(["Overview", "Financials", "DCF", "Comps", "LBO", "Scenarios", "Monte Carlo", "Merger",
                "Data and checks", "Export"])

# ------------------------------------------------------------------- overview
with tabs[0]:
    left, right = st.columns([3, 2])
    left.plotly_chart(charts.football_field(res), width="stretch")
    with right:
        st.markdown("**Reading the chart**")
        st.markdown(
            f"- Each bar is a range of value per share from one method; the dotted line is the share price.\n"
            f"- Comparables: first to third quartile of the peers' multiples, applied to {c.ticker}.\n"
            f"- DCF: WACC of **{a.wacc:.2%}** (beta {a.beta:.2f}), moved one step either way.\n"
            f"- LBO: the price a fund can pay to earn {a.target_irr_high:.0%} to {a.target_irr:.0%} a year.")
        st.dataframe(pd.DataFrame(
            [(label, low, high, (low + high) / 2 / a.price - 1) for label, low, high in res.football[:-1]
             if low is not None and high is not None], columns=["Method", "Low", "High", "vs price"]),
            hide_index=True, column_config={
                "Low": st.column_config.NumberColumn(format="$%.2f"), "High": st.column_config.NumberColumn(format="$%.2f"),
                "vs price": st.column_config.NumberColumn(format="percent")})
    st.plotly_chart(charts.revenue_and_ebitda(res), width="stretch")

# ----------------------------------------------------------------- financials
with tabs[1]:
    st.plotly_chart(charts.margins(res), width="stretch")
    years_h = [f"{x.year}A" for x in c.fiscal_years]
    lines = {"Revenue": "revenue", "Gross profit": "gross_profit", "Reported EBIT": "ebit", "D&A": "da",
             "Impairments added back": "impairments", "Analyst adjustments": "ebitda_adj",
             "Adjusted EBITDA": "ebitda_adjusted", "Net income": "net_income", "Cash flow from operations": "cfo",
             "Capex": "capex", "Cash": "cash", "Financial debt": "debt", "Net working capital": "nwc",
             "Shareholders' equity": "equity"}
    hist = {label: c.hist[key] + [c.ltm.get(key) if key not in ("cash", "debt") else c.balance[key]]
            for label, key in lines.items()}
    st.markdown("**Published accounts, restated**")
    st.dataframe(table(hist, years_h + ["LTM"]), width="stretch")
    years_p = [f"{x.year}E" for x in res.proj.ends]
    p = res.proj
    st.markdown("**Projection** (standalone: debt constant, cash absorbs the flows)")
    st.dataframe(table({"Revenue": p.revenue, "EBITDA": p.ebitda, "EBIT": p.ebit, "Net income": p.net_income,
                        "Capex": p.capex, "Change in NWC": p.change_nwc, "Cash": p.cash, "Equity": p.equity,
                        "Total assets": p.total_assets}, years_p), width="stretch")
    if c.adjustments.ebitda_source or c.adjustments.capex_source:
        st.caption("Analyst adjustments: " + " | ".join(x for x in (c.adjustments.capex_source, c.adjustments.ebitda_source) if x))

# ------------------------------------------------------------------------ DCF
with tabs[2]:
    m = st.columns(5)
    m[0].metric("WACC", f"{a.wacc:.2%}")
    m[1].metric("Cost of equity", f"{a.cost_of_equity:.2%}", f"beta {a.beta:.2f}", delta_color="off", delta_arrow="off")
    m[2].metric("Value, perpetual growth", f"${dcf.share_gordon:.2f}")
    m[3].metric("Value, exit multiple", f"${dcf.share_multiple:.2f}")
    m[4].metric("Terminal value weight", f"{dcf.tv_share_gordon:.0%}",
                "high" if dcf.tv_share_gordon >= 0.8 else "reasonable", delta_color="inverse" if dcf.tv_share_gordon >= 0.8 else "off", delta_arrow="off")
    method = st.radio("Terminal value", ["Perpetual growth", "Exit multiple"], horizontal=True)
    left, right = st.columns(2)
    left.plotly_chart(charts.free_cash_flows(res), width="stretch")
    right.plotly_chart(charts.value_bridge(res, "gordon" if method.startswith("Perp") else "multiple"), width="stretch")
    s = res.sens
    left, right = st.columns(2)
    left.plotly_chart(charts.heatmap(s.dcf_gordon, [f"{w:.2%}" for w in s.wacc], [f"{g:.2%}" for g in s.growth],
                                     "Value per share ($): WACC and perpetual growth", "Perpetual growth", "WACC", ".2f"),
                      width="stretch")
    right.plotly_chart(charts.heatmap(s.dcf_multiple, [f"{w:.2%}" for w in s.wacc], [f"{x:.1f}x" for x in s.dcf_multiples],
                                      "Value per share ($): WACC and exit multiple", "Exit multiple", "WACC", ".2f"),
                       width="stretch")
    with st.expander("Why these values: the justification of each cost-of-capital input"):
        for name in ("risk_free_rate", "equity_risk_premium", "raw_beta", "blume_weight", "debt_weight", "terminal_growth", "exit_multiple"):
            st.markdown(f"- **{name.replace('_', ' ')}** = {getattr(a, name):.4g}. {a.notes.get(name, '')}")

# ---------------------------------------------------------------------- comps
with tabs[3]:
    if not res.comps.peers:
        st.info("No comparable loaded. Enter tickers in the sidebar.")
    else:
        choice = st.radio("Multiple", list(MULTIPLES), format_func=LABELS.get, horizontal=True, index=1)
        st.plotly_chart(charts.comps_multiples(res, choice), width="stretch")
        rows = []
        for peer in res.comps.peers:
            rows.append([peer.company.ticker, peer.company.name.title(), peer.quote.price, peer.market_cap, peer.enterprise_value,
                         peer.company.ltm["revenue"], peer.company.ltm["ebitda_adjusted"]]
                        + [peer.multiple(x, res.comps.cap) for x in MULTIPLES])
        frame = pd.DataFrame(rows, columns=["Ticker", "Company", "Price", "Market cap", "EV", "Revenue", "EBITDA"]
                             + [LABELS[x] for x in MULTIPLES])
        st.dataframe(frame, hide_index=True, width="stretch", column_config={
            **{x: st.column_config.NumberColumn(format="%.1f") for x in ("Market cap", "EV", "Revenue", "EBITDA")},
            **{LABELS[x]: st.column_config.NumberColumn(format="%.1fx") for x in MULTIPLES},
            "Price": st.column_config.NumberColumn(format="$%.2f")})
        st.caption("Empty multiple: not meaningful (negative denominator, or above the cap of "
                   f"{res.comps.cap:.0f}x). LTM aggregates, EBITDA before impairments.")
        stats = pd.DataFrame({LABELS[x]: res.comps.stats[x] for x in MULTIPLES}).loc[["max", "q3", "median", "q1", "min"]]
        implied = pd.DataFrame({LABELS[x]: res.comps.implied[x] for x in ("ev_ebitda", "ev_ebit", "pe")})
        left, right = st.columns(2)
        left.markdown("**Statistics of the multiples**")
        left.dataframe(stats.map(lambda v: "n.m." if v is None or v != v else f"{v:.1f}x"), width="stretch")
        right.markdown(f"**Implied value of {c.ticker} per share**")
        right.dataframe(implied.map(lambda v: "n.m." if v is None or v != v else f"${v:.2f}"), width="stretch")

# ------------------------------------------------------------------------ LBO
with tabs[4]:
    m = st.columns(6)
    m[0].metric("Offer price", f"${lbo.offer_price:.2f}", f"{a.acquisition_premium:.0%} premium", delta_color="off", delta_arrow="off")
    m[1].metric("Entry multiple", f"{lbo.entry_multiple:.1f}x")
    m[2].metric("Debt / EBITDA", f"{lbo.new_debt / c.ltm['ebitda_adjusted']:.1f}x")
    m[3].metric("Sponsor equity", money(lbo.sponsor_equity), f"{lbo.sponsor_equity / lbo.total_uses:.0%} of the financing", delta_color="off", delta_arrow="off")
    m[4].metric("IRR", "n.m." if lbo.irr != lbo.irr else f"{lbo.irr:.1%}", f"{lbo.irr - a.target_irr:+.1%} vs target" if lbo.irr == lbo.irr else None)
    m[5].metric("MOIC", f"{lbo.moic:.2f}x")
    left, right = st.columns(2)
    left.plotly_chart(charts.sources_and_uses(res), width="stretch")
    right.plotly_chart(charts.debt_paydown(res), width="stretch")
    s = res.sens
    left, right = st.columns(2)
    left.plotly_chart(charts.heatmap(s.lbo_premium, [f"{x:.0%}" for x in s.premiums], [f"{x:.1f}x" for x in s.lbo_multiples],
                                     "IRR: premium paid and exit multiple", "Exit multiple", "Premium", ".1%"), width="stretch")
    right.plotly_chart(charts.heatmap(s.lbo_exit, [f"{x:.1f}x" for x in s.lbo_multiples], [f"Year {y}" for y in s.exit_years],
                                      "IRR: exit multiple and exit year", "Exit year", "Exit multiple", ".1%"), width="stretch")
    years_l = [f"{x.year}E" for x in res.proj.ends[1:]]
    st.markdown("**Debt schedule**")
    st.dataframe(table({"EBITDA": res.proj.ebitda[1:], "Senior interest": lbo.senior_interest,
                        "Subordinated cash interest": lbo.sub_interest, "PIK interest": lbo.sub_pik,
                        "Net income": lbo.net_income, "Cash available for debt": lbo.fcf,
                        "Mandatory amortisation": lbo.amortization, "Cash sweep": lbo.sweep,
                        "Senior debt, end": lbo.senior_end, "Subordinated debt, end": lbo.sub_end,
                        "Cash, end": lbo.cash_end}, years_l), width="stretch")
    st.caption(f"Maximum price for a {a.target_irr:.0%} IRR: ${lbo.max_price[a.target_irr]:.2f} per share; for "
               f"{a.target_irr_high:.0%}: ${lbo.max_price[a.target_irr_high]:.2f}. Exact formula, no trial and error.")

# ------------------------------------------------------------------ scenarios
with tabs[5]:
    every = compute_scenarios(inputs, model, None)
    if live:
        every = {**every, f"{scenario} + your changes": res}
    st.plotly_chart(charts.scenarios(every), width="stretch")
    st.dataframe(pd.DataFrame({name: {
        "Revenue, last year": f"{r.proj.revenue[-1]:,.0f}", "EBITDA margin, last year": f"{r.a.ebitda_margin[-1]:.1%}",
        "WACC": f"{r.a.wacc:.2%}", "DCF, perpetual growth": f"${r.dcf.share_gordon:.2f}",
        "DCF, exit multiple": f"${r.dcf.share_multiple:.2f}", "LBO IRR": f"{r.lbo.irr:.1%}", "LBO MOIC": f"{r.lbo.moic:.2f}x",
        "Maximum LBO price": f"${r.lbo.max_price[r.a.target_irr]:.2f}", "Changed assumptions": ", ".join(r.overrides) or "none",
    } for name, r in every.items()}), width="stretch")
    if not file_config.scenarios:
        st.caption("Built-in scenarios: bull and bear move growth and margin by one point every year. "
                   "Define your own in a config file ([scenarios.name] tables).")

# ---------------------------------------------------------------- Monte Carlo
with tabs[6]:
    st.markdown("A distribution of DCF values instead of a single figure. The standard deviations state how uncertain "
                "you think each assumption is: they are your inputs, not estimates.")
    m = st.columns(5)
    draws = m[0].select_slider("Draws", [500, 1000, 2000, 5000], 2000)
    sd_g = m[1].slider("Growth, std dev (pts)", 0.0, 3.0, 1.0, 0.25)
    sd_m = m[2].slider("Margin, std dev (pts)", 0.0, 3.0, 1.0, 0.25)
    sd_w = m[3].slider("WACC, std dev (pts)", 0.0, 2.0, 0.5, 0.25)
    sd_t = m[4].slider("Perpetual growth, std dev (pts)", 0.0, 1.0, 0.25, 0.05)
    try:
        mc = simulate(c, a, draws, 7, sd_g / 100, sd_m / 100, sd_w / 100, sd_t / 100)
        m = st.columns(5)
        m[0].metric("Median", f"${mc.median:.2f}")
        m[1].metric("5th percentile", f"${mc.p5:.2f}")
        m[2].metric("95th percentile", f"${mc.p95:.2f}")
        m[3].metric("Draws above the share price", f"{mc.prob_above_price:.0%}")
        m[4].metric("Base case", f"${mc.base_case:.2f}")
        st.plotly_chart(charts.monte_carlo(mc, a.price), width="stretch")
        if mc.discarded:
            st.caption(f"{mc.discarded} draw(s) discarded: WACC too close to perpetual growth.")
    except ValueError as exc:
        st.warning(str(exc))

# --------------------------------------------------------------------- merger
with tabs[7]:
    if not inputs.peers:
        st.info("Load at least one comparable: it plays the acquirer.")
    else:
        st.markdown(f"Would buying **{c.ticker}** raise or lower the acquirer's earnings per share? First-pass analysis on "
                    "last-twelve-month earnings: no purchase price allocation, no integration costs.")
        m = st.columns(5)
        acquirer = m[0].selectbox("Acquirer", [p.company.ticker for p in inputs.peers])
        premium = m[1].slider("Premium", 0, 80, 30, format="%d%%") / 100
        stock = m[2].slider("Paid in stock", 0, 100, 50, 5, format="%d%%") / 100
        synergies = m[3].number_input("Synergies, pre-tax ($m)", 0.0, 5000.0, 100.0, 25.0)
        debt_rate = m[4].slider("Cost of new debt", 3.0, 12.0, 6.5, 0.25, format="%.2f%%") / 100
        buyer = next(p for p in inputs.peers if p.company.ticker == acquirer)
        if (buyer.company.ltm["net_income_adjusted"] or 0) <= 0:
            st.warning(f"{acquirer} has no positive LTM earnings: accretion is not meaningful.")
        else:
            terms = MergerTerms(premium, stock, synergies, debt_rate, a.tax_rate)
            mg = compute_merger(buyer, c, a, terms)
            m = st.columns(5)
            m[0].metric("Price for the shares", money(mg.equity_purchase), f"${mg.offer_price:.2f} per share", delta_color="off", delta_arrow="off")
            m[1].metric("EPS, standalone to pro forma", f"${mg.pro_forma_eps:.2f}", f"{mg.accretion:+.1%}")
            m[2].metric("Break-even synergies", money(mg.breakeven_synergies))
            m[3].metric("New shares issued", f"{mg.new_shares:.1f}m", f"{mg.target_ownership:.0%} of the combined company", delta_color="off", delta_arrow="off")
            m[4].metric("Pro forma net debt / EBITDA", f"{mg.pro_forma_leverage:.1f}x")
            points = [(x / 10, compute_merger(buyer, c, a, MergerTerms(premium, x / 10, synergies, debt_rate, a.tax_rate)).accretion)
                      for x in range(11)]
            st.plotly_chart(charts.accretion(points), width="stretch")

# ------------------------------------------------------------ data and checks
with tabs[8]:
    left, right = st.columns(2)
    with left:
        st.markdown("**Where the data comes from**")
        for line in res.sources:
            st.markdown(f"- {line}")
        if inputs.profile:
            st.markdown(f"- Industry: SIC {inputs.profile.sic}, {inputs.profile.sic_description}")
        st.markdown("**API keys**")
        st.dataframe(pd.DataFrame([(v.name, "set" if ok else ("missing" if v.required else "not set"), v.purpose)
                                   for v, ok in config.status()], columns=["Variable", "Status", "Used for"]), hide_index=True)
    with right:
        st.markdown("**Checks**")
        if not issues:
            st.success("No anomaly.")
        for level, message in issues:
            (st.error if level == "ERROR" else st.warning)(message)
        for note in inputs.notes:
            st.info(note)
    with st.expander("Every assumption, with its justification"):
        rows = [(name, getattr(a, name), a.notes.get(name, "")) for name in a.notes if hasattr(a, name)]
        st.dataframe(pd.DataFrame([(n, ", ".join(f"{x:.4g}" for x in v) if isinstance(v, list) else str(v), why)
                                   for n, v, why in rows], columns=["Assumption", "Value", "Why"]), hide_index=True, width="stretch")

# --------------------------------------------------------------------- export
with tabs[9]:
    st.markdown("The workbook carries the assumptions set here. Every figure in it is a formula: change a blue cell in "
                "Excel and the model recalculates. The Checks sheet reconciles Excel with the Python engine.")
    bloomberg = st.toggle("Write live Bloomberg formulas for share prices (needs a Terminal to refresh)", False)
    export = compute(inputs, ModelConfig(model.overrides, Settings(**{**settings.__dict__, "bloomberg_formulas": bloomberg}),
                                         model.scenarios, model.origin), scenario, live)
    wb, _ = build_workbook(export, date.today())
    buffer = io.BytesIO()
    wb.save(buffer)
    suffix = "" if scenario == BASE else f"_{scenario}"
    st.download_button("Download the Excel model", buffer.getvalue(), f"{c.ticker}_model{suffix}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    if live:
        lines = "\n".join(f"{name} = {value!r}" for name, value in live.items())
        st.markdown("**Your changes as a config file** (save it and pass it with `--config`)")
        st.code(lines, language="toml")
