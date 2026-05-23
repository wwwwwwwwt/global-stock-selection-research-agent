import pandas as pd
import pytest
from openstockagent.data.feeds.base import BaseDataFeed
from openstockagent.data.feeds.yahoo import YahooFinanceFeed


class DummyFeed(BaseDataFeed):
    def fetch_ohlcv(self, symbol, period="1y"):
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=3),
            "open": [1.0, 2.0, 3.0],
            "high": [1.5, 2.5, 3.5],
            "low": [0.5, 1.5, 2.5],
            "close": [1.2, 2.2, 3.2],
            "volume": [100, 200, 300],
        }).set_index("date")


def test_base_data_feed_returns_dataframe():
    feed = DummyFeed()
    df = feed.fetch_ohlcv("TEST")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3


def test_yahoo_fetch_aapl():
    feed = YahooFinanceFeed()
    df = feed.fetch_ohlcv("AAPL", period="3mo")
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 30
    required = {"open", "high", "low", "close", "volume"}
    assert required.issubset(set(df.columns))
    assert str(df.index.dtype).startswith("datetime64")
