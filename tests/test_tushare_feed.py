import pandas as pd
import pytest

from openstockagent.data.feeds.tushare import TushareAStockFeed, TushareClient, TushareRateLimiter, TushareReferenceFeed


def test_tushare_feed_uses_pro_bar_for_adjusted_daily_bars_and_normalizes_columns():
    client = FakeTushareClient()
    feed = TushareAStockFeed(client=client, adjust="qfq")

    bars = feed.fetch_bars("600519.SH", interval="1d", start="2024-01-01", end="2024-01-03", adjusted=True)

    assert client.pro_bar_calls == [
        {
            "ts_code": "600519.SH",
            "start_date": "20240101",
            "end_date": "20240103",
            "adj": "qfq",
            "freq": "D",
            "asset": "E",
        }
    ]
    assert list(bars.columns) == ["timestamp", "open", "high", "low", "close", "volume", "amount"]
    assert list(bars["timestamp"]) == ["2024-01-02T00:00:00Z", "2024-01-03T00:00:00Z"]
    assert list(bars["close"]) == [101.5, 102.5]
    assert list(bars["volume"]) == [1000.0, 1200.0]
    assert list(bars["amount"]) == [101000000.0, 122400000.0]


def test_tushare_feed_uses_daily_for_unadjusted_bars_and_derives_period_dates():
    client = FakeTushareClient()
    feed = TushareAStockFeed(client=client)

    bars = feed.fetch_bars("000001.SZ", interval="1d", end="2024-04-05", period="6mo", adjusted=False)

    assert client.query_calls == [
        {
            "api_name": "daily",
            "fields": "ts_code,trade_date,open,high,low,close,vol,amount",
            "params": {
                "ts_code": "000001.SZ",
                "start_date": "20231005",
                "end_date": "20240405",
            },
        }
    ]
    assert list(bars["timestamp"]) == ["2024-01-02T00:00:00Z", "2024-01-03T00:00:00Z"]


def test_tushare_feed_rejects_non_daily_intervals():
    feed = TushareAStockFeed(client=FakeTushareClient())

    try:
        feed.fetch_bars("600519.SH", interval="1h")
    except ValueError as exc:
        assert "Unsupported Tushare A-share interval" in str(exc)
    else:
        raise AssertionError("expected unsupported interval to fail")


def test_tushare_rate_limiter_sleeps_to_keep_requests_under_configured_rate():
    clock = FakeClock([10.0, 10.5, 11.1])
    sleeps = []
    limiter = TushareRateLimiter(requests_per_minute=60, monotonic=clock, sleep=sleeps.append)

    limiter.wait()
    limiter.wait()
    limiter.wait()

    assert sleeps == pytest.approx([0.5, 0.9])


def test_tushare_client_honors_zero_rate_limit_for_smoke_tests():
    client = TushareClient("token", tushare_module=FakeTushareModule(), requests_per_minute=0)

    assert client.rate_limiter.requests_per_minute == 0


def test_tushare_reference_feed_fetches_stock_basic_as_instruments_and_aliases():
    client = FakeTushareClient()
    feed = TushareReferenceFeed(client=client)

    instruments, aliases = feed.fetch_instruments(list_status="L")

    assert client.query_calls[0] == {
        "api_name": "stock_basic",
        "fields": (
            "ts_code,symbol,name,area,industry,market,exchange,list_status,"
            "list_date,delist_date,is_hs"
        ),
        "params": {"exchange": "", "list_status": "L"},
    }
    assert [instrument.instrument_id for instrument in instruments] == [
        "EQUITY:CN:600519",
        "EQUITY:CN:000001",
    ]
    assert instruments[0].exchange == "SSE"
    assert instruments[0].metadata_json is not None
    assert [(alias.source, alias.source_symbol) for alias in aliases] == [
        ("tushare", "600519.SH"),
        ("tushare", "000001.SZ"),
    ]


def test_tushare_reference_feed_wraps_core_reference_endpoints_with_compact_dates():
    client = FakeTushareClient()
    feed = TushareReferenceFeed(client=client)

    feed.fetch_trade_calendar(start="2024-01-01", end="2024-01-31")
    feed.fetch_daily_basic(trade_date="2024-01-02")
    feed.fetch_daily(trade_date="2024-01-02")
    feed.fetch_stock_st(trade_date="2024-01-02")
    feed.fetch_suspend(trade_date="2024-01-02", suspend_type="S")
    feed.fetch_stk_limit(trade_date="2024-01-02")

    assert [call["api_name"] for call in client.query_calls] == [
        "trade_cal",
        "daily_basic",
        "daily",
        "stock_st",
        "suspend_d",
        "stk_limit",
    ]
    assert client.query_calls[0]["params"] == {"exchange": "SSE", "start_date": "20240101", "end_date": "20240131"}
    assert client.query_calls[1]["params"] == {"trade_date": "20240102"}
    assert client.query_calls[4]["params"] == {"trade_date": "20240102", "suspend_type": "S"}


class FakeTushareClient:
    def __init__(self):
        self.pro_bar_calls = []
        self.query_calls = []

    def pro_bar(self, **kwargs):
        self.pro_bar_calls.append(kwargs)
        return _raw_daily_frame()

    def query(self, api_name, fields=None, **params):
        self.query_calls.append({"api_name": api_name, "fields": fields, "params": params})
        if api_name == "stock_basic":
            return pd.DataFrame(
                {
                    "ts_code": ["600519.SH", "000001.SZ"],
                    "symbol": ["600519", "000001"],
                    "name": ["贵州茅台", "平安银行"],
                    "area": ["贵州", "深圳"],
                    "industry": ["白酒", "银行"],
                    "market": ["主板", "主板"],
                    "exchange": ["SSE", "SZSE"],
                    "list_status": ["L", "L"],
                    "list_date": ["20010827", "19910403"],
                    "delist_date": [None, None],
                    "is_hs": ["H", "S"],
                }
            )
        return _raw_daily_frame()


class FakeTushareModule:
    def pro_api(self, token):
        return object()


class FakeClock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0)


def _raw_daily_frame():
    return pd.DataFrame(
        {
            "ts_code": ["600519.SH", "600519.SH"],
            "trade_date": ["20240103", "20240102"],
            "open": [101.0, 100.0],
            "high": [103.0, 102.0],
            "low": [100.0, 99.0],
            "close": [102.5, 101.5],
            "vol": [1200.0, 1000.0],
            "amount": [122400.0, 101000.0],
        }
    )
