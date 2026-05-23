import pandas as pd
from openstockagent.data.storage import SQLiteStorage


def test_save_and_load_ohlcv(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    df = pd.DataFrame({
        "open": [1.0, 2.0],
        "high": [1.5, 2.5],
        "low": [0.5, 1.5],
        "close": [1.2, 2.2],
        "volume": [100, 200],
    }, index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    df.index.name = "date"

    storage.save_ohlcv("TEST", df)
    loaded = storage.load_ohlcv("TEST")

    assert len(loaded) == 2
    assert loaded["close"].iloc[-1] == 2.2


def test_load_empty_returns_empty_df(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    loaded = storage.load_ohlcv("UNKNOWN")
    assert loaded.empty
    assert list(loaded.columns) == ["open", "high", "low", "close", "volume"]
