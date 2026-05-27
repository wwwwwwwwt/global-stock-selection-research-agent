import json

import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias, PredictionRun, TechnicalSignal
from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.database.mysql import MySQLConfig


MYSQL_CONFIG = MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456")


def test_mysql_market_storage_creates_core_canonical_tables_and_resolves_alias():
    factory = FakeConnectionFactory(fetchone_rows=[{"instrument_id": "EQUITY:US:AAPL"}])
    storage = MySQLMarketDataStorage(config=MYSQL_CONFIG, connection_factory=factory)
    instrument = Instrument(
        instrument_id="EQUITY:US:AAPL",
        symbol="AAPL",
        market="US",
        exchange="NASDAQ",
        asset_type="equity",
        currency="USD",
        name="Apple Inc.",
        timezone="America/New_York",
    )
    alias = InstrumentAlias("EQUITY:US:AAPL", "polygon", "AAPL")

    storage.upsert_instrument(instrument)
    storage.upsert_instrument_alias(alias)

    assert storage.resolve_alias("polygon", "AAPL") == "EQUITY:US:AAPL"
    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS instruments" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS instrument_aliases" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS bars" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS feed_runs" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS data_quality_issues" in executed_sql
    assert "bar_interval VARCHAR(16) NOT NULL" in executed_sql
    assert "bar_timestamp VARCHAR(64) NOT NULL" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql


def test_mysql_market_storage_bulk_upserts_instruments_and_aliases():
    factory = FakeConnectionFactory()
    storage = MySQLMarketDataStorage(config=MYSQL_CONFIG, connection_factory=factory)
    instruments = [
        Instrument("EQUITY:CN:000001", "000001", "CN", "SZSE", "equity", "CNY", "平安银行", "Asia/Shanghai"),
        Instrument("EQUITY:CN:600519", "600519", "CN", "SSE", "equity", "CNY", "贵州茅台", "Asia/Shanghai"),
    ]
    aliases = [
        InstrumentAlias("EQUITY:CN:000001", "tushare", "000001.SZ"),
        InstrumentAlias("EQUITY:CN:600519", "tushare", "600519.SH"),
    ]

    assert storage.upsert_instruments(instruments) == 2
    assert storage.upsert_instrument_aliases(aliases) == 2

    executed_sql = "\n".join(factory.executed_sql)
    assert "INSERT INTO instruments" in executed_sql
    assert "INSERT INTO instrument_aliases" in executed_sql
    assert factory.executed_params[-1]["source_symbol"] == "600519.SH"


def test_mysql_market_storage_upserts_and_loads_canonical_bars():
    factory = FakeConnectionFactory(
        fetchall_rows=[
            [
                {
                    "instrument_id": "EQUITY:US:AAPL",
                    "timestamp": "2024-01-02T21:00:00Z",
                    "local_date": "2024-01-02",
                    "interval": "1d",
                    "source": "csv",
                    "adjustment": "split_adjusted",
                    "open": 100.0,
                    "high": 103.0,
                    "low": 99.0,
                    "close": 102.0,
                    "volume": 1000.0,
                    "amount": 101000.0,
                    "currency": "USD",
                    "is_complete": 1,
                    "provider_payload_hash": None,
                },
                {
                    "instrument_id": "EQUITY:US:AAPL",
                    "timestamp": "2024-01-03T21:00:00Z",
                    "local_date": "2024-01-03",
                    "interval": "1d",
                    "source": "csv",
                    "adjustment": "split_adjusted",
                    "open": 102.0,
                    "high": 104.0,
                    "low": 101.0,
                    "close": 103.5,
                    "volume": 1200.0,
                    "amount": 123000.0,
                    "currency": "USD",
                    "is_complete": 1,
                    "provider_payload_hash": None,
                },
            ]
        ]
    )
    storage = MySQLMarketDataStorage(config=MYSQL_CONFIG, connection_factory=factory)
    df = pd.DataFrame(
        {
            "instrument_id": ["EQUITY:US:AAPL", "EQUITY:US:AAPL"],
            "timestamp": ["2024-01-02T21:00:00Z", "2024-01-03T21:00:00Z"],
            "local_date": ["2024-01-02", "2024-01-03"],
            "interval": ["1d", "1d"],
            "source": ["csv", "csv"],
            "adjustment": ["split_adjusted", "split_adjusted"],
            "open": [100.0, 102.0],
            "high": [103.0, 104.0],
            "low": [99.0, 101.0],
            "close": [102.0, 103.5],
            "volume": [1000.0, 1200.0],
            "amount": [101000.0, 123000.0],
            "currency": ["USD", "USD"],
            "is_complete": [1, 1],
        }
    )

    assert storage.upsert_bars(df) == 2
    loaded = storage.load_bars("EQUITY:US:AAPL", "1d", "2024-01-01T00:00:00Z", "2024-01-04T00:00:00Z")

    assert list(loaded["close"]) == [102.0, 103.5]
    assert loaded.iloc[0]["source"] == "csv"
    assert factory.executed_params[-1] == [
        "EQUITY:US:AAPL",
        "1d",
        "2024-01-01T00:00:00Z",
        "2024-01-04T00:00:00Z",
    ]


