"""Data collection and restatement: the right figures, despite the traps of published data."""

import sys
import types
from datetime import date

import pytest

from talanton import config
from talanton.data import DataError, EdgarClient, FredClient, MarketData, load_industries, relever, suggest_peers
from talanton.data import damodaran
from talanton.data.fred import parse_csv
from talanton.data.market import AlphaVantageProvider, FinnhubProvider, YahooProvider, regression_beta
from talanton.restatement import build_company, load_adjustments
from talanton.restatement.facts import Facts

from .conftest import ADJUSTMENTS, CACHE


def peer(edgar, ticker):
    return build_company(ticker, edgar.facts(ticker), 1, None, detailed_balance=False)


def test_fiscal_years_and_last_quarter(inputs):
    target = inputs.target
    assert [d.year for d in target.fiscal_years] == [2021, 2022, 2023, 2024, 2025]
    assert target.balance_date == date(2026, 9, 30)
    assert target.shares == pytest.approx(285.5)


def test_ltm_is_year_plus_ytd_minus_prior_ytd(inputs):
    ltm = inputs.target.ltm
    assert ltm["revenue"] == pytest.approx(5347.623 + 3794.187 - 3581.163)
    assert ltm["ebit"] == pytest.approx(546.424 + 384.458 - 405.368)
    assert ltm["da"] == pytest.approx(167.985 + 143.286 - 125.954)


def test_published_balance_sheets_balance(inputs):
    h = inputs.target.hist
    for assets, le in zip(h["total_assets"], h["total_liabilities_equity"]):
        assert assets == pytest.approx(le)
    assert all(v > 0 for v in h["other_assets"] + h["other_liabilities"])


def test_analyst_adjustments(inputs):
    target = inputs.target
    assert target.hist["capex"][-1] == pytest.approx(181.992)       # rebuilt total, not the partial line
    assert target.ltm["ebitda_adj"] == pytest.approx(-88.0)
    assert target.ltm["ebitda_adjusted"] == pytest.approx(target.ltm["ebitda_reported"] - 88.0)


def test_without_adjustment_partial_capex_is_flagged(edgar):
    raw = build_company("MAT", edgar.facts("MAT"), 5, None)
    assert raw.hist["capex"][-1] == pytest.approx(110.618)
    assert any("Capex" in w for w in raw.warnings)


def test_options_and_leases_read_from_the_10k(inputs):
    target = inputs.target
    assert (target.options, target.option_strike) == (pytest.approx(8.022), pytest.approx(19.31))
    assert target.rsus == 0.0 and "RSUs are not tagged" in target.dilution_source
    assert target.lease_liabilities == pytest.approx(351.593)


def test_hasbro_two_revenue_tags(edgar):
    has = peer(edgar, "HAS")
    assert has.ltm["revenue"] == pytest.approx(4701.3 + 3735.1 - 3255.4)    # and not 5,365.9
    assert any("disagree" in w for w in has.warnings)


def test_hasbro_goodwill_impairment_outside_the_ltm_window(edgar):
    has = peer(edgar, "HAS")
    assert has.ltm["impairments"] == pytest.approx(0.0)
    assert has.ltm["ebit"] == pytest.approx(11.1 + 1040.1 + 286.4)


def test_jakks_shares_in_thousands_in_the_10q(edgar):
    assert peer(edgar, "JAKK").shares == pytest.approx(11.519192)           # cover page, not 0.011869


def test_funko_without_cover_page(edgar):
    fnko = peer(edgar, "FNKO")
    assert fnko.shares == pytest.approx(57.111136)
    assert any("share count" in w for w in fnko.warnings)


def test_debt_all_components(edgar):
    golf = peer(edgar, "GOLF")
    assert golf.balance["debt"] == pytest.approx(854.393 + 0.653 + 21.521)
    assert golf.balance["minorities"] == pytest.approx(2.299 + 1.162)
    assert peer(edgar, "JAKK").balance["debt"] == 0.0


def test_yeti_53_week_year_and_half_year(edgar):
    yeti = peer(edgar, "YETI")
    assert yeti.fiscal_years[-1] == date(2026, 1, 3)
    assert yeti.ltm_date == date(2026, 7, 4)
    assert yeti.ltm["revenue"] == pytest.approx(1868.494 + 864.282 - 797.020)


