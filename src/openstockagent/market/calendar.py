"""Trading calendar helpers."""
from __future__ import annotations

import pandas as pd


def add_trading_days(start_date: str, days: int, calendar_storage=None, market: str | None = None) -> str:
    if days < 0:
        raise ValueError("days must be non-negative")
    if days == 0:
        return pd.Timestamp(start_date).strftime("%Y-%m-%d")
    if calendar_storage is not None and market is not None:
        stored = calendar_storage.next_trading_date(market, start_date, days)
        if stored is not None:
            return stored
    return (pd.Timestamp(start_date) + pd.offsets.BDay(days)).strftime("%Y-%m-%d")


def previous_trading_date(as_of: str, calendar_storage=None, market: str | None = None) -> str:
    if calendar_storage is not None and market is not None:
        stored = calendar_storage.previous_trading_date(market, as_of)
        if stored is not None:
            return stored
    return (pd.Timestamp(as_of) - pd.offsets.BDay(1)).strftime("%Y-%m-%d")

