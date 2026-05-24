"""AKShare feed for China A-share daily bars."""
from __future__ import annotations

import pandas as pd

from .base import BaseMarketDataFeed


class AkShareAStockFeed(BaseMarketDataFeed):
    source = "akshare"

    def __init__(self, client=None, adjust: str = "qfq"):
        self.client = client or _import_akshare()
        self.adjust = adjust

    def fetch_bars(
        self,
        source_symbol: str,
        interval: str,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        end_date = _compact_date(end or pd.Timestamp.utcnow().strftime("%Y-%m-%d"))
        start_date = _compact_date(start) if start else _start_from_period(end_date, period or "1y")
        df = self.client.stock_zh_a_hist(
            symbol=source_symbol,
            period=_akshare_period(interval),
            start_date=start_date,
            end_date=end_date,
            adjust=self.adjust if adjusted else "",
        )
        if df.empty:
            raise ValueError(f"No AKShare data returned for {source_symbol}")
        df = df.rename(
            columns={
                "日期": "timestamp",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
            }
        )
        df = df[["timestamp", "open", "high", "low", "close", "volume", "amount"]].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return df


def _import_akshare():
    import akshare as ak

    return ak


def _akshare_period(interval: str) -> str:
    mapping = {"1d": "daily", "1w": "weekly", "1mo": "monthly"}
    if interval not in mapping:
        raise ValueError(f"Unsupported AKShare A-share interval: {interval}")
    return mapping[interval]


def _compact_date(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def _start_from_period(end_date: str, period: str) -> str:
    end = pd.Timestamp(end_date)
    if period.endswith("mo"):
        start = end - pd.DateOffset(months=int(period[:-2]))
    elif period.endswith("y"):
        start = end - pd.DateOffset(years=int(period[:-1]))
    else:
        raise ValueError(f"Unsupported period for AKShare A-share feed: {period}")
    return start.strftime("%Y%m%d")
