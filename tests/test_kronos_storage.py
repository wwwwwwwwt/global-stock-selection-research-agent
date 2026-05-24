import pandas as pd
import pytest

from openstockagent.data.storage import SQLiteStorage
import openstockagent.predictors.kronos_adapter as kronos_adapter
from openstockagent.predictors.kronos_adapter import KronosStockPredictor


def test_load_kronos_frame_returns_sorted_numeric_columns(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
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
