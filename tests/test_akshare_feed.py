import pandas as pd

from openstockagent.data.feeds.akshare import AkShareAStockFeed


def test_akshare_feed_normalizes_a_share_hist_columns():
    client = FakeAkShareClient()
    feed = AkShareAStockFeed(client=client)

    bars = feed.fetch_bars("600519", interval="1d", start="2024-01-01", end="2024-01-03")

    assert client.calls == [
        {
            "symbol": "600519",
            "period": "daily",
            "start_date": "20240101",
            "end_date": "20240103",
            "adjust": "qfq",
        }
    ]
    assert list(bars.columns) == ["timestamp", "open", "high", "low", "close", "volume", "amount"]
    assert bars.iloc[0]["timestamp"] == "2024-01-02T00:00:00Z"
    assert list(bars["close"]) == [101.5, 102.5]


def test_akshare_feed_derives_dates_from_period_and_end():
    client = FakeAkShareClient()
    feed = AkShareAStockFeed(client=client)

    feed.fetch_bars("000001", interval="1d", end="2024-04-05", period="6mo")

    assert client.calls[0]["start_date"] == "20231005"
    assert client.calls[0]["end_date"] == "20240405"


class FakeAkShareClient:
    def __init__(self):
        self.calls = []

    def stock_zh_a_hist(self, **kwargs):
        self.calls.append(kwargs)
        return pd.DataFrame(
            {
                "日期": ["2024-01-02", "2024-01-03"],
                "开盘": [100.0, 101.0],
                "收盘": [101.5, 102.5],
                "最高": [102.0, 103.0],
                "最低": [99.0, 100.0],
                "成交量": [1000.0, 1200.0],
                "成交额": [101000.0, 122400.0],
            }
        )
