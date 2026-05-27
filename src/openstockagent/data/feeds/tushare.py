"""Tushare Pro feed for China A-share production data."""
from __future__ import annotations

from collections.abc import Callable
import json
import os
import time

import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias

from .base import BaseMarketDataFeed


TUSHARE_TOKEN_ENV = "TUSHARE_TOKEN"
TUSHARE_RATE_LIMIT_ENV = "TUSHARE_RATE_LIMIT_PER_MINUTE"
DEFAULT_REQUESTS_PER_MINUTE = 450
DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,vol,amount"
STOCK_BASIC_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,list_status,"
    "list_date,delist_date,is_hs"
)


class TushareRateLimiter:
    """Small synchronous rate limiter for Tushare's per-minute API quotas."""

    def __init__(
        self,
        requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if requests_per_minute < 0:
            raise ValueError("requests_per_minute must be >= 0")
        self.requests_per_minute = requests_per_minute
        self._min_interval_seconds = 0.0 if requests_per_minute == 0 else 60.0 / requests_per_minute
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._min_interval_seconds <= 0:
            return
        now = self._monotonic()
        if self._last_request_at is None:
            self._last_request_at = now
            return
        elapsed = now - self._last_request_at
        remaining = self._min_interval_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)
            now += remaining
        self._last_request_at = now


class TushareClient:
    """Thin SDK wrapper that centralizes token handling and rate limiting."""

    def __init__(
        self,
        token: str,
        *,
        pro_api=None,
        tushare_module=None,
        rate_limiter: TushareRateLimiter | None = None,
        requests_per_minute: int | None = None,
    ):
        if not token:
            raise ValueError(f"Tushare token is required. Set {TUSHARE_TOKEN_ENV}.")
        self.token = token
        limit = _requests_per_minute_from_env() if requests_per_minute is None else requests_per_minute
        self.rate_limiter = rate_limiter or TushareRateLimiter(requests_per_minute=limit)
        self._tushare = tushare_module or _import_tushare()
        self._pro_api = pro_api or self._tushare.pro_api(token)

    @classmethod
    def from_env(
        cls,
        token: str | None = None,
        *,
        requests_per_minute: int | None = None,
        rate_limiter: TushareRateLimiter | None = None,
    ) -> "TushareClient":
        return cls(
            token or os.getenv(TUSHARE_TOKEN_ENV, ""),
            requests_per_minute=requests_per_minute,
            rate_limiter=rate_limiter,
        )

    def query(self, api_name: str, fields: str | None = None, **params) -> pd.DataFrame:
        self.rate_limiter.wait()
        cleaned = _drop_none(params)
        if fields is None:
            return self._pro_api.query(api_name, **cleaned)
        return self._pro_api.query(api_name, fields=fields, **cleaned)

    def pro_bar(self, **params) -> pd.DataFrame:
        self.rate_limiter.wait()
        return self._tushare.pro_bar(api=self._pro_api, **_drop_none(params))


class TushareAStockFeed(BaseMarketDataFeed):
    """China A-share daily-bar feed backed by Tushare Pro."""

    source = "tushare"

    def __init__(
        self,
        client=None,
        *,
        token: str | None = None,
        adjust: str = "qfq",
        requests_per_minute: int | None = None,
    ):
        self.client = client or TushareClient.from_env(token=token, requests_per_minute=requests_per_minute)
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
        if interval != "1d":
            raise ValueError(f"Unsupported Tushare A-share interval: {interval}")

        end_date = _compact_date(end or pd.Timestamp.utcnow().strftime("%Y-%m-%d"))
        start_date = _compact_date(start) if start else _start_from_period(end_date, period or "1y")
        if adjusted:
            frame = self.client.pro_bar(
                ts_code=source_symbol,
                start_date=start_date,
                end_date=end_date,
                adj=self.adjust,
                freq="D",
                asset="E",
            )
        else:
            frame = self.client.query(
                "daily",
                fields=DAILY_FIELDS,
                ts_code=source_symbol,
                start_date=start_date,
                end_date=end_date,
            )
        return _normalize_daily_bars(frame, source_symbol)


