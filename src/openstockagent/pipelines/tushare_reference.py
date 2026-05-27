"""Tushare reference-data synchronization for China A-shares."""
from __future__ import annotations

from dataclasses import dataclass
import json

import pandas as pd

from openstockagent.market.models import CorporateAction, InstrumentStatus, TradingCalendarDay


@dataclass(frozen=True)
class TushareReferenceSyncResult:
    market: str
    start: str
    end: str
    status_date: str
    instruments_written: int
    aliases_written: int
    calendar_days_written: int
    statuses_written: int
    corporate_actions_written: int


def run_tushare_reference_sync(
    *,
    start: str,
    end: str,
    status_date: str,
    reference_feed,
    market_data_storage,
    market_reality_storage,
    include_instruments: bool = True,
    include_calendar: bool = True,
    include_status: bool = True,
    include_adj_factor: bool = True,
) -> TushareReferenceSyncResult:
    instruments_written = 0
    aliases_written = 0
    calendar_days_written = 0
    statuses_written = 0
    corporate_actions_written = 0

    if include_instruments:
        instruments, aliases = reference_feed.fetch_instruments(list_status="L")
        instruments_written = _upsert_instruments(market_data_storage, instruments)
        aliases_written = _upsert_aliases(market_data_storage, aliases)

    if include_calendar:
        calendar_frame = reference_feed.fetch_trade_calendar(start=start, end=end, exchange="SSE")
        calendar_days = _calendar_days_from_frame(calendar_frame)
        calendar_days_written = market_reality_storage.upsert_trading_calendar_days(calendar_days)

    if include_status:
        status_rows = _status_rows(
            st_frame=reference_feed.fetch_stock_st(trade_date=status_date),
            suspend_frame=reference_feed.fetch_suspend(trade_date=status_date),
            limit_frame=reference_feed.fetch_stk_limit(trade_date=status_date),
            status_date=status_date,
        )
        statuses_written = market_reality_storage.upsert_instrument_statuses(status_rows)

    if include_adj_factor:
        adj_frame = reference_feed.fetch_adj_factor(trade_date=status_date)
        actions = _adjustment_actions_from_frame(adj_frame)
        corporate_actions_written = market_reality_storage.upsert_corporate_actions(actions)

    return TushareReferenceSyncResult(
        market="CN",
        start=start,
        end=end,
        status_date=status_date,
        instruments_written=instruments_written,
        aliases_written=aliases_written,
        calendar_days_written=calendar_days_written,
        statuses_written=statuses_written,
        corporate_actions_written=corporate_actions_written,
    )


def _calendar_days_from_frame(frame: pd.DataFrame) -> list[TradingCalendarDay]:
    if frame is None or frame.empty:
        return []
    days = []
    for _, row in frame.iterrows():
        is_open = int(row.get("is_open", 0)) == 1
        days.append(
            TradingCalendarDay(
                market="CN",
                calendar_date=_date(row["cal_date"]),
                is_trading_day=is_open,
                session_type="regular" if is_open else "closed",
                open_time="09:30" if is_open else None,
                close_time="15:00" if is_open else None,
                source="tushare",
                notes_json=_payload_json(row),
            )
        )
    return days


def _upsert_instruments(market_data_storage, instruments) -> int:
    if hasattr(market_data_storage, "upsert_instruments"):
        return market_data_storage.upsert_instruments(instruments)
    for instrument in instruments:
        market_data_storage.upsert_instrument(instrument)
    return len(instruments)


def _upsert_aliases(market_data_storage, aliases) -> int:
    if hasattr(market_data_storage, "upsert_instrument_aliases"):
        return market_data_storage.upsert_instrument_aliases(aliases)
    for alias in aliases:
        market_data_storage.upsert_instrument_alias(alias)
    return len(aliases)


def _status_rows(
    *,
    st_frame: pd.DataFrame,
    suspend_frame: pd.DataFrame,
    limit_frame: pd.DataFrame,
    status_date: str,
) -> list[InstrumentStatus]:
    rows: dict[str, dict] = {}
    local_date = _date(status_date)

    for _, row in _safe_frame(limit_frame).iterrows():
        instrument_id = _instrument_id(row["ts_code"])
        record = rows.setdefault(instrument_id, _default_status_record(instrument_id, local_date))
        record["limit_up"] = _float_or_none(row.get("up_limit"))
        record["limit_down"] = _float_or_none(row.get("down_limit"))
        record["reasons"]["limit"] = _clean_payload(row)

    for _, row in _safe_frame(st_frame).iterrows():
        instrument_id = _instrument_id(row["ts_code"])
        record = rows.setdefault(instrument_id, _default_status_record(instrument_id, local_date))
        record["is_st"] = True
        record["reasons"]["st"] = _clean_payload(row)

    for _, row in _safe_frame(suspend_frame).iterrows():
        instrument_id = _instrument_id(row["ts_code"])
        record = rows.setdefault(instrument_id, _default_status_record(instrument_id, local_date))
        record["is_suspended"] = True
        record["is_tradable"] = False
        record["reasons"]["suspend"] = _clean_payload(row)

    statuses = []
    for instrument_id in sorted(rows):
        record = rows[instrument_id]
        status = _status_label(record["is_st"], record["is_suspended"])
        statuses.append(
            InstrumentStatus(
                instrument_id=instrument_id,
                status_date=record["status_date"],
                status=status,
                is_tradable=record["is_tradable"],
                is_st=record["is_st"],
                is_suspended=record["is_suspended"],
                limit_up=record["limit_up"],
                limit_down=record["limit_down"],
                reason_json=json.dumps(record["reasons"], ensure_ascii=False, sort_keys=True),
            )
        )
    return statuses


def _adjustment_actions_from_frame(frame: pd.DataFrame) -> list[CorporateAction]:
    if frame is None or frame.empty:
        return []
    actions = []
    for _, row in frame.iterrows():
        instrument_id = _instrument_id(row["ts_code"])
        action_date = _date(row["trade_date"])
        source_symbol = str(row["ts_code"])
        actions.append(
            CorporateAction(
                action_id=f"tushare-adj-factor-{source_symbol}-{action_date}",
                instrument_id=instrument_id,
                action_date=action_date,
                ex_date=action_date,
                action_type="adjustment_factor",
                adjustment_factor=_float_or_none(row.get("adj_factor")),
                source="tushare",
                payload_json=_payload_json(row),
            )
        )
    return actions


def _default_status_record(instrument_id: str, status_date: str) -> dict:
    return {
        "instrument_id": instrument_id,
        "status_date": status_date,
        "is_tradable": True,
        "is_st": False,
        "is_suspended": False,
        "limit_up": None,
        "limit_down": None,
        "reasons": {},
    }


def _status_label(is_st: bool, is_suspended: bool) -> str:
    if is_st and is_suspended:
        return "st_suspended"
    if is_suspended:
        return "suspended"
    if is_st:
        return "st"
    return "active"


def _safe_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    return frame if frame is not None else pd.DataFrame()


def _instrument_id(ts_code: object) -> str:
    symbol = str(ts_code).split(".", 1)[0]
    return f"EQUITY:CN:{symbol}"


def _date(value: object) -> str:
    return pd.Timestamp(str(value)).strftime("%Y-%m-%d")


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _payload_json(row: pd.Series) -> str:
    return json.dumps(_clean_payload(row), ensure_ascii=False, sort_keys=True)


def _clean_payload(row: pd.Series) -> dict:
    return {key: _clean_value(value) for key, value in row.to_dict().items()}


def _clean_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
