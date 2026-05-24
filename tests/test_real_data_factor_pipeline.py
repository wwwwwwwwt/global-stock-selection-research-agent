import pandas as pd

from openstockagent.data.storage import SQLiteStorage
from openstockagent.data.symbols import to_source_symbol
from openstockagent.data.feeds.registry import FeedRegistry
from openstockagent.pipelines.real_data_factors import run_real_data_factor_pipeline
from openstockagent.universe.models import UniverseMember


def test_to_source_symbol_maps_instrument_ids_to_source_symbols():
    assert to_source_symbol("EQUITY:US:AAPL", source="yahoo") == "AAPL"
    assert to_source_symbol("EQUITY:US:AAPL", source="polygon") == "AAPL"
    assert to_source_symbol("EQUITY:CN:600519", source="akshare") == "600519"
    assert to_source_symbol("EQUITY:CN:000001", source="akshare") == "000001"
    assert to_source_symbol("EQUITY:HK:09988", source="yahoo") == "9988.HK"


def test_real_data_factor_pipeline_routes_market_feeds_and_writes_factor_values(temp_db_path):
    bar_storage = SQLiteStorage(temp_db_path)
    universe_storage = FakeUniverseStorage(
        [
            UniverseMember("cn_sample", "EQUITY:CN:600519", "2024-01-01"),
            UniverseMember("cn_sample", "EQUITY:US:AAPL", "2024-01-01"),
        ]
    )
    factor_storage = FakeFactorStorage()
    akshare_feed = FakeFeed("akshare")
    yahoo_feed = FakeFeed("yahoo")
    feed_registry = FeedRegistry()
    feed_registry.register("CN", "equity", "1d", akshare_feed)
    feed_registry.register("US", "equity", "1d", yahoo_feed)

    result = run_real_data_factor_pipeline(
        universe_id="cn_sample",
        as_of="2024-04-05",
        interval="1d",
        period="6mo",
        feed_registry=feed_registry,
        universe_storage=universe_storage,
        bar_storage=bar_storage,
        factor_storage=factor_storage,
    )

    assert akshare_feed.calls == [("600519", "1d", "6mo")]
    assert yahoo_feed.calls == [("AAPL", "1d", "6mo")]
    assert result.members_seen == 2
    assert result.instruments_fetched == 2
    assert result.bars_written == 140
    assert result.factor_values_written == 18
    assert len(factor_storage.definitions) == 9
    assert len(factor_storage.values) == 18
    stored = bar_storage.load_bars("EQUITY:CN:600519", "1d", "2024-01-01T00:00:00Z", "2024-04-30T00:00:00Z")
    assert len(stored) == 70
    assert {value.factor_name for value in factor_storage.values} >= {"return_5d", "turnover_amount_20d"}
    assert all(value.percentile is not None for value in factor_storage.values)


def test_real_data_factor_pipeline_records_symbol_failures_without_aborting(temp_db_path):
    bar_storage = SQLiteStorage(temp_db_path)
    universe_storage = FakeUniverseStorage(
        [
            UniverseMember("cn_sample", "EQUITY:CN:600519", "2024-01-01"),
            UniverseMember("cn_sample", "EQUITY:CN:000001", "2024-01-01"),
        ]
    )
    factor_storage = FakeFactorStorage()
    feed = PartiallyFailingFeed("akshare")
    feed_registry = FeedRegistry()
    feed_registry.register("CN", "equity", "1d", feed)

    result = run_real_data_factor_pipeline(
        universe_id="cn_sample",
        as_of="2024-04-05",
        interval="1d",
        period="6mo",
        feed_registry=feed_registry,
        universe_storage=universe_storage,
        bar_storage=bar_storage,
        factor_storage=factor_storage,
    )

    assert result.instruments_fetched == 1
    assert result.failed_instruments == 1
    assert result.errors == ["000001: rate limited"]
    assert result.factor_values_written == 9


class FakeUniverseStorage:
    def __init__(self, members):
        self.members = members
        self.calls = []

    def load_universe_members(self, universe_id, as_of=None):
        self.calls.append((universe_id, as_of))
        return self.members


class FakeFactorStorage:
    def __init__(self):
        self.definitions = []
        self.values = []

    def upsert_factor_definitions(self, definitions):
        self.definitions = definitions
        return len(definitions)

    def upsert_factor_values(self, values):
        self.values = values
        return len(values)


class FakeFeed:
    def __init__(self, source):
        self.source = source
        self.calls = []

    def fetch_bars(self, source_symbol, interval, start=None, end=None, period=None, adjusted=True):
        self.calls.append((source_symbol, interval, period))
        frame = _sample_feed_bars(periods=70)
        if source_symbol == "000001":
            frame["close"] = frame["close"] * 0.92
        return frame


class PartiallyFailingFeed(FakeFeed):
    def fetch_bars(self, source_symbol, interval, start=None, end=None, period=None, adjusted=True):
        if source_symbol == "000001":
            raise RuntimeError("rate limited")
        return super().fetch_bars(source_symbol, interval, start=start, end=end, period=period, adjusted=adjusted)


def _sample_feed_bars(periods: int) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=periods)
    close = pd.Series([100.0 + i for i in range(periods)])
    volume = pd.Series([1000.0 + i * 10 for i in range(periods)])
    return pd.DataFrame(
        {
            "timestamp": dates.strftime("%Y-%m-%dT00:00:00Z"),
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": volume,
            "amount": close * volume,
        }
    )
