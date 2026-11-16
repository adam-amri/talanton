"""Sector references published by Aswath Damodaran (NYU Stern): betas and EV multiples.

A snapshot of the US tables ships with Talanton (`reference/damodaran_us.csv`),
so the sector cross-checks work offline. `refresh` downloads the current HTML
tables and stores them in the cache, which then takes precedence. Damodaran
updates these tables once a year, in January.

Used for two things:
  - a sector beta, re-levered at the company's own debt/equity ratio, when the
    regression beta is unreliable;
  - a sector EV/EBITDA, shown next to the comparables as a sanity check.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .base import DataError, http_get

URL_BETAS = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html"
URL_MULTIPLES = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html"
BUNDLED = Path(__file__).parent / "reference" / "damodaran_us.csv"
BUNDLED_AS_OF = "January 2026"
COLUMNS = ("industry", "firms", "beta", "debt_to_equity", "effective_tax_rate", "unlevered_beta",
           "cash_to_firm_value", "unlevered_beta_cash_corrected", "ev_ebitda", "ev_ebit")

# SIC code (or prefix) -> Damodaran industry. Best-effort and deliberately short:
# when a code is missing, choose the industry yourself (`industry = "..."` in the config).
SIC_TO_INDUSTRY = {
    "1311": "Oil/Gas (Production and Exploration)", "1531": "Homebuilding", "2086": "Beverage (Soft)",
    "2082": "Beverage (Alcoholic)", "2111": "Tobacco", "20": "Food Processing", "23": "Apparel",
    "26": "Paper/Forest Products", "2711": "Publishing & Newspapers", "2721": "Publishing & Newspapers",
    "2731": "Publishing & Newspapers", "2834": "Drugs (Pharmaceutical)", "2836": "Drugs (Biotechnology)",
    "284": "Household Products", "2911": "Oil/Gas (Integrated)", "3021": "Shoe", "314": "Shoe",
    "3312": "Steel", "3571": "Computers/Peripherals", "3572": "Computers/Peripherals",
    "3674": "Semiconductor", "3711": "Auto & Truck", "3714": "Auto Parts", "372": "Aerospace/Defense",
    "376": "Aerospace/Defense", "3841": "Healthcare Products", "3845": "Healthcare Products",
    "394": "Recreation", "4011": "Transportation (Railroads)", "4213": "Trucking", "4512": "Air Transport",
    "4812": "Telecom (Wireless)", "4813": "Telecom. Services", "4833": "Broadcasting", "4841": "Cable TV",
    "4941": "Utility (Water)", "5211": "Retail (Building Supply)", "5311": "Retail (General)",
    "5331": "Retail (General)", "5411": "Retail (Grocery and Food)", "5812": "Restaurant/Dining",
    "7011": "Hotel/Gaming", "7311": "Advertising", "7372": "Software (System & Application)",
    "7812": "Entertainment", "8062": "Hospitals/Healthcare Facilities", "82": "Education",
}


@dataclass(frozen=True)
class Industry:
    name: str
    firms: int
    beta: float | None
    debt_to_equity: float | None
    effective_tax_rate: float | None
    unlevered_beta: float | None
    cash_to_firm_value: float | None
    unlevered_beta_cash_corrected: float | None
    ev_ebitda: float | None
    ev_ebit: float | None
    as_of: str = BUNDLED_AS_OF

    @property
    def source(self) -> str:
        return f"A. Damodaran (NYU Stern), US industry '{self.name}', {self.firms} firms, data as of {self.as_of}"


def relever(unlevered_beta: float, debt_to_equity: float, tax_rate: float) -> float:
    """Hamada: levered beta = unlevered beta x (1 + (1 - tax) x D/E)."""
    return unlevered_beta * (1 + (1 - tax_rate) * max(0.0, debt_to_equity))


def _number(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def _read_csv(file: Path) -> dict[str, Industry]:
    lines = file.read_text(encoding="utf-8").splitlines()
    as_of = BUNDLED_AS_OF
    for line in lines:
        match = re.search(r"as of ([A-Z][a-z]+ \d{4})", line) if line.startswith("#") else None
        if match:
            as_of = match.group(1)
    table: dict[str, Industry] = {}
    for row in csv.DictReader(line for line in lines if not line.startswith("#")):
        table[row["industry"]] = Industry(
            row["industry"], int(row["firms"]), *(_number(row[c]) for c in COLUMNS[2:]), as_of=as_of)
    return table


def load_industries(cache: Path | None = None) -> dict[str, Industry]:
    """Industry table: the refreshed copy in the cache if there is one, else the bundled snapshot."""
    refreshed = Path(cache) / "damodaran" / "damodaran_us.csv" if cache else None
    return _read_csv(refreshed if refreshed and refreshed.exists() else BUNDLED)


def industry_for_sic(sic: str, table: dict[str, Industry]) -> Industry | None:
    """Longest matching SIC prefix wins (four digits, then three, then two)."""
    for length in (4, 3, 2):
        name = SIC_TO_INDUSTRY.get(sic[:length]) if len(sic) >= length else None
        if name and name in table:
            return table[name]
    return None


# -- online refresh -----------------------------------------------------------
class _Table(HTMLParser):
    """Collects the rows of every table of a page as lists of cell texts."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_page(text: str) -> tuple[list[str], list[list[str]], str]:
    """Returns (header row, data rows, "as of" text) of a Damodaran HTML table."""
    parser = _Table()
    parser.feed(text)
    start = next((i for i, r in enumerate(parser.rows) if r and r[0] == "Industry Name"), None)
    if start is None:
        raise DataError("Damodaran page: table header 'Industry Name' not found (layout changed?).")
    match = re.search(r"as of\s+([A-Z][a-z]+\s+\d{4})", " ".join(text.split()))
    data = [r for r in parser.rows[start + 1:] if r and r[0]]
    return parser.rows[start], data, " ".join(match.group(1).split()) if match else "unknown date"


