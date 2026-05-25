"""Market reality models."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TradingCalendarDay:
    market: str
    calendar_date: str
    is_trading_day: bool
    session_type: str = "regular"
    open_time: str | None = None
    close_time: str | None = None
    source: str = "manual"
    notes_json: str = "{}"

    def to_record(self) -> dict:
        record = asdict(self)
        record["is_trading_day"] = int(self.is_trading_day)
        return record


@dataclass(frozen=True)
class InstrumentStatus:
    instrument_id: str
    status_date: str
    status: str
    is_tradable: bool
    is_st: bool = False
    is_suspended: bool = False
    limit_up: float | None = None
    limit_down: float | None = None
    reason_json: str = "{}"

    def to_record(self) -> dict:
        record = asdict(self)
        record["is_tradable"] = int(self.is_tradable)
        record["is_st"] = int(self.is_st)
        record["is_suspended"] = int(self.is_suspended)
        return record


@dataclass(frozen=True)
class CorporateAction:
    action_id: str
    instrument_id: str
    action_date: str
    ex_date: str | None
    action_type: str
    adjustment_factor: float | None = None
    cash_amount: float | None = None
    split_ratio: float | None = None
    source: str = "manual"
    payload_json: str = "{}"

    def to_record(self) -> dict:
        return asdict(self)

