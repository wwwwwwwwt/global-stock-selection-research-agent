from pathlib import Path

from openstockagent.data.feeds.csv_feed import CsvFeed
from openstockagent.data.feeds.registry import FeedRegistry
from openstockagent.data.symbols import infer_instrument


def test_infer_us_instrument():
    instrument, alias = infer_instrument("AAPL", source="yahoo")
    assert instrument.instrument_id == "EQUITY:US:AAPL"
    assert alias.source_symbol == "AAPL"


def test_infer_hk_instrument():
    instrument, alias = infer_instrument("9988.HK", source="yahoo")
    assert instrument.instrument_id == "EQUITY:HK:09988"
    assert instrument.market == "HK"


def test_registry_returns_configured_feed():
    registry = FeedRegistry()
    csv_feed = CsvFeed(Path("tests/fixtures/sample_bars.csv"))
    registry.register("US", "equity", "1d", csv_feed)

    feed = registry.resolve(market="US", asset_type="equity", interval="1d")
    assert feed.source == "csv"


def test_registry_normalizes_lookup_keys():
    registry = FeedRegistry()
    csv_feed = CsvFeed(Path("tests/fixtures/sample_bars.csv"))
    registry.register("us", "Equity", "1D", csv_feed)

    feed = registry.resolve(market="US", asset_type="equity", interval="1d")
    assert feed.source == "csv"
