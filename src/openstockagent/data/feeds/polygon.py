"""Polygon.io feed for US stock aggregate bars."""
from __future__ import annotations

import pandas as pd
import requests

from openstockagent.config import POLYGON_API_KEY

from .base import BaseMarketDataFeed


class PolygonStockFeed(BaseMarketDataFeed):
    source = "polygon"

    def __init__(self, api_key: str | None = None, client=None, timeout: int = 10):
        self.api_key = api_key if api_key is not None else POLYGON_API_KEY
        if not self.api_key:
            raise ValueError("PolygonStockFeed requires POLYGON_API_KEY")
        self.client = client or PolygonClient(api_key=self.api_key, timeout=timeout)

    def fetch_bars(
        self,
        source_symbol: str,
        interval: str,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        to_date = _date(end or pd.Timestamp.utcnow().strftime("%Y-%m-%d"))
        from_date = _date(start) if start else _start_from_period(to_date, period or "1y")
        multiplier, timespan = _polygon_interval(interval)
        payload = self.client.get_aggregates(
            ticker=source_symbol,
            multiplier=multiplier,
            timespan=timespan,
            from_date=from_date,
            to_date=to_date,
            adjusted=adjusted,
        )
        rows = payload.get("results") or []
        if not rows:
            raise ValueError(f"No Polygon data returned for {source_symbol}")
        df = pd.DataFrame(rows)
        normalized = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": df["o"],
                "high": df["h"],
                "low": df["l"],
                "close": df["c"],
                "volume": df["v"],
                "amount": df.get("vw", df["c"]) * df["v"],
            }
        )
        return normalized[["timestamp", "open", "high", "low", "close", "volume", "amount"]]


class PolygonClient:
    def __init__(self, api_key: str, timeout: int = 10, session=None):
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()

    def get_aggregates(
        self,
        ticker: str,
        multiplier: int,
        timespan: str,
        from_date: str,
        to_date: str,
        adjusted: bool,
    ) -> dict:
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        response = self.session.get(
            url,
            params={"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


def _polygon_interval(interval: str) -> tuple[int, str]:
    mapping = {"1d": (1, "day"), "1w": (1, "week"), "1mo": (1, "month"), "1h": (1, "hour"), "1m": (1, "minute")}
    if interval not in mapping:
        raise ValueError(f"Unsupported Polygon interval: {interval}")
    return mapping[interval]


def _date(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _start_from_period(end_date: str, period: str) -> str:
    end = pd.Timestamp(end_date)
    if period.endswith("mo"):
        start = end - pd.DateOffset(months=int(period[:-2]))
    elif period.endswith("y"):
        start = end - pd.DateOffset(years=int(period[:-1]))
    elif period.endswith("d"):
        start = end - pd.DateOffset(days=int(period[:-1]))
    else:
        raise ValueError(f"Unsupported period for Polygon feed: {period}")
    return start.strftime("%Y-%m-%d")