def _ratio(text: str) -> str:
    text = text.strip()
    if text in ("", "NA"):
        return ""
    return f"{float(text.rstrip('%')) / 100:.4f}" if text.endswith("%") else text


def refresh(cache: Path) -> dict[str, Industry]:
    """Downloads both tables, merges them by industry and stores the result in the cache."""
    headers = {"User-Agent": "Mozilla/5.0 (Talanton, educational use)"}
    pages = {}
    for key, url in (("betas", URL_BETAS), ("multiples", URL_MULTIPLES)):
        raw = http_get(url, headers=headers, what=f"Damodaran ({key})").content
        pages[key] = parse_page(raw.decode("cp1252", errors="replace"))
    head_b, rows_b, as_of = pages["betas"]
    head_m, rows_m, _ = pages["multiples"]
    wanted = {"beta": "Beta", "debt_to_equity": "D/E Ratio", "effective_tax_rate": "Effective Tax rate",
              "unlevered_beta": "Unlevered beta", "cash_to_firm_value": "Cash/Firm value",
              "unlevered_beta_cash_corrected": "Unlevered beta corrected for cash"}
    try:
        at = {k: head_b.index(v) for k, v in wanted.items()}
        firms_at = head_b.index("Number of firms")
        ev_ebitda_at, ev_ebit_at = head_m.index("EV/EBITDA"), head_m.index("EV/EBIT")   # first block: positive EBITDA
    except ValueError as exc:
        raise DataError(f"Damodaran page: expected column missing ({exc}).") from exc
    multiples = {r[0]: r for r in rows_m}
    file = Path(cache) / "damodaran" / "damodaran_us.csv"
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("w", newline="", encoding="utf-8") as f:
        f.write(f"# Source: Aswath Damodaran (NYU Stern), US sector tables. Data as of {as_of}.\n")
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for r in rows_b:
            m = multiples.get(r[0], [])
            writer.writerow([r[0], r[firms_at]] + [_ratio(r[at[c]]) for c in COLUMNS[2:8]]
                            + [_ratio(m[ev_ebitda_at]) if len(m) > ev_ebitda_at else "",
                               _ratio(m[ev_ebit_at]) if len(m) > ev_ebit_at else ""])
    return _read_csv(file)
