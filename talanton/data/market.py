"""Market data: last price, monthly history, beta, risk-free rate.

Prices come from a chain of interchangeable providers, tried in order until one
answers (see `default_providers`):

    Bloomberg Terminal (optional)  ->  Yahoo Finance  ->  Alpha Vantage  ->  Finnhub

Free sources carry no institutional quality guarantee and are meant for personal
use. Everything goes through a local cache, read as is in offline mode. Adding a
provider means writing a class with `quote` and `monthly` and putting it in the list.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

from .. import config
from .base import DataError, Quote, http_get

BENCHMARK = "^GSPC"             # S&P 500, for the beta
TEN_YEAR = "^TNX"               # 10-year Treasury yield, in %
MIN_RETURNS = 12


class Provider(Protocol):
    name: str

    def quote(self, ticker: str) -> Quote: ...

    def monthly(self, ticker: str) -> list[tuple[date, float]]: ...


def regression_beta(stock: list[tuple[date, float]], index: list[tuple[date, float]]
                    ) -> tuple[float, int, float]:
    """Beta = slope of the regression of the stock's monthly returns on the index's.

    Returns (beta, number of returns, R²). Only months present in both series are kept.
    """
    index_prices = dict(index)
    common = [(d, p, index_prices[d]) for d, p in sorted(stock) if d in index_prices]
    if len(common) < MIN_RETURNS + 1:
        raise DataError(f"Price history too short to estimate a beta ({MIN_RETURNS} returns minimum).")
    rs = [common[i][1] / common[i - 1][1] - 1 for i in range(1, len(common))]
    ri = [common[i][2] / common[i - 1][2] - 1 for i in range(1, len(common))]
    n = len(rs)
    ms, mi = sum(rs) / n, sum(ri) / n
    cov = sum((a - ms) * (b - mi) for a, b in zip(rs, ri))
    var_i = sum((b - mi) ** 2 for b in ri)
    var_s = sum((a - ms) ** 2 for a in rs)
    beta = cov / var_i
    r2 = (cov * cov) / (var_i * var_s) if var_s else 0.0
    return beta, n, r2


def _drop_current_month(series: list[tuple[date, float]]) -> list[tuple[date, float]]:
    today = date.today()
    return [(d, p) for d, p in series if (d.year, d.month) != (today.year, today.month)]


# -- providers ----------------------------------------------------------------
class YahooProvider:
    """Yahoo Finance through the yfinance library. No key."""

    name = "Yahoo Finance"

    def quote(self, ticker: str) -> Quote:
        import yfinance as yf

        history = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
        history = history.dropna(subset=["Close"])
        if history.empty:
            raise DataError(f"Yahoo Finance returned no price for {ticker}.")
        day = history.index[-1].date()
        currency = "%" if ticker == TEN_YEAR else "USD"
        return Quote(ticker, day, float(history["Close"].iloc[-1]), currency,
                     f"Yahoo Finance, close of {day.isoformat()}")

    def monthly(self, ticker: str) -> list[tuple[date, float]]:
        import yfinance as yf

        history = yf.Ticker(ticker).history(period="5y", interval="1mo", auto_adjust=True)
        history = history.dropna(subset=["Close"])
        series = [(stamp.date().replace(day=1), float(price)) for stamp, price in history["Close"].items()]
        return _drop_current_month(series)


class AlphaVantageProvider:
    """Alpha Vantage (free key). The free tier allows only a few requests per day."""

    name = "Alpha Vantage"
    URL = "https://www.alphavantage.co/query"
    ALIASES = {BENCHMARK: "SPY"}        # no index data on the free tier: the S&P 500 ETF stands in

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _call(self, function: str, ticker: str) -> dict:
        if ticker.startswith("^") and ticker not in self.ALIASES:
            raise DataError(f"Alpha Vantage has no data for the index {ticker}.")
        symbol = self.ALIASES.get(ticker, ticker)
        data = http_get(self.URL, what=f"Alpha Vantage ({ticker})",
                        params={"function": function, "symbol": symbol, "apikey": self.api_key}).json()
        for key in ("Note", "Information", "Error Message"):
            if key in data:
                raise DataError(f"Alpha Vantage ({ticker}): {str(data[key])[:160]}")
        return data

    def quote(self, ticker: str) -> Quote:
        row = self._call("GLOBAL_QUOTE", ticker).get("Global Quote") or {}
        try:
            day = date.fromisoformat(row["07. latest trading day"])
            return Quote(ticker, day, float(row["05. price"]), "USD",
                         f"Alpha Vantage, close of {day.isoformat()}")
        except (KeyError, ValueError) as exc:
            raise DataError(f"Alpha Vantage returned no price for {ticker}.") from exc

    def monthly(self, ticker: str) -> list[tuple[date, float]]:
        rows = self._call("TIME_SERIES_MONTHLY_ADJUSTED", ticker).get("Monthly Adjusted Time Series") or {}
        series = sorted((date.fromisoformat(d).replace(day=1), float(v["5. adjusted close"]))
                        for d, v in rows.items())
        return _drop_current_month(series)[-60:]


class FinnhubProvider:
    """Finnhub (free key): last price only, and peer suggestions (see `peers`)."""

    name = "Finnhub"
    URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def quote(self, ticker: str) -> Quote:
        if ticker.startswith("^"):
            raise DataError(f"Finnhub has no data for the index {ticker}.")
        data = http_get(f"{self.URL}/quote", what=f"Finnhub ({ticker})",
                        params={"symbol": ticker, "token": self.api_key}).json()
        if not data.get("c") or not data.get("t"):
            raise DataError(f"Finnhub returned no price for {ticker}.")
        day = datetime.fromtimestamp(int(data["t"]), tz=timezone.utc).date()
        return Quote(ticker, day, float(data["c"]), "USD", f"Finnhub, last price of {day.isoformat()}")

    def monthly(self, ticker: str) -> list[tuple[date, float]]:
        raise DataError("Finnhub's free tier has no price history.")

    def peers(self, ticker: str) -> list[str]:
        data = http_get(f"{self.URL}/stock/peers", what=f"Finnhub peers ({ticker})",
                        params={"symbol": ticker, "token": self.api_key}).json()
        return [t.upper() for t in data if isinstance(t, str) and t.upper() != ticker.upper()]


def default_providers() -> list[Provider]:
    """Provider chain built from the keys available in the environment."""
    chain: list[Provider] = []
    if config.get(config.BLOOMBERG) in ("1", "true", "yes"):
        from .bloomberg import BloombergProvider

        chain.append(BloombergProvider())
    chain.append(YahooProvider())
    if config.get(config.ALPHA_VANTAGE):
        chain.append(AlphaVantageProvider(config.get(config.ALPHA_VANTAGE)))
    if config.get(config.FINNHUB):
        chain.append(FinnhubProvider(config.get(config.FINNHUB)))
    return chain


# -- cached access --------------------------------------------------------------
def _file_name(ticker: str) -> str:
    return ticker.replace("^", "_")


class MarketData:
    def __init__(self, cache: Path, offline: bool = False, providers: list[Provider] | None = None):
        self.cache = Path(cache) / "market"
        self.offline = offline
        self.providers = providers if providers is not None else ([] if offline else default_providers())
        self.log: list[str] = []            # which provider failed, and why

    def _first(self, method: str, ticker: str):
        """Tries each provider in turn and returns the first answer."""
        errors = []
        for provider in self.providers:
            try:
                return getattr(provider, method)(ticker)
            except ImportError:
                errors.append(f"{provider.name}: library not installed")
            except DataError as exc:
                errors.append(f"{provider.name}: {exc}")
            except Exception as exc:        # a provider that breaks must not stop the chain
                errors.append(f"{provider.name}: {exc.__class__.__name__}: {exc}")
        self.log += [f"{ticker} ({method}): {e}" for e in errors]
        hint = " Install yfinance (`pip install yfinance`) or run with --offline on an existing cache." \
            if any("not installed" in e for e in errors) else ""
        raise DataError(f"No provider returned {method} data for {ticker}. " + " | ".join(errors) + hint)

    # -- last price ---------------------------------------------------------
    def _quotes(self) -> dict:
        file = self.cache / "quotes.json"
        return json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}

    def quote(self, ticker: str) -> Quote:
        if not self.offline:
            q: Quote = self._first("quote", ticker)
            every = self._quotes()
            every[ticker] = {"date": q.date.isoformat(), "price": q.price, "currency": q.currency,
                             "source": q.source}
            self.cache.mkdir(parents=True, exist_ok=True)
            (self.cache / "quotes.json").write_text(json.dumps(every, indent=1, ensure_ascii=False),
                                                    encoding="utf-8")
            return q
        row = self._quotes().get(ticker)
        if row is None:
            raise DataError(f"No price in the cache for {ticker}.")
        return Quote(ticker, date.fromisoformat(row["date"]), float(row["price"]), row["currency"],
                     row["source"])

    # -- monthly history and beta ---------------------------------------------
    def monthly(self, ticker: str) -> list[tuple[date, float]]:
        file = self.cache / f"monthly_{_file_name(ticker)}.csv"
        if not self.offline:
            series = self._first("monthly", ticker)
            self.cache.mkdir(parents=True, exist_ok=True)
            with file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "adj_close"])
                writer.writerows((d.isoformat(), f"{p:.4f}") for d, p in series)
            return series
        if not file.exists():
            raise DataError(f"No monthly history in the cache for {ticker}.")
        with file.open(encoding="utf-8") as f:
            return [(date.fromisoformat(r["date"]), float(r["adj_close"])) for r in csv.DictReader(f)]

    def beta(self, ticker: str, index: str = BENCHMARK) -> tuple[float, int, float]:
        return regression_beta(self.monthly(ticker), self.monthly(index))

    def ten_year_yield(self) -> Quote:
        """10-year Treasury yield from the price providers, as a fraction (0.0486 for 4.86%)."""
        q = self.quote(TEN_YEAR)
        return Quote(q.ticker, q.date, q.price / 100.0, "fraction", q.source)
