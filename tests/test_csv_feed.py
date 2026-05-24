from pathlib import Path

from openstockagent.data.feeds.csv_feed import CsvFeed


def test_csv_feed_fetches_bars():
    feed = CsvFeed(Path("tests/fixtures/sample_bars.csv"))
    df = feed.fetch_bars("AAPL", interval="1d")

    assert len(df) == 3
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "amount"]
    assert df.iloc[-1]["close"] == 104