def test_a_single_quarter_is_not_a_year_to_date(edgar):
    facts = Facts(edgar.facts("JAKK"))
    assert facts.year_to_date("ProfitLoss", date(2026, 1, 1), date(2026, 9, 30)) is None
    assert facts.year_to_date("NetIncomeLoss", date(2026, 1, 1), date(2026, 9, 30)).value == 31482000


def test_the_last_filing_wins():
    raw = {"cik": 1, "entityName": "Test", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2024-01-01", "end": "2024-12-31", "val": 100, "accn": "a", "form": "10-K", "filed": "2025-02-01"},
        {"start": "2024-01-01", "end": "2024-12-31", "val": 104, "accn": "b", "form": "10-K", "filed": "2026-02-01"},
        {"start": "2024-10-01", "end": "2024-12-31", "val": 30, "accn": "a", "form": "10-K", "filed": "2025-02-01"},
    ]}}}}}
    assert Facts(raw).annual("Revenues", date(2024, 12, 31)).value == 104     # restated figure


def test_offline_without_cache(tmp_path):
    with pytest.raises(DataError):
        EdgarClient(tmp_path, offline=True).facts("MAT")


def test_unknown_ticker(edgar):
    with pytest.raises(DataError):
        edgar.cik("XXXX")


def test_beta_on_a_built_series():
    index = [(date(2024, m, 1), 100 * 1.01 ** m * (1 + 0.02 * (-1) ** m)) for m in range(1, 13)]
    index += [(date(2025, m, 1), 113 * 1.01 ** m * (1 + 0.02 * (-1) ** m)) for m in range(1, 13)]
    stock = [index[0]]
    for (_, p0), (d, p1) in zip(index, index[1:]):
        stock.append((d, stock[-1][1] * (1 + 1.5 * (p1 / p0 - 1))))
    beta, n, r2 = regression_beta(stock, index)
    assert (round(beta, 6), n, round(r2, 6)) == (1.5, 23, 1.0)


def test_mattel_beta(market):
    beta, n, r2 = market.beta("MAT")
    assert n == 58 and 0.4 < beta < 0.8 and r2 < 0.2


def test_adjustments_file(tmp_path):
    adj = load_adjustments(ADJUSTMENTS)
    assert len(adj.capex) == 5 and adj.ebitda == {"LTM": -88.0} and "stockanalysis" in adj.capex_source
    bad = tmp_path / "bad.toml"
    bad.write_text("[resultat]\nLTM = 1\n")
    with pytest.raises(ValueError, match="unknown section"):
        load_adjustments(bad)


# --- profile, industry code and peer suggestions ---------------------------------

def test_profile_and_sic(edgar):
    p = edgar.profile("MAT")
    assert (p.sic, p.sic_description, p.tickers) == ("3942", "Dolls & Stuffed Toys", ("MAT",))


def test_companies_by_sic_and_listed(edgar):
    companies = edgar.companies_by_sic("3944")
    assert len(companies) == 53 and (46080, "HASBRO, INC.") in companies
    assert (913160, "CREATIVE PROGRAMMING & TECHNOLOGY VENTURES INC") in companies     # XML entity decoded
    listed = edgar.listed({c for c, _ in companies})
    assert {t for t, _ in listed.values()} == {"HAS", "FNKO", "JAKK", "KMRK", "NNUP"}


def test_peer_suggestions_widen_to_neighbouring_codes(edgar):
    suggestions, notes = suggest_peers(edgar, "MAT", limit=30)
    tickers = [s.ticker for s in suggestions]
    assert "MAT" not in tickers and {"HAS", "FNKO", "JAKK", "GOLF"} <= set(tickers)
    assert tickers.index("HAS") < tickers.index("GOLF")                    # SIC 3944 before 3949
    assert notes == []


# --- FRED ------------------------------------------------------------------------

def test_fred_latest_as_of_the_price_date(fred):
    assert fred.latest("DGS10", date(2026, 11, 9)).value == 4.88
    assert fred.latest("DGS10", date(2026, 11, 11)).date == date(2026, 11, 10)     # holiday: blank value skipped
    assert fred.latest("SOFR", date(2026, 11, 9)).fraction == pytest.approx(0.0388)
    with pytest.raises(DataError):
        fred.latest("DGS10", date(2020, 1, 1))


