import pandas as pd

from openstockagent.pipelines.tushare_daily_batch import run_tushare_daily_batch_sync
from openstockagent.universe.models import UniverseMember


def test_tushare_daily_batch_sync_filters_universe_and_writes_bars_and_daily_basic_factors():
    universe_storage = FakeUniverseStorage(
        [
            UniverseMember("cn_core", "EQUITY:CN:000001", "2026-01-01"),
            UniverseMember("cn_core", "EQUITY:CN:600519", "2026-01-01"),
        ]
    )
    bar_storage = FakeBarStorage()
    factor_storage = FakeFactorStorage()

    result = run_tushare_daily_batch_sync(
        universe_id="cn_core",
        trade_date="2026-05-27",
        reference_feed=FakeTushareReferenceFeed(),
        universe_storage=universe_storage,
        bar_storage=bar_storage,
        factor_storage=factor_storage,
    )

    assert result.members_seen == 2
    assert result.daily_rows_seen == 3
    assert result.daily_basic_rows_seen == 3
    assert result.instruments_matched == 2
    assert result.bars_written == 2
    assert result.factor_values_written == 18
    assert set(bar_storage.frame["instrument_id"]) == {"EQUITY:CN:000001", "EQUITY:CN:600519"}
    assert set(bar_storage.frame["adjustment"]) == {"raw"}
    assert bar_storage.frame.loc[bar_storage.frame["instrument_id"] == "EQUITY:CN:000001", "amount"].iloc[0] == 1000000.0
    assert {definition.factor_name for definition in factor_storage.definitions} == {
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe_ttm",
        "pb",
        "ps_ttm",
        "dv_ttm",
        "total_mv",
        "circ_mv",
    }
    pe_values = [value for value in factor_storage.values if value.factor_name == "pe_ttm"]
    assert all(value.percentile is not None for value in pe_values)


def test_tushare_daily_batch_sync_handles_empty_provider_frames_without_crashing():
    universe_storage = FakeUniverseStorage(
        [
            UniverseMember("cn_core", "EQUITY:CN:000001", "2026-01-01"),
            UniverseMember("cn_core", "EQUITY:CN:600519", "2026-01-01"),
        ]
    )
    bar_storage = FakeBarStorage()
    factor_storage = FakeFactorStorage()

    result = run_tushare_daily_batch_sync(
        universe_id="cn_core",
        trade_date="2026-05-27",
        reference_feed=FakeEmptyTushareReferenceFeed(),
        universe_storage=universe_storage,
        bar_storage=bar_storage,
        factor_storage=factor_storage,
    )

    assert result.members_seen == 2
    assert result.daily_rows_seen == 0
    assert result.daily_basic_rows_seen == 0
    assert result.instruments_matched == 0
    assert result.bars_written == 0
    assert result.factor_values_written == 0
    assert not hasattr(bar_storage, "frame")
    assert factor_storage.values == []


class FakeTushareReferenceFeed:
    def fetch_daily(self, trade_date):
        assert trade_date == "2026-05-27"
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "600519.SH", "000002.SZ"],
                "trade_date": ["20260527", "20260527", "20260527"],
                "open": [10.0, 100.0, 20.0],
                "high": [10.5, 103.0, 21.0],
                "low": [9.8, 99.0, 19.0],
                "close": [10.2, 101.0, 20.5],
                "vol": [1000.0, 2000.0, 3000.0],
                "amount": [1000.0, 2000.0, 3000.0],
            }
        )

    def fetch_daily_basic(self, trade_date):
        assert trade_date == "2026-05-27"
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "600519.SH", "000002.SZ"],
                "trade_date": ["20260527", "20260527", "20260527"],
                "turnover_rate": [1.0, 2.0, 3.0],
                "turnover_rate_f": [1.5, 2.5, 3.5],
                "volume_ratio": [0.8, 1.2, 2.0],
                "pe_ttm": [8.0, 20.0, 30.0],
                "pb": [0.9, 5.0, 2.0],
                "ps_ttm": [1.0, 8.0, 3.0],
                "dv_ttm": [4.0, 1.0, 2.0],
                "total_mv": [100000.0, 2000000.0, 300000.0],
                "circ_mv": [80000.0, 1500000.0, 250000.0],
            }
        )


class FakeEmptyTushareReferenceFeed(FakeTushareReferenceFeed):
    def fetch_daily(self, trade_date):
        assert trade_date == "2026-05-27"
        return pd.DataFrame()

    def fetch_daily_basic(self, trade_date):
        assert trade_date == "2026-05-27"
        return pd.DataFrame()


class FakeUniverseStorage:
    def __init__(self, members):
        self.members = members

    def load_universe_members(self, universe_id, as_of=None):
        assert (universe_id, as_of) == ("cn_core", "2026-05-27")
        return self.members


class FakeBarStorage:
    def upsert_bars(self, frame):
        self.frame = frame
        return len(frame)


class FakeFactorStorage:
    def __init__(self):
        self.values = []

    def upsert_factor_definitions(self, definitions):
        self.definitions = definitions
        return len(definitions)

    def upsert_factor_values(self, values):
        self.values = values
        return len(values)
