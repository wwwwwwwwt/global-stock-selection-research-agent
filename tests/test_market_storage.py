import json

import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias, PredictionRun, TechnicalSignal
from openstockagent.data.storage import SQLiteStorage


def test_upsert_instrument_and_alias(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
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
    alias = InstrumentAlias("EQUITY:US:AAPL", "yahoo", "AAPL")

    storage.upsert_instrument(instrument)
    storage.upsert_instrument_alias(alias)

    assert storage.resolve_alias("yahoo", "AAPL") == "EQUITY:US:AAPL"


def test_upsert_and_load_bars(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
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
    assert storage.upsert_bars(df) == 2

    loaded = storage.load_bars("EQUITY:US:AAPL", "1d", "2024-01-01T00:00:00Z", "2024-01-04T00:00:00Z")
    assert list(loaded["close"]) == [102.0, 103.5]
    assert loaded.iloc[0]["source"] == "csv"


def test_save_prediction_run_and_predicted_bars(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
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


def test_save_technical_signal(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
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