def test_fred_csv_parser():
    assert parse_csv("observation_date,X\n2026-01-02,4.5\n2026-01-03,\n2026-01-04,.\n") == [(date(2026, 1, 2), 4.5)]


class _Response:
    def __init__(self, payload=None, text="", status=200):
        self._payload, self.text, self.status_code = payload, text, status
        self.content = text.encode("cp1252")

    def json(self):
        return self._payload


def test_fred_download_without_and_with_a_key(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, params))
        if "api.stlouisfed.org" in url:
            return _Response({"observations": [{"date": "2026-11-06", "value": "."}, {"date": "2026-11-09", "value": "4.88"}]})
        return _Response(text="observation_date,DGS10\n2026-11-09,4.88\n2026-11-10,4.98\n")

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.delenv(config.FRED, raising=False)
    client = FredClient(tmp_path / "a")
    assert client.latest("DGS10").value == 4.98 and calls[0][0].endswith("fredgraph.csv") and calls[0][1]["id"] == "DGS10"
    assert client.latest("DGS10").value == 4.98 and len(calls) == 1                # served by the cache
    keyed = FredClient(tmp_path / "b", api_key="k")
    assert keyed.latest("DGS10").value == 4.88 and calls[1][1]["api_key"] == "k"
    assert FredClient(tmp_path / "b", offline=True).series("DGS10") == [(date(2026, 11, 9), 4.88)]


# --- Damodaran ---------------------------------------------------------------------

def test_bundled_sector_table():
    table = load_industries()
    rec = table["Recreation"]
    assert len(table) == 96 and (rec.firms, rec.unlevered_beta_cash_corrected, rec.ev_ebitda) == (49, 0.74, 10.39)
    assert table["Banks (Regional)"].ev_ebitda is None and rec.as_of == "January 2026"
    assert damodaran.industry_for_sic("3942", table) is rec
    assert damodaran.industry_for_sic("7372", table).name == "Software (System & Application)"
    assert damodaran.industry_for_sic("9999", table) is None
    assert relever(0.74, 0.5, 0.25) == pytest.approx(0.74 * 1.375)


BETAS_PAGE = """<html><body><p>Date of Analysis: Data used is as of January 2027</p><table>
<tr><td class=x style='a:b'>Industry Name</td><td>Number of firms</td><td>Beta</td><td>D/E Ratio</td><td>Effective Tax rate</td>
<td>Unlevered beta</td><td>Cash/Firm value</td><td>Unlevered beta corrected for cash</td><td>HiLo Risk</td></tr>
<tr><td class=x>Recreation</td><td>50</td><td>1.05</td><td>60.00%</td><td>11.00%</td><td>0.72</td><td>5.00%</td>
<td>0.76</td><td>0.5</td></tr><tr><td></td><td></td></tr></table></body></html>"""
MULTIPLES_PAGE = """<html><body><table><tr><td></td><td></td><td>Only positive EBITDA firms</td><td>All firms</td></tr>
<tr><td>Industry Name</td><td>Number of firms</td><td>EV/EBITDAR&D</td><td>EV/EBITDA</td><td>EV/EBIT</td><td>EV/EBIT (1-t)</td>
<td>EV/EBITDAR&D</td><td>EV/EBITDA</td><td>EV/EBIT</td><td>EV/EBIT (1-t)</td></tr>
<tr><td>Recreation</td><td>50</td><td>9.5</td><td>11.00</td><td>NA</td><td>28</td><td>10</td><td>12</td><td>24</td><td>28</td></tr>
</table></body></html>"""


def test_sector_refresh_parses_the_html_tables(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.get", lambda url, headers=None, params=None, timeout=None:
                        _Response(text=BETAS_PAGE if "Betas" in url else MULTIPLES_PAGE))
    rec = damodaran.refresh(tmp_path)["Recreation"]
    assert (rec.firms, rec.debt_to_equity, rec.unlevered_beta_cash_corrected, rec.ev_ebitda, rec.ev_ebit) == \
        (50, 0.6, 0.76, 11.0, None)
    assert rec.as_of == "January 2027"
    assert load_industries(tmp_path)["Recreation"].firms == 50              # the refreshed copy now wins


# --- "online" paths, with a simulated network (no real call) ------------------------