def test_mysql_market_storage_saves_prediction_summary():
    factory = FakeConnectionFactory(
        fetchone_rows=[
            {
                "run_id": "pred_1",
                "model_name": "kronos",
                "model_variant": "small",
                "horizon": 2,
                "created_at": "2024-01-31T00:00:00Z",
            }
        ],
        fetchall_rows=[[{"close": 105.5}, {"close": 106.5}]],
    )
    storage = MySQLMarketDataStorage(config=MYSQL_CONFIG, connection_factory=factory)
    run = PredictionRun(
        run_id="pred_1",
        model_name="kronos",
        model_variant="small",
        instrument_id="EQUITY:US:AAPL",
        interval="1d",
        lookback_start="2024-01-01T21:00:00Z",
        lookback_end="2024-01-31T21:00:00Z",
        horizon=2,
        source_selection_json=json.dumps({"source": "csv"}),
    )
    predicted = pd.DataFrame(
        {
            "forecast_timestamp": ["2024-02-01T21:00:00Z", "2024-02-02T21:00:00Z"],
            "step": [1, 2],
            "open": [104.0, 105.0],
            "high": [106.0, 107.0],
            "low": [103.0, 104.0],
            "close": [105.5, 106.5],
            "volume": [1300.0, 1400.0],
            "amount": [136500.0, 149100.0],
            "confidence": [0.7, 0.68],
        }
    )

    storage.save_prediction_run(run, predicted)
    loaded = storage.load_latest_prediction_summary("EQUITY:US:AAPL", "1d")

    assert loaded["run_id"] == "pred_1"
    assert loaded["horizon"] == 2
    assert loaded["forecast_close_max"] == 106.5


def test_mysql_market_storage_saves_technical_signal():
    factory = FakeConnectionFactory(
        fetchall_rows=[
            [
                {
                    "signal_id": "sig_1",
                    "instrument_id": "EQUITY:US:AAPL",
                    "timestamp": "2024-01-31T21:00:00Z",
                    "interval": "1d",
                    "signal_type": "golden_cross",
                    "direction": "bullish",
                    "strength": 0.75,
                    "confidence": 0.8,
                    "severity": "watch",
                    "summary": "MA5 crossed above MA20.",
                    "evidence_json": '{"fast": 101.0, "slow": 100.0}',
                    "input_range_start": "2024-01-01T21:00:00Z",
                    "input_range_end": "2024-01-31T21:00:00Z",
                    "created_at": "2024-01-31T21:00:00Z",
                }
            ]
        ]
    )
    storage = MySQLMarketDataStorage(config=MYSQL_CONFIG, connection_factory=factory)
    signal = TechnicalSignal(
        signal_id="sig_1",
        instrument_id="EQUITY:US:AAPL",
        timestamp="2024-01-31T21:00:00Z",
        interval="1d",
        signal_type="golden_cross",
        direction="bullish",
        strength=0.75,
        confidence=0.8,
        severity="watch",
        summary="MA5 crossed above MA20.",
        evidence_json='{"fast": 101.0, "slow": 100.0}',
        input_range_start="2024-01-01T21:00:00Z",
        input_range_end="2024-01-31T21:00:00Z",
    )

    assert storage.save_technical_signals([signal]) == 1
    loaded = storage.load_recent_technical_signals("EQUITY:US:AAPL", "1d", limit=5)
    assert loaded[0]["signal_type"] == "golden_cross"


class FakeConnectionFactory:
    def __init__(self, fetchone_rows=None, fetchall_rows=None):
        self.fetchone_rows = list(fetchone_rows or [])
        self.fetchall_rows = list(fetchall_rows or [])
        self.executed_sql = []
        self.executed_params = []

    def __call__(self, config):
        self.config = config
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, factory):
        self.factory = factory

    def cursor(self):
        return FakeCursor(self.factory)

    def commit(self):
        pass

    def close(self):
        pass


class FakeCursor:
    def __init__(self, factory):
        self.factory = factory

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        pass

    def execute(self, sql, params=None):
        self.factory.executed_sql.append(sql)
        self.factory.executed_params.append(params)
        return 1

    def executemany(self, sql, params):
        self.factory.executed_sql.append(sql)
        self.factory.executed_params.extend(params)
        return len(params)

    def fetchone(self):
        return self.factory.fetchone_rows.pop(0) if self.factory.fetchone_rows else None

    def fetchall(self):
        return self.factory.fetchall_rows.pop(0) if self.factory.fetchall_rows else []
