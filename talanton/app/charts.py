"""Charts of the interactive app (Plotly). Pure functions: a result in, a figure out.

Colour does one job per chart: blue is the measure, orange and aqua tell series
apart, grey is context (history, reference lines). No dual axes.
"""

from __future__ import annotations

import plotly.graph_objects as go

from ..engine import Result
from ..valuation import MonteCarlo
from ..valuation.comps import LABELS

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GREY, LIGHT_BLUE = "#9a9a94", "#a9c8ee"
SEQUENTIAL = [[0.0, "#e8f0fa"], [0.5, "#7fb0e6"], [1.0, "#1f5fae"]]
RDBU = [[0.0, "#eb6834"], [0.5, "#f1f0ec"], [1.0, "#2a78d6"]]


def _layout(fig: go.Figure, title: str, height: int = 380, **kw) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15), x=0, xanchor="left"),
        height=height, margin=dict(l=10, r=20, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
        hoverlabel=dict(font_size=13), **{"bargap": 0.35, **kw})
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", zeroline=False)
    return fig


def football_field(res: Result) -> go.Figure:
    rows = [(label, low, high) for label, low, high in res.football[:-1] if low is not None and high is not None]
    labels = [r[0] for r in rows][::-1]
    lows = [r[1] for r in rows][::-1]
    highs = [r[2] for r in rows][::-1]
    fig = go.Figure(go.Bar(
        y=labels, x=[h - l for l, h in zip(lows, highs)], base=lows, orientation="h", marker_color=BLUE,
        marker_line_width=0, width=0.5, customdata=list(zip(lows, highs)),
        hovertemplate="%{y}<br>$%{customdata[0]:.2f} to $%{customdata[1]:.2f}<extra></extra>"))
    for label, low, high in zip(labels, lows, highs):
        fig.add_annotation(y=label, x=low, text=f"{low:.1f}", showarrow=False, xanchor="right", xshift=-6)
        fig.add_annotation(y=label, x=high, text=f"{high:.1f}", showarrow=False, xanchor="left", xshift=6)
    price = res.a.price
    fig.add_vline(x=price, line_width=2, line_dash="dot", line_color=ORANGE,
                  annotation_text=f"Share price ${price:.2f}", annotation_position="top")
    _layout(fig, "Value per share by method ($)", height=90 + 52 * len(rows))
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.18)", tickprefix="$")
    fig.update_yaxes(showgrid=False)
    return fig


def revenue_and_ebitda(res: Result) -> go.Figure:
    c, p = res.target, res.proj
    years = [f"{d.year}A" for d in c.fiscal_years] + [f"{d.year}E" for d in p.ends]
    nh = len(c.fiscal_years)
    revenue = c.hist["revenue"] + p.revenue
    ebitda = c.hist["ebitda_adjusted"] + p.ebitda
    fig = go.Figure()
    fig.add_bar(x=years, y=revenue, name="Revenue", marker_color=[GREY] * nh + [BLUE] * len(p.ends),
                hovertemplate="%{x}: $%{y:,.0f}m<extra>Revenue</extra>")
    fig.add_bar(x=years, y=ebitda, name="Adjusted EBITDA", marker_color=[LIGHT_BLUE] * len(years),
                hovertemplate="%{x}: $%{y:,.0f}m<extra>EBITDA</extra>")
    fig.update_layout(barmode="group", showlegend=False)
    fig.add_vline(x=nh - 0.5, line_width=1, line_dash="dot", line_color=GREY)
    return _layout(fig, "Revenue (dark) and adjusted EBITDA (light), $m: published in grey, projected in blue")


def margins(res: Result) -> go.Figure:
    c, p = res.target, res.proj
    years = [f"{d.year}A" for d in c.fiscal_years] + [f"{d.year}E" for d in p.ends]
    margin = [e / r for e, r in zip(c.hist["ebitda_adjusted"] + p.ebitda, c.hist["revenue"] + p.revenue)]
    growth = [None] + [b / a - 1 for a, b in zip(c.hist["revenue"], c.hist["revenue"][1:])] + res.a.revenue_growth
    fig = go.Figure()
    fig.add_scatter(x=years, y=margin, name="EBITDA margin", mode="lines+markers", line=dict(color=BLUE, width=2),
                    marker=dict(size=8), hovertemplate="%{x}: %{y:.1%}<extra>EBITDA margin</extra>")
    fig.add_scatter(x=years, y=growth, name="Revenue growth", mode="lines+markers", line=dict(color=ORANGE, width=2),
                    marker=dict(size=8), hovertemplate="%{x}: %{y:.1%}<extra>Revenue growth</extra>")
    fig.add_vline(x=len(c.fiscal_years) - 0.5, line_width=1, line_dash="dot", line_color=GREY)
    _layout(fig, "EBITDA margin and revenue growth")
    fig.update_yaxes(tickformat=".0%")
    return fig


