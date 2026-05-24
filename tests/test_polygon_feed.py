import pandas as pd
import pytest

from openstockagent.data.feeds.polygon import PolygonStockFeed


def test_polygon_feed_normalizes_aggregate_bars():
    client = FakePolygonClient(
        {
            "status": "OK",
            "results": [
                {"t": 1704153600000, "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.5, "v": 1000.0, "vw": 101.0},
                {"t": 1704240000000, "o": 101.0, "h": 103.0, "l": 100.0, "c": 102.5, "v": 1200.0, "vw": 102.0},
            ],
        }
    )
    feed = PolygonStockFeed(api_key="test-key", client=client)

    bars = feed.fetch_bars("AAPL", interval="1d", end="2024-01-03", period="5d")

    assert client.calls == [
        {
            "ticker": "AAPL",
            "multiplier": 1,
            "timespan": "day",
            "from_date": "2023-12-29",
            "to_date": "2024-01-03",
            "adjusted": True,
        }
    ]
    assert list(bars.columns) == ["timestamp", "open", "high", "low", "close", "volume", "amount"]
    assert list(bars["close"]) == [101.5, 102.5]
    assert bars.iloc[0]["timestamp"] == "2024-01-02T00:00:00Z"
    assert bars.iloc[0]["amount"] == pytest.approx(101000.0)


def test_polygon_feed_requires_api_key():
    with pytest.raises(ValueError, match="POLYGON_API_KEY"):
        PolygonStockFeed(api_key="")


class FakePolygonClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_aggregates(self, ticker, multiplier, timespan, from_date, to_date, adjusted):
        self.calls.append(
            {
                "ticker": ticker,
                "multiplier": multiplier,
                "timespan": timespan,
                "from_date": from_date,
                "to_date": to_date,
                "adjusted": adjusted,
            }
        )
        return self.payload
