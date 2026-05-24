import pandas as pd

from openstockagent.data.normalize import normalize_bars
from openstockagent.data.validate import validate_bars


def test_normalize_bars_adds_canonical_metadata():
    raw = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T21:00:00Z"],
            "open": [100.0],
            "high": [103.0],
            "low": [99.0],
            "close": [102.0],
            "volume": [1000.0],
        }
    )
    normalized = normalize_bars(
        raw,
        instrument_id="EQUITY:US:AAPL",
        interval="1d",
        source="csv",
        adjustment="split_adjusted",
        currency="USD",
    )

    assert normalized.iloc[0]["instrument_id"] == "EQUITY:US:AAPL"
    assert normalized.iloc[0]["amount"] == 101000.0
    assert normalized.iloc[0]["local_date"] == "2024-01-02"
    assert normalized.iloc[0]["is_complete"] == 1


def test_validate_bars_detects_invalid_ohlc():
    invalid = pd.DataFrame(
        {
            "instrument_id": ["EQUITY:US:AAPL"],
            "timestamp": ["2024-01-02T21:00:00Z"],
            "local_date": ["2024-01-02"],
            "interval": ["1d"],
            "source": ["csv"],
            "adjustment": ["split_adjusted"],
            "open": [100.0],
            "high": [98.0],
            "low": [99.0],
            "close": [102.0],
            "volume": [1000.0],
            "amount": [101000.0],
            "currency": ["USD"],
            "is_complete": [1],
        }
    )

    issues = validate_bars(invalid)
    assert issues[0]["issue_type"] == "invalid_ohlc"
    assert issues[0]["severity"] == "error"