def free_cash_flows(res: Result) -> go.Figure:
    years = [f"{d.year}E" for d in res.proj.ends]
    pv = [f * w * k for f, w, k in zip(res.dcf.fcf, res.dcf.weights, res.dcf.factors)]
    fig = go.Figure()
    fig.add_bar(x=years, y=res.dcf.fcf, name="Free cash flow", marker_color=LIGHT_BLUE,
                hovertemplate="%{x}: $%{y:,.0f}m<extra>Free cash flow</extra>")
    fig.add_bar(x=years, y=pv, name="Discounted (and prorated in year 1)", marker_color=BLUE,
                hovertemplate="%{x}: $%{y:,.0f}m<extra>Discounted</extra>")
    fig.update_layout(barmode="group")
    return _layout(fig, "Free cash flows, $m")


def value_bridge(res: Result, method: str = "gordon") -> go.Figure:
    d, a = res.dcf, res.a
    pv_tv = d.pv_tv_gordon if method == "gordon" else d.pv_tv_multiple
    equity = d.equity_gordon if method == "gordon" else d.equity_multiple
    fig = go.Figure(go.Waterfall(
        x=["Discounted cash flows", "Discounted terminal value", "Enterprise value", "Net debt and other", "Equity value"],
        y=[d.pv_fcf, pv_tv, 0, -a.bridge, 0], measure=["relative", "relative", "total", "relative", "total"],
        text=[f"{v:,.0f}" for v in (d.pv_fcf, pv_tv, d.pv_fcf + pv_tv, -a.bridge, equity)], textposition="outside",
        increasing=dict(marker=dict(color=BLUE)), decreasing=dict(marker=dict(color=ORANGE)),
        totals=dict(marker=dict(color=GREY)), connector=dict(line=dict(color="rgba(128,128,128,0.4)", width=1)),
        hovertemplate="%{x}: $%{text}m<extra></extra>"))
    title = "perpetual growth" if method == "gordon" else "exit multiple"
    return _layout(fig, f"From cash flows to equity value, $m ({title})", showlegend=False)


def heatmap(values, row_labels, col_labels, title: str, x_title: str, y_title: str, fmt: str, base=None) -> go.Figure:
    z = [[v if v is not None else float("nan") for v in row] for row in values]
    text = [[("n.m." if v is None else format(v, fmt)) for v in row] for row in values]
    fig = go.Figure(go.Heatmap(
        z=z, x=col_labels, y=row_labels, text=text, texttemplate="%{text}", colorscale=SEQUENTIAL, showscale=False,
        xgap=2, ygap=2, hovertemplate=f"{y_title} %{{y}}<br>{x_title} %{{x}}<br>%{{text}}<extra></extra>"))
    _layout(fig, title, height=330)
    fig.update_xaxes(title_text=x_title, type="category", side="bottom")
    fig.update_yaxes(title_text=y_title, type="category", autorange="reversed", showgrid=False)
    return fig


def comps_multiples(res: Result, multiple: str = "ev_ebitda") -> go.Figure:
    comps = res.comps
    rows = [(p.company.ticker, p.multiple(multiple, comps.cap)) for p in comps.peers]
    rows = sorted([(t, m) for t, m in rows if m is not None], key=lambda r: r[1])
    fig = go.Figure(go.Bar(x=[t for t, _ in rows], y=[m for _, m in rows], marker_color=BLUE, width=0.5,
                           text=[f"{m:.1f}x" for _, m in rows], textposition="outside",
                           hovertemplate="%{x}: %{y:.1f}x<extra></extra>"))
    median = comps.stats[multiple]["median"]
    if median is not None:
        fig.add_hline(y=median, line_width=2, line_dash="dot", line_color=ORANGE,
                      annotation_text=f"Median {median:.1f}x", annotation_position="top left")
    sector = getattr(comps.industry, multiple, None) if comps.industry else None
    if sector is not None:
        fig.add_hline(y=sector, line_width=1, line_dash="dash", line_color=GREY,
                      annotation_text=f"Sector {sector:.1f}x", annotation_position="bottom right")
    return _layout(fig, f"{LABELS[multiple]} of the comparables (LTM)", showlegend=False)