class TushareReferenceFeed:
    """Core A-share reference-data endpoints used by the stock-selection system."""

    source = "tushare"

    def __init__(
        self,
        client=None,
        *,
        token: str | None = None,
        requests_per_minute: int | None = None,
    ):
        self.client = client or TushareClient.from_env(token=token, requests_per_minute=requests_per_minute)

    def fetch_stock_basic(self, *, exchange: str = "", list_status: str = "L") -> pd.DataFrame:
        return self.client.query(
            "stock_basic",
            fields=STOCK_BASIC_FIELDS,
            exchange=exchange,
            list_status=list_status,
        )

    def fetch_instruments(
        self,
        *,
        exchange: str = "",
        list_status: str = "L",
    ) -> tuple[list[Instrument], list[InstrumentAlias]]:
        frame = self.fetch_stock_basic(exchange=exchange, list_status=list_status)
        instruments = []
        aliases = []
        for _, row in frame.iterrows():
            instrument = _instrument_from_stock_basic(row)
            instruments.append(instrument)
            aliases.append(InstrumentAlias(instrument.instrument_id, self.source, str(row["ts_code"]), priority=1))
        return instruments, aliases

    def fetch_trade_calendar(
        self,
        *,
        start: str,
        end: str,
        exchange: str = "SSE",
        is_open: int | str | None = None,
    ) -> pd.DataFrame:
        return self.client.query(
            "trade_cal",
            **_drop_none(
                {
                    "exchange": exchange,
                    "start_date": _compact_date(start),
                    "end_date": _compact_date(end),
                    "is_open": is_open,
                }
            ),
        )

    def fetch_daily_basic(
        self,
        *,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        return self.client.query(
            "daily_basic",
            **_drop_none(
                {
                    "ts_code": ts_code,
                    "trade_date": _compact_date(trade_date) if trade_date else None,
                    "start_date": _compact_date(start) if start else None,
                    "end_date": _compact_date(end) if end else None,
                }
            ),
        )

    def fetch_stock_st(
        self,
        *,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        return self.client.query(
            "stock_st",
            **_drop_none(
                {
                    "ts_code": ts_code,
                    "trade_date": _compact_date(trade_date) if trade_date else None,
                    "start_date": _compact_date(start) if start else None,
                    "end_date": _compact_date(end) if end else None,
                }
            ),
        )

    def fetch_suspend(
        self,
        *,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start: str | None = None,
        end: str | None = None,
        suspend_type: str | None = None,
    ) -> pd.DataFrame:
        return self.client.query(
            "suspend_d",
            **_drop_none(
                {
                    "ts_code": ts_code,
                    "trade_date": _compact_date(trade_date) if trade_date else None,
                    "start_date": _compact_date(start) if start else None,
                    "end_date": _compact_date(end) if end else None,
                    "suspend_type": suspend_type,
                }
            ),
        )

    def fetch_stk_limit(
        self,
        *,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        return self.client.query(
            "stk_limit",
            **_drop_none(
                {
                    "ts_code": ts_code,
                    "trade_date": _compact_date(trade_date) if trade_date else None,
                    "start_date": _compact_date(start) if start else None,
                    "end_date": _compact_date(end) if end else None,
                }
            ),
        )

    def fetch_adj_factor(
        self,
        *,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        return self.client.query(
            "adj_factor",
            **_drop_none(
                {
                    "ts_code": ts_code,
                    "trade_date": _compact_date(trade_date) if trade_date else None,
                    "start_date": _compact_date(start) if start else None,
                    "end_date": _compact_date(end) if end else None,
                }
            ),
        )


def _normalize_daily_bars(frame: pd.DataFrame, source_symbol: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError(f"No Tushare data returned for {source_symbol}")
    missing = {"trade_date", "open", "high", "low", "close"} - set(frame.columns)
    if missing:
        raise ValueError(f"Tushare daily bars missing columns: {sorted(missing)}")
    normalized = frame.rename(columns={"trade_date": "timestamp", "vol": "volume"}).copy()
    if "amount" not in normalized.columns:
        normalized["amount"] = None
    normalized = normalized[["timestamp", "open", "high", "low", "close", "volume", "amount"]].copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], format="%Y%m%d", utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    normalized = normalized.sort_values("timestamp").reset_index(drop=True)
    return normalized


def _instrument_from_stock_basic(row: pd.Series) -> Instrument:
    ts_code = str(row["ts_code"])
    symbol, suffix = ts_code.split(".", 1)
    exchange = _exchange_from_tushare_suffix(suffix, row.get("exchange"))
    metadata = _clean_metadata(row.to_dict())
    active = str(row.get("list_status", "L")) == "L"
    return Instrument(
        instrument_id=f"EQUITY:CN:{symbol}",
        symbol=symbol,
        market="CN",
        exchange=exchange,
        asset_type="equity",
        currency="CNY",
        name=_none_if_nan(row.get("name")),
        timezone="Asia/Shanghai",
        active=active,
        metadata_json=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    )


def _exchange_from_tushare_suffix(suffix: str, exchange: object | None = None) -> str:
    if not pd.isna(exchange) and exchange:
        return str(exchange)
    mapping = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
    if suffix not in mapping:
        raise ValueError(f"Unsupported Tushare exchange suffix: {suffix}")
    return mapping[suffix]


def _compact_date(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def _start_from_period(end_date: str, period: str) -> str:
    end = pd.Timestamp(end_date)
    if period.endswith("mo"):
        start = end - pd.DateOffset(months=int(period[:-2]))
    elif period.endswith("y"):
        start = end - pd.DateOffset(years=int(period[:-1]))
    elif period.endswith("d"):
        start = end - pd.DateOffset(days=int(period[:-1]))
    else:
        raise ValueError(f"Unsupported period for Tushare A-share feed: {period}")
    return start.strftime("%Y%m%d")


def _requests_per_minute_from_env() -> int:
    value = os.getenv(TUSHARE_RATE_LIMIT_ENV)
    if value is None:
        return DEFAULT_REQUESTS_PER_MINUTE
    return int(value)


def _drop_none(params: dict) -> dict:
    return {key: value for key, value in params.items() if value is not None}


def _clean_metadata(values: dict) -> dict:
    return {key: _none_if_nan(value) for key, value in values.items()}


def _none_if_nan(value):
    return None if pd.isna(value) else value


def _import_tushare():
    try:
        import tushare as ts
    except ImportError as exc:
        raise ImportError("Install the `tushare` package or run through the project environment.") from exc
    return ts
