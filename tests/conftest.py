"""Test data: real accounts and market data recorded in examples/cache.

The files of examples/cache/sec follow the exact structure of the SEC APIs
(extracts reduced to the fields Talanton reads). No test needs the network.
"""

from pathlib import Path

import pytest

from talanton.data import EdgarClient, FredClient, MarketData
from talanton.engine import collect, compute

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "examples" / "cache"
ADJUSTMENTS = ROOT / "examples" / "adjustments" / "MAT.toml"
CONFIG = ROOT / "examples" / "configs" / "MAT.toml"
PEERS = ["HAS", "FNKO", "JAKK", "YETI", "GOLF"]


@pytest.fixture(scope="session")
def edgar() -> EdgarClient:
    return EdgarClient(CACHE, offline=True)


@pytest.fixture(scope="session")
def market() -> MarketData:
    return MarketData(CACHE, offline=True)


@pytest.fixture(scope="session")
def fred() -> FredClient:
    return FredClient(CACHE, offline=True)


@pytest.fixture(scope="session")
def inputs():
    return collect("MAT", PEERS, CACHE, True, ADJUSTMENTS, log=lambda *a: None)


@pytest.fixture(scope="session")
def result(inputs):
    return compute(inputs)
