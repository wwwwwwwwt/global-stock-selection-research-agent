import pandas as pd
import pytest

from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.database.mysql import MySQLConfig
import openstockagent.predictors.kronos_adapter as kronos_adapter
from openstockagent.predictors.kronos_adapter import KronosStockPredictor


def test_load_kronos_frame_returns_sorted_numeric_columns():
    factory = FakeConnectionFactory(
        fetchall_rows=[
            [
                {
                    "timestamp": "2024-01-04T21:00:00Z",
                    "open": 103.5,
                    "high": 105.0,
                    "low": 102.0,
                    "close": 104.0,
                    "volume": 1100.0,
                    "amount": 114400.0,
                },
                {
                    "timestamp": "2024-01-03T21:00:00Z",
                    "open": 102.0,
                    "high": 104.0,
                    "low": 101.0,
                    "close": 103.5,
                    "volume": 1200.0,
                    "amount": 123000.0,
                },
            ]
        ]
    )
    storage = MySQLMarketDataStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
    )
    df = pd.DataFrame(
        {
            "instrument_id": ["EQUITY:US:AAPL"] * 3,
            "timestamp": ["2024-01-03T21:00:00Z", "2024-01-02T21:00:00Z", "2024-01-04T21:00:00Z"],
            "local_date": ["2024-01-03", "2024-01-02", "2024-01-04"],
            "interval": ["1d"] * 3,
            "source": ["csv"] * 3,
            "adjustment": ["split_adjusted"] * 3,
            "open": [102.0, 100.0, 103.5],
            "high": [104.0, 103.0, 105.0],
            "low": [101.0, 99.0, 102.0],
            "close": [103.5, 102.0, 104.0],
            "volume": [1200.0, 1000.0, 1100.0],
            "amount": [123000.0, 101000.0, 114400.0],
            "currency": ["USD"] * 3,
            "is_complete": [1, 1, 1],
        }
    )
    storage.upsert_bars(df)

    frame = storage.load_kronos_frame("EQUITY:US:AAPL", "1d", lookback=2)

    assert list(frame.columns) == ["open", "high", "low", "close", "volume", "amount"]
    assert list(frame["close"]) == [103.5, 104.0]
    assert str(frame.index[0]) == "2024-01-03 21:00:00+00:00"


def test_kronos_adapter_keeps_amount_when_present():
    predictor = KronosStockPredictor.__new__(KronosStockPredictor)
    predictor.variant = "mini"
    predictor.device = "cpu"
    predictor.predictor = _RecordingPredictor()
    frame = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000.0, 1200.0],
            "amount": [101000.0, 122400.0],
        },
        index=pd.date_range("2024-01-01", periods=2, freq="B"),
    )

    predictor.predict("AAPL", frame, horizon=1)

    assert list(predictor.predictor.seen_columns) == ["open", "high", "low", "close", "volume", "amount"]


def test_kronos_adapter_reports_missing_required_columns():
    predictor = KronosStockPredictor.__new__(KronosStockPredictor)
    predictor.variant = "mini"
    predictor.device = "cpu"
    predictor.predictor = _RecordingPredictor()
    frame = pd.DataFrame(
        {
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
        },
        index=pd.date_range("2024-01-01", periods=1, freq="B"),
    )

    with pytest.raises(ValueError, match="missing required columns"):
        predictor.predict("AAPL", frame, horizon=1)


def test_kronos_model_resolver_uses_env_model_dir(tmp_path, monkeypatch):
    model_dir = tmp_path / "kronos-base"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"weights")
    monkeypatch.setenv("OPENSTOCKAGENT_MODELS_DIR", str(tmp_path))

    resolved = kronos_adapter._resolve_model_path("NeoQuasar/Kronos-base", "kronos-base")

    assert resolved == str(model_dir)


def test_kronos_model_resolver_ignores_incomplete_local_model(tmp_path, monkeypatch):
    model_dir = tmp_path / "kronos-base"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(kronos_adapter, "LOCAL_MODELS_DIR", tmp_path)
    monkeypatch.delenv("OPENSTOCKAGENT_MODELS_DIR", raising=False)

    resolved = kronos_adapter._resolve_model_path("NeoQuasar/Kronos-base", "kronos-base")

    assert resolved == "NeoQuasar/Kronos-base"


class _RecordingPredictor:
    def predict(self, df, **kwargs):
        self.seen_columns = df.columns
        return pd.DataFrame(
            {
                "open": [102.0],
                "high": [103.0],
                "low": [101.0],
                "close": [102.5],
                "volume": [1300.0],
                "amount": [133250.0],
            }
        )


class FakeConnectionFactory:
    def __init__(self, fetchall_rows=None):
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

    def fetchall(self):
        return self.factory.fetchall_rows.pop(0) if self.factory.fetchall_rows else []
