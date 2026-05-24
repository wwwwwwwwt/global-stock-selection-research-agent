import pandas as pd
import pytest

from openstockagent.data.feeds.yahoo import YahooFinanceFeed


def test_yahoo_feed_normalizes_history_to_canonical_bars():
    calls = []

    def ticker_factory(symbol):
        calls.append(symbol)
        return _FakeTicker()

    feed = YahooFinanceFeed(ticker_factory=ticker_factory, timeout=7, repair=True)

    bars = feed.fetch_bars("AAPL", interval="1d", period="5d", adjusted=True)

    assert calls == ["AAPL"]
    assert list(bars.columns) == ["timestamp", "open", "high", "low", "close", "volume", "amount"]
    assert list(bars["close"]) == [101.5, 102.5]
    assert bars.iloc[0]["timestamp"] == "2024-01-02T00:00:00Z"
    assert _FakeTicker.last_kwargs == {
        "interval": "1d",
        "period": "5d",
        "auto_adjust": True,
        "repair": True,
        "timeout": 7,
        "raise_errors": True,
    }


def test_yahoo_feed_requires_period_or_start_end():
    feed = YahooFinanceFeed(ticker_factory=lambda symbol: _FakeTicker())

    with pytest.raises(ValueError, match="period or both start and end"):
        feed.fetch_bars("AAPL", interval="1d")


class _FakeTicker:
    last_kwargs = {}

    def history(self, **kwargs):
        type(self).last_kwargs = kwargs
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [102.0, 103.0],
                "Low": [99.0, 100.0],
                "Close": [101.5, 102.5],
                "Volume": [1000.0, 1200.0],
            },
            index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
        )