def debt_paydown(res: Result) -> go.Figure:
    lbo, p = res.lbo, res.proj
    years = ["Closing"] + [f"{d.year}E" for d in p.ends[1:]]
    fig = go.Figure()
    fig.add_bar(x=years, y=[lbo.senior_debt] + lbo.senior_end, name="Senior debt", marker_color=BLUE,
                hovertemplate="%{x}: $%{y:,.0f}m<extra>Senior debt</extra>")
    if lbo.sub_debt > 0:
        fig.add_bar(x=years, y=[lbo.sub_debt] + lbo.sub_end, name="Subordinated debt", marker_color=ORANGE,
                    hovertemplate="%{x}: $%{y:,.0f}m<extra>Subordinated debt</extra>")
    fig.update_layout(barmode="stack")
    return _layout(fig, "Acquisition debt at year end, $m")


def sources_and_uses(res: Result) -> go.Figure:
    lbo, a = res.lbo, res.a
    uses = [("Purchase of shares", lbo.equity_purchase), ("Refinanced debt", lbo.refinanced_debt),
            ("Fees", lbo.transaction_fees + lbo.financing_fees), ("Minimum cash", a.min_cash)]
    sources = [("Sponsor equity", lbo.sponsor_equity), ("Senior debt", lbo.senior_debt),
               ("Subordinated debt", lbo.sub_debt), ("Company cash", lbo.closing_cash)]
    fig = go.Figure()
    for side, items, color in (("Uses", uses, GREY), ("Sources", sources, BLUE)):
        items = [(k, v) for k, v in items if v > 0]
        fig.add_bar(y=[k for k, _ in items][::-1], x=[v for _, v in items][::-1], orientation="h", name=side,
                    marker_color=color, text=[f"{v:,.0f}" for _, v in items][::-1], textposition="outside",
                    hovertemplate="%{y}: $%{x:,.0f}m<extra>" + side + "</extra>")
    _layout(fig, f"Sources (blue) and uses (grey), $m: total {lbo.total_uses:,.0f}", height=400, showlegend=False)
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(range=[0, 1.15 * max(lbo.equity_purchase, lbo.sponsor_equity, lbo.senior_debt)])
    return fig


def scenarios(results: dict[str, Result]) -> go.Figure:
    names = list(results)
    fig = go.Figure()
    for label, color, pick in (("DCF, perpetual growth", BLUE, lambda r: r.dcf.share_gordon),
                               ("DCF, exit multiple", ORANGE, lambda r: r.dcf.share_multiple),
                               ("LBO maximum price", AQUA, lambda r: r.lbo.max_price[r.a.target_irr])):
        values = [pick(results[n]) for n in names]
        fig.add_bar(x=names, y=values, name=label, marker_color=color, text=[f"{v:.1f}" for v in values],
                    textposition="outside", hovertemplate="%{x}: $%{y:.2f}<extra>" + label + "</extra>")
    price = next(iter(results.values())).a.price
    fig.add_hline(y=price, line_width=2, line_dash="dot", line_color=GREY,
                  annotation_text=f"Share price ${price:.2f}", annotation_position="top left")
    fig.update_layout(barmode="group")
    return _layout(fig, "Value per share by scenario ($)")


def monte_carlo(mc: MonteCarlo, price: float) -> go.Figure:
    fig = go.Figure(go.Histogram(x=mc.values, nbinsx=50, marker_color=BLUE, marker_line_width=0,
                                 hovertemplate="$%{x}: %{y} draws<extra></extra>"))
    fig.add_vline(x=price, line_width=2, line_dash="dot", line_color=ORANGE,
                  annotation_text=f"Share price ${price:.2f}", annotation_position="top left")
    fig.add_vline(x=mc.median, line_width=2, line_color=GREY,
                  annotation_text=f"Median ${mc.median:.2f}", annotation_position="top right")
    _layout(fig, "Distribution of the DCF value per share ($)", showlegend=False, bargap=0.05)
    fig.update_xaxes(tickprefix="$")
    return fig


def accretion(points: list[tuple[float, float]]) -> go.Figure:
    """EPS accretion as a function of the share of stock in the price."""
    fig = go.Figure(go.Scatter(x=[p[0] for p in points], y=[p[1] for p in points], mode="lines+markers",
                               line=dict(color=BLUE, width=2), marker=dict(size=8),
                               hovertemplate="%{x:.0%} in stock: %{y:+.1%}<extra></extra>"))
    fig.add_hline(y=0, line_width=1, line_color=GREY)
    _layout(fig, "EPS accretion (+) or dilution (-) by share of stock in the price", showlegend=False)
    fig.update_xaxes(tickformat=".0%", title_text="Share of the price paid in stock")
    fig.update_yaxes(tickformat="+.0%")
    return fig
