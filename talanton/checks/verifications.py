"""Consistency checks done by Python, before the workbook is even written."""

from __future__ import annotations

from ..engine import Result

TOLERANCE = 1e-6
ERROR, WARNING = "ERROR", "WARNING"


def verify(res: Result) -> list[tuple[str, str]]:
    """Returns the list of anomalies: (level, message). Level: ERROR or WARNING."""
    issues: list[tuple[str, str]] = []
    company, a, p, d, lbo = res.target, res.a, res.proj, res.dcf, res.lbo

    for end, assets, le in zip(company.fiscal_years, company.hist["total_assets"],
                               company.hist["total_liabilities_equity"]):
        if abs(assets - le) > 0.5:
            issues.append((ERROR, f"Published balance sheet out of balance at {end}: {assets - le:+.1f} $m."))
    for end, assets, le in zip(p.ends, p.total_assets, p.total_liabilities_equity):
        if abs(assets - le) > TOLERANCE * max(1.0, assets):
            issues.append((ERROR, f"Projected balance sheet out of balance at {end}: {assets - le:+.4f} $m."))
    sources = lbo.senior_debt + lbo.sub_debt + lbo.closing_cash + lbo.sponsor_equity
    if abs(sources - lbo.total_uses) > TOLERANCE * lbo.total_uses:
        issues.append((ERROR, "LBO: sources do not exactly cover uses."))
    if a.wacc - a.terminal_growth <= 0.005:
        issues.append((ERROR, "The WACC must exceed perpetual growth by at least 0.5 point."))
    if lbo.sponsor_equity <= 0:
        issues.append((ERROR, "LBO: debt exceeds the price paid, sponsor equity is negative."))

    for name, share in (("perpetual growth", d.tv_share_gordon), ("exit multiple", d.tv_share_multiple)):
        if share >= 0.8:
            issues.append((WARNING, f"DCF with {name}: terminal value is {share:.0%} of the value."))
    n_peers = len(res.comps.values("ev_ebitda"))
    if n_peers < 4:
        issues.append((WARNING, f"Only {n_peers} comparable(s) with a meaningful EV / EBITDA."))
    if min(p.cash) < 0:
        issues.append((WARNING, "Projected cash turns negative."))
    if min(lbo.cash_end) < 0:
        issues.append((WARNING, "LBO: cash turns negative, the debt is not sustainable."))
    for w in company.warnings:
        issues.append((WARNING, w))
    for peer in res.comps.peers:
        for w in peer.company.warnings:
            issues.append((WARNING, w))
    return issues
