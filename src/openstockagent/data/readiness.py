"""Data readiness checks for daily stock-selection runs."""
from __future__ import annotations

from dataclasses import dataclass, field
import json

import pandas as pd


BLOCKING_STATUSES = {"data_bad", "market_not_ready"}


@dataclass(frozen=True)
class DataReadinessCheck:
    universe_id: str
    as_of: str
    market: str
    data_status: str
    latest_bar_date: str | None = None
    latest_factor_date: str | None = None
    is_trading_day: bool | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def should_block_recommendations(self) -> bool:
        return self.data_status in BLOCKING_STATUSES

    def to_message(self) -> str:
        return (
            f"data_readiness={self.data_status};"
            f"latest_bar_date={self.latest_bar_date or 'n/a'};"
            f"latest_factor_date={self.latest_factor_date or 'n/a'};"
            f"is_trading_day={self.is_trading_day if self.is_trading_day is not None else 'unknown'};"
            f"flags={json.dumps(self.flags, sort_keys=True)}"
        )


def check_selection_data_readiness(
    *,
    universe_id: str,
    as_of: str,
    market: str,
    universe_storage,
    bar_storage,
    factor_storage,
    market_reality_storage,
    interval: str = "1d",
    adjustment: str | None = "split_adjusted",
    source: str | None = None,
) -> DataReadinessCheck:
    members = universe_storage.load_universe_members(universe_id, as_of=as_of)
    instrument_ids = [member.instrument_id for member in members]
    flags = []
    if not instrument_ids:
        return DataReadinessCheck(
            universe_id=universe_id,
            as_of=as_of,
            market=market.upper(),
            data_status="data_bad",
            flags=["empty_universe"],
        )

    calendar_helper_exists = hasattr(market_reality_storage, "load_trading_calendar_day")
    calendar_day = (
        market_reality_storage.load_trading_calendar_day(market, as_of) if calendar_helper_exists else None
    )
    if calendar_helper_exists and calendar_day is None:
        flags.append("trading_calendar_day_missing")
    elif calendar_day is None:
        flags.append("trading_calendar_helper_missing")
    is_trading_day = None if calendar_day is None else bool(calendar_day.is_trading_day)

    bar_helper_exists = hasattr(bar_storage, "latest_bar_date_for_instruments")
    latest_bar_date = (
        bar_storage.latest_bar_date_for_instruments(
            instrument_ids,
            interval=interval,
            source=source,
            adjustment=adjustment,
        )
        if bar_helper_exists
        else None
    )
    if bar_helper_exists and latest_bar_date is None:
        flags.append("latest_bar_date_missing")
    elif not bar_helper_exists:
        flags.append("latest_bar_date_helper_missing")

    factor_helper_exists = hasattr(factor_storage, "latest_factor_date_for_instruments")
    latest_factor_date = (
        factor_storage.latest_factor_date_for_instruments(instrument_ids, interval=interval)
        if factor_helper_exists
        else None
    )
    if factor_helper_exists and latest_factor_date is None:
        flags.append("latest_factor_date_missing")
    elif not factor_helper_exists:
        flags.append("latest_factor_date_helper_missing")

    status = "ready"
    if is_trading_day is False:
        status = "market_not_ready"
        flags.append("non_trading_day")
    if bar_helper_exists and latest_bar_date is None:
        status = "data_bad"
    elif latest_bar_date is not None and _date_lt(latest_bar_date, as_of):
        flags.append("latest_bar_before_as_of")
        status = "market_not_ready" if is_trading_day is True else "stale"
    if factor_helper_exists and latest_factor_date is None:
        status = "data_bad"
    elif latest_factor_date is not None and _date_lt(latest_factor_date, as_of):
        flags.append("latest_factor_before_as_of")
        if status == "ready":
            status = "market_not_ready" if is_trading_day is True else "stale"

    return DataReadinessCheck(
        universe_id=universe_id,
        as_of=as_of,
        market=market.upper(),
        data_status=status,
        latest_bar_date=latest_bar_date,
        latest_factor_date=latest_factor_date,
        is_trading_day=is_trading_day,
        flags=flags,
    )


def _date_lt(left: str, right: str) -> bool:
    return pd.Timestamp(left).date() < pd.Timestamp(right).date()
