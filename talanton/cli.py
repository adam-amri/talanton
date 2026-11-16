"""Command line: `talanton run TICKER --peers A,B,C`, and a few helpers."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

from . import config
from .checks import reconcile, recalculate, verify
from .data import DataError, EdgarClient, load_industries, suggest_peers
from .data import damodaran
from .data.market import FinnhubProvider
from .engine import BASE, collect, compute, compute_scenarios
from .excel import build_workbook
from .model import load_config
from .restatement import RestatementError
from .valuation import MergerTerms, compute_merger

FAILURES = (DataError, RestatementError, ValueError)


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="talanton", description="From a ticker to an M&A / LBO valuation model in Excel.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--cache", type=Path, default=Path("data_cache"),
                       help="folder where downloaded data is kept (default: data_cache)")
        p.add_argument("--offline", action="store_true", help="use the cache only, no network access")

    run = sub.add_parser("run", help="build the model of a US-listed company")
    run.add_argument("ticker", help="ticker of the target company, for example MAT")
    run.add_argument("--peers", default="", help="tickers of the comparables, separated by commas")
    common(run)
    run.add_argument("--adjustments", type=Path,
                     help="TOML file of analyst adjustments (default: adjustments/TICKER.toml if it exists)")
    run.add_argument("--config", type=Path, help="TOML config: assumption overrides, settings, theme, scenarios")
    run.add_argument("--scenario", default=BASE, help="scenario of the config to build the workbook for")
    run.add_argument("--output", type=Path, default=Path("output"), help="folder of the workbook produced")
    run.add_argument("--no-recalc", action="store_true",
                     help="do not call LibreOffice (Excel will compute the formulas on opening)")

    peers = sub.add_parser("peers", help="suggest comparable companies (same SEC industry code)")
    peers.add_argument("ticker")
    peers.add_argument("--limit", type=int, default=20)
    common(peers)

    merger = sub.add_parser("merger", help="accretion / dilution of an acquirer buying a target")
    merger.add_argument("acquirer")
    merger.add_argument("target")
    merger.add_argument("--premium", type=float, default=0.30)
    merger.add_argument("--stock", type=float, default=0.5, help="share of the price paid in acquirer shares (0 to 1)")
    merger.add_argument("--synergies", type=float, default=0.0, help="pre-tax run-rate synergies, in $m")
    merger.add_argument("--debt-rate", type=float, default=0.065)
    merger.add_argument("--adjustments", type=Path)
    common(merger)

    sub.add_parser("sources", help="show the data sources and which API keys are set")
    industries = sub.add_parser("industries", help="list the sector references (Damodaran)")
    industries.add_argument("--refresh", action="store_true", help="download the current tables first")
    industries.add_argument("--cache", type=Path, default=Path("data_cache"))
    app = sub.add_parser("app", help="open the interactive interface in the browser")
    app.add_argument("--port", type=int, default=8501)
    return parser.parse_args(argv)


def _run(args) -> int:
    ticker = args.ticker.upper()
    peers = [t.strip().upper() for t in args.peers.split(",") if t.strip()]
    adjustments = args.adjustments
    if adjustments is None:
        candidate = Path("adjustments") / f"{ticker}.toml"
        adjustments = candidate if candidate.exists() else None
    cfg = load_config(args.config)
    inputs = collect(ticker, peers, args.cache, args.offline, adjustments, cfg.settings)
    results = compute_scenarios(inputs, cfg)
    if args.scenario not in results:
        raise ValueError(f"Unknown scenario {args.scenario!r}. Defined: {', '.join(results)}.")
    res = results[args.scenario]

    issues = verify(res)
    wb, registry = build_workbook(res, date.today())
    args.output.mkdir(parents=True, exist_ok=True)
    suffix = "" if res.scenario == BASE else f"_{res.scenario}"
    file = args.output / f"{ticker}_model{suffix}.xlsx"
    wb.save(file)

    a, d, lbo = res.a, res.dcf, res.lbo
    median = res.comps.implied.get("ev_ebitda", {}).get("median")
    print(f"\n{res.target.name} ({ticker}), share price ${a.price:.2f}, enterprise value ${a.enterprise_value:,.0f}m"
          + ("" if res.scenario == BASE else f"  [scenario: {res.scenario}]"))
    print(f"  DCF, perpetual growth : ${d.share_gordon:6.2f} per share (WACC {a.wacc:.2%}, beta {a.beta:.2f})")
    print(f"  DCF, exit multiple    : ${d.share_multiple:6.2f} per share")
    if median is not None:
        print(f"  Comps, median EV/EBITDA: ${median:6.2f} per share")
    print(f"  LBO at a {a.acquisition_premium:.0%} premium: IRR {lbo.irr:.1%}, MOIC {lbo.moic:.2f}x")
    print(f"  Maximum price for a fund targeting a {a.target_irr:.0%} IRR: ${lbo.max_price[a.target_irr]:.2f} per share")
    if len(results) > 1:
        print("\n  Scenario        DCF growth   DCF multiple   LBO IRR   Max price")
        for name, r in results.items():
            print(f"  {name:<14} {r.dcf.share_gordon:>10.2f} {r.dcf.share_multiple:>14.2f} {r.lbo.irr:>9.1%}"
                  f" {r.lbo.max_price[r.a.target_irr]:>11.2f}")
    print("\nSources:")
    for line in res.sources:
        print(f"  {line}")
    for level, message in issues:
        print(f"  [{level}] {message}")
    for message in inputs.notes:
        print(f"  [NOTE] {message}")

    code = 1 if any(level == "ERROR" for level, _ in issues) else 0
    if args.no_recalc:
        print("\nFormulas not recalculated: Excel will compute them on opening.")
    elif recalculate(file):
        rec = reconcile(file, registry, res.checkpoints())
        if rec.ok:
            print(f"\nReconciliation: {rec.n_formulas} formulas recalculated without error, "
                  f"Excel = Python on {len(res.checkpoints())} key figures.")
        else:
            code = 1
            print("\nReconciliation failed:", file=sys.stderr)
            for key, (excel, python) in rec.gaps.items():
                print(f"  {key}: Excel {excel} / Python {python}", file=sys.stderr)
            for cell in rec.formula_errors[:20] + rec.empty_cells[:20]:
                print(f"  formula in error or empty: {cell}", file=sys.stderr)
    else:
        print("\nLibreOffice not found: Python / Excel reconciliation not run from the command line. "
              "The Checks sheet does it when the workbook is opened.")
    print(f"Workbook: {file}")
    return code


def _peers(args) -> int:
    key = config.get(config.FINNHUB)
    finnhub = FinnhubProvider(key) if key and not args.offline else None
    suggestions, notes = suggest_peers(EdgarClient(args.cache, offline=args.offline), args.ticker, args.limit, finnhub)
    if not suggestions:
        print(f"No suggestion for {args.ticker.upper()}.")
    for s in suggestions:
        print(f"  {s.ticker:<7} {s.name[:44]:<44} {s.reason}")
    for n in notes:
        print(f"  [NOTE] {n}")
    if suggestions:
        print("\nSuggestions only: SIC codes are coarse and the list includes micro-caps. Pick the peers yourself, e.g.")
        print(f"  talanton run {args.ticker.upper()} --peers {','.join(s.ticker for s in suggestions[:5])}")
    return 0


def _merger(args) -> int:
    acquirer, target = args.acquirer.upper(), args.target.upper()
    inputs = collect(target, [acquirer], args.cache, args.offline, args.adjustments)
    if not inputs.peers:
        raise ValueError(f"The accounts of the acquirer {acquirer} could not be read.")
    res = compute(inputs)
    terms = MergerTerms(premium=args.premium, stock_pct=args.stock, synergies=args.synergies, debt_rate=args.debt_rate)
    m = compute_merger(inputs.peers[0], inputs.target, res.a, terms)
    print(f"\n{acquirer} buys {target} at ${m.offer_price:.2f} per share ({terms.premium:.0%} premium): "
          f"${m.equity_purchase:,.0f}m for the shares")
    print(f"  Paid {terms.stock_pct:.0%} in stock: {m.new_shares:.1f}m new shares "
          f"({m.exchange_ratio:.4f} per target share), {m.target_ownership:.1%} of the combined company")
    print(f"  New debt (cash part and fees): ${m.new_debt:,.0f}m at {terms.debt_rate:.2%}")
    print(f"  EPS: ${m.acquirer_eps:.2f} standalone -> ${m.pro_forma_eps:.2f} pro forma: "
          f"{m.accretion:+.1%} ({'accretive' if m.accretion >= 0 else 'dilutive'})")
    print(f"  Synergies needed to break even: ${m.breakeven_synergies:,.0f}m pre-tax (assumed: ${terms.synergies:,.0f}m)")
    print(f"  Pro forma net debt / EBITDA: {m.pro_forma_leverage:.1f}x")
    print("  First-pass analysis on LTM earnings: no purchase price allocation, no integration costs.")
    return 0


def _sources() -> int:
    print("Data sources of the Open edition (free):")
    print("  SEC EDGAR            accounts, company profile, industry code     no key")
    print("  FRED                 Treasury yield, SOFR, credit spreads         no key (public CSV), or API key")
    print("  Damodaran (NYU)      sector betas and EV multiples                no key (snapshot bundled)")
    print("  Yahoo Finance        share prices, monthly history                no key (yfinance)")
    print("  Alpha Vantage        backup for prices and history                free key")
    print("  Finnhub              backup for prices, peer suggestions          free key")
    print("Terminal edition: Bloomberg Terminal through blpapi (experimental).\n")
    for variable, is_set in config.status():
        state = "set    " if is_set else ("MISSING" if variable.required else "not set")
        print(f"  {variable.name:<22} {state}  {variable.purpose}")
        if not is_set:
            print(f"  {'':<22}          -> {variable.where}")
    return 0


def _industries(args) -> int:
    table = damodaran.refresh(args.cache) if args.refresh else load_industries(args.cache)
    as_of = next(iter(table.values())).as_of
    print(f"Sector references, A. Damodaran (NYU Stern), data as of {as_of}\n")
    print(f"  {'Industry':<40} {'Firms':>5} {'Unlev. beta':>11} {'EV/EBITDA':>9}")
    for i in table.values():
        beta = f"{i.unlevered_beta_cash_corrected:.2f}" if i.unlevered_beta_cash_corrected is not None else "n.a."
        mult = f"{i.ev_ebitda:.1f}x" if i.ev_ebitda is not None else "n.a."
        print(f"  {i.name:<40} {i.firms:>5} {beta:>11} {mult:>9}")
    return 0


def _app(args) -> int:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print('The interface needs extra packages: pip install -e ".[app]"', file=sys.stderr)
        return 1
    script = Path(__file__).parent / "app" / "main.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(script), "--server.port", str(args.port)])


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    args = _parse(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "peers":
            return _peers(args)
        if args.command == "merger":
            return _merger(args)
        if args.command == "sources":
            return _sources()
        if args.command == "industries":
            return _industries(args)
        return _app(args)
    except FAILURES as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