def test_sec_download_identified_and_cached(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, headers["User-Agent"]))
        if "company_tickers" in url:
            return _Response({"0": {"cik_str": 63276, "ticker": "MAT", "title": "MATTEL INC /DE/"}})
        return _Response({"cik": 63276, "entityName": "MATTEL INC /DE/", "facts": {}})

    monkeypatch.setattr("requests.get", fake_get)
    client = EdgarClient(tmp_path, contact="Test Talanton test@example.com", pause_s=0)
    assert client.facts("mat")["cik"] == 63276
    assert [u for u, _ in calls] == ["https://www.sec.gov/files/company_tickers.json",
                                     "https://data.sec.gov/api/xbrl/companyfacts/CIK0000063276.json"]
    assert all(agent == "Test Talanton test@example.com" for _, agent in calls)
    client.facts("MAT")
    assert len(calls) == 2                                      # second call served by the cache


def test_the_sec_requires_identification(tmp_path, monkeypatch):
    monkeypatch.delenv(config.CONTACT, raising=False)
    with pytest.raises(DataError, match="TALANTON_CONTACT"):
        EdgarClient(tmp_path).facts("MAT")


def test_http_errors_become_clear_messages(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.get", lambda *a, **k: _Response(status=429))
    with pytest.raises(DataError, match="rate limit"):
        EdgarClient(tmp_path, contact="x", pause_s=0).facts("MAT")


def test_online_prices_with_simulated_yfinance(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    this_month = date.today().replace(day=1)

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        def history(self, period, interval, auto_adjust):
            if interval == "1d":
                return pd.DataFrame({"Close": [15.35, float("nan"), 15.59]},
                                    index=pd.to_datetime(["2026-11-06", "2026-11-07", "2026-11-09"]))
            months = pd.to_datetime(["2026-08-01", "2026-09-01", "2026-10-01", this_month.isoformat()])
            return pd.DataFrame({"Close": [14.95, 12.66, 15.42, 99.0]}, index=months)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    client = MarketData(tmp_path, providers=[YahooProvider()])
    q = client.quote("MAT")
    assert (q.price, q.date) == (15.59, date(2026, 11, 9))
    series = client.monthly("MAT")
    assert [p for _, p in series] == [14.95, 12.66, 15.42]      # the current, incomplete month is dropped
    again = MarketData(tmp_path, offline=True)                  # what was downloaded reads back offline
    assert again.quote("MAT").price == 15.59 and again.monthly("MAT") == series


def test_provider_chain_falls_back(tmp_path, monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if "alphavantage" in url:
            return _Response({"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."})
        return _Response({"c": 15.59, "t": 1794268800})          # Finnhub: 2026-11-10 UTC

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setitem(sys.modules, "yfinance", None)           # yfinance not installed
    client = MarketData(tmp_path, providers=[YahooProvider(), AlphaVantageProvider("k"), FinnhubProvider("k")])
    q = client.quote("MAT")
    assert q.price == 15.59 and q.source.startswith("Finnhub") and q.date == date(2026, 11, 10)
    with pytest.raises(DataError, match="No provider"):
        client.monthly("MAT")


def test_alpha_vantage_formats(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if params["function"] == "GLOBAL_QUOTE":
            return _Response({"Global Quote": {"01. symbol": params["symbol"], "05. price": "15.5900",
                                               "07. latest trading day": "2026-11-09"}})
        return _Response({"Monthly Adjusted Time Series": {"2026-10-30": {"5. adjusted close": "15.42"},
                                                           "2026-09-30": {"5. adjusted close": "12.66"}}})

    monkeypatch.setattr("requests.get", fake_get)
    av = AlphaVantageProvider("k")
    assert av.quote("MAT").price == 15.59
    assert av.monthly("^GSPC") == [(date(2026, 9, 1), 12.66), (date(2026, 10, 1), 15.42)]    # SPY stands in
    with pytest.raises(DataError):
        av.quote("^TNX")


def test_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv(config.FRED, raising=False)
    monkeypatch.setenv(config.FINNHUB, "from-environment")
    env = tmp_path / ".env"
    env.write_text('# keys\nFRED_API_KEY="abc"\nFINNHUB_API_KEY=ignored\nEMPTY=\n')
    assert config.load_env(env) == ["FRED_API_KEY"]
    assert config.get(config.FRED) == "abc" and config.get(config.FINNHUB) == "from-environment"
    monkeypatch.delenv(config.FRED)
