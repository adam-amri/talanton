"""Bloomberg Terminal provider ("Terminal edition"). EXPERIMENTAL.

Works only on a computer where a Bloomberg Terminal is running and logged in:
the Desktop API then listens on localhost:8194. Requires Bloomberg's Python
library (`pip install blpapi`, see Bloomberg's "API Library" page).

Activate it with TALANTON_BLOOMBERG=1: Bloomberg is then asked first, and the
free sources remain as fallbacks. This module was written from Bloomberg's API
documentation and could not be run against a real Terminal: test it on yours
and adjust `FIELDS` if a field name differs.

Licence reminder: Bloomberg data is licensed to the Terminal user. Do not
commit it to a public repository (Talanton's cache folder is git-ignored) and
check your institution's rules on automated use of the API.
"""

from __future__ import annotations

from datetime import date

from .base import DataError, Quote

HOST, PORT = "localhost", 8194
SERVICE = "//blp/refdata"
FIELDS = {
    "price": "PX_LAST",
    "currency": "CRNCY",
    "raw_beta": "EQY_RAW_BETA",
    "adjusted_beta": "EQY_BETA",
    "peers": "BLOOMBERG_PEERS",
}


def security(ticker: str) -> str:
    """Talanton ticker -> Bloomberg security ("MAT" -> "MAT US Equity")."""
    if ticker == "^GSPC":
        return "SPX Index"
    if ticker == "^TNX":
        return "USGG10YR Index"
    return ticker if " " in ticker else f"{ticker.replace('-', '/')} US Equity"


class BloombergProvider:
    name = "Bloomberg Terminal"

    def __init__(self, host: str = HOST, port: int = PORT):
        self.host, self.port = host, port
        self._session = None

    # -- session ------------------------------------------------------------
    def _open(self):
        if self._session is not None:
            return self._session
        import blpapi

        options = blpapi.SessionOptions()
        options.setServerHost(self.host)
        options.setServerPort(self.port)
        session = blpapi.Session(options)
        if not session.start():
            raise DataError("Bloomberg: no Terminal session on this computer (is the Terminal open and logged in?).")
        if not session.openService(SERVICE):
            raise DataError(f"Bloomberg: cannot open the service {SERVICE}.")
        self._session = session
        return session

    def _responses(self, request):
        """Sends a request and yields the `securityData` elements of the answer."""
        import blpapi

        session = self._open()
        session.sendRequest(request)
        while True:
            event = session.nextEvent(5000)
            for message in event:
                if message.hasElement("responseError"):
                    raise DataError(f"Bloomberg: {message.getElement('responseError')}")
                if message.hasElement("securityData"):
                    yield message.getElement("securityData")
            if event.eventType() == blpapi.Event.RESPONSE:
                break
            if event.eventType() == blpapi.Event.TIMEOUT:
                raise DataError("Bloomberg: no answer from the Terminal (timeout).")

    def reference(self, ticker: str, fields: list[str]) -> dict:
        """Current value of several fields for one security (the API behind Excel's BDP)."""
        service = self._open().getService(SERVICE)
        request = service.createRequest("ReferenceDataRequest")
        request.append("securities", security(ticker))
        for field in fields:
            request.append("fields", field)
        values: dict = {}
        for block in self._responses(request):
            for i in range(block.numValues()):
                data = block.getValueAsElement(i).getElement("fieldData")
                for field in fields:
                    if data.hasElement(field):
                        element = data.getElement(field)
                        values[field] = element if element.isArray() else element.getValue()
        return values

    # -- provider interface ----------------------------------------------------
    def quote(self, ticker: str) -> Quote:
        values = self.reference(ticker, [FIELDS["price"], FIELDS["currency"]])
        if FIELDS["price"] not in values:
            raise DataError(f"Bloomberg returned no price for {security(ticker)}.")
        currency = "%" if ticker == "^TNX" else str(values.get(FIELDS["currency"], "USD"))
        today = date.today()
        return Quote(ticker, today, float(values[FIELDS["price"]]), currency,
                     f"Bloomberg Terminal ({security(ticker)}, {FIELDS['price']}), {today.isoformat()}")

    def monthly(self, ticker: str) -> list[tuple[date, float]]:
        service = self._open().getService(SERVICE)
        request = service.createRequest("HistoricalDataRequest")
        request.append("securities", security(ticker))
        request.append("fields", FIELDS["price"])
        today = date.today()
        request.set("periodicitySelection", "MONTHLY")
        request.set("startDate", today.replace(year=today.year - 5).strftime("%Y%m%d"))
        request.set("endDate", today.strftime("%Y%m%d"))
        request.set("adjustmentFollowDPDF", True)       # prices adjusted like the Terminal's defaults
        series = []
        for block in self._responses(request):
            rows = block.getElement("fieldData")
            for i in range(rows.numValues()):
                row = rows.getValueAsElement(i)
                d = row.getElementAsDatetime("date")
                series.append((date(d.year, d.month, 1), float(row.getElementAsFloat(FIELDS["price"]))))
        series = [(d, p) for d, p in series if (d.year, d.month) != (today.year, today.month)]
        if not series:
            raise DataError(f"Bloomberg returned no history for {security(ticker)}.")
        return series

    # -- extras ----------------------------------------------------------------
    def beta(self, ticker: str) -> tuple[float | None, float | None]:
        """(raw beta, adjusted beta) as computed by Bloomberg."""
        values = self.reference(ticker, [FIELDS["raw_beta"], FIELDS["adjusted_beta"]])
        return values.get(FIELDS["raw_beta"]), values.get(FIELDS["adjusted_beta"])

    def peers(self, ticker: str) -> list[str]:
        """Bloomberg's peer list, as US tickers."""
        values = self.reference(ticker, [FIELDS["peers"]])
        rows = values.get(FIELDS["peers"])
        if rows is None:
            return []
        tickers = []
        for i in range(rows.numValues()):
            text = str(rows.getValueAsElement(i).getElement(0).getValue())      # e.g. "HAS US"
            parts = text.split()
            if len(parts) >= 2 and parts[1] == "US":
                tickers.append(parts[0].replace("/", "-"))
        return tickers


def bdp(ticker: str, field: str = FIELDS["price"]) -> str:
    """Excel formula text of a live Bloomberg cell (without the leading '=')."""
    return f'_xll.BDP("{security(ticker)}","{field}")'
