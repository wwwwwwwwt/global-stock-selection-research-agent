"""Tushare trade-date batch synchronization for China A-shares."""
from __future__ import annotations

from dataclasses import dataclass
import json

import pandas as pd

from openstockagent.data.normalize import normalize_bars
from openstockagent.data.symbols import to_source_symbol
from openstockagent.factors.cross_section import add_cross_section_scores
from openstockagent.factors.definitions import FACTOR_DEFINITIONS_BY_NAME
from openstockagent.factors.models import FactorValue


DAILY_BASIC_FACTORS = [
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "pe_ttm",
    "pb",
    "ps_ttm",
    "dv_ttm",
    "total_mv",
    "circ_mv",
]


@dataclass(frozen=True)
class TushareDailyBatchSyncResult:
    universe_id: str
    trade_date: str
    members_seen: int
    daily_rows_seen: int
    daily_basic_rows_seen: int
    bars_written: int
    factor_values_written: int
    instruments_matched: int


def run_tushare_daily_batch_sync(
    *,
    universe_id: str,
    trade_date: str,
    reference_feed,
    universe_storage,
    bar_storage,
    factor_storage,
    include_bars: bool = True,
    include_daily_basic: bool = True,
    max_symbols: int | None = None,
) -> TushareDailyBatchSyncResult:
    members = universe_storage.load_universe_members(universe_id, as_of=trade_date)
    if max_symbols is not None:
        members = members[:max_symbols]
    source_to_instrument = {
        to_source_symbol(member.instrument_id, source="tushare"): member.instrument_id for member in members
    }
    source_symbols = set(source_to_instrument)

    daily_rows_seen = 0
    daily_basic_rows_seen = 0
    bars_written = 0
    factor_values_written = 0
    matched_symbols = set()

    if include_bars:
        daily_frame = reference_feed.fetch_daily(trade_date=trade_date)
        daily_rows_seen = len(daily_frame)
        matched_daily = _filter_source_symbols(daily_frame, source_symbols)
        matched_symbols.update(matched_daily["ts_code"].astype(str).tolist())
        canonical_bars = _canonical_bars_from_daily(matched_daily, source_to_instrument)
        bars_written = bar_storage.upsert_bars(canonical_bars)

    if include_daily_basic:
        daily_basic_frame = reference_feed.fetch_daily_basic(trade_date=trade_date)
        daily_basic_rows_seen = len(daily_basic_frame)
        matched_daily_basic = _filter_source_symbols(daily_basic_frame, source_symbols)
        matched_symbols.update(matched_daily_basic["ts_code"].astype(str).tolist())
        values = _daily_basic_factor_values(matched_daily_basic, source_to_instrument, trade_date)
        scored_values = add_cross_section_scores(values)
        factor_storage.upsert_factor_definitions(
            [FACTOR_DEFINITIONS_BY_NAME[factor_name] for factor_name in DAILY_BASIC_FACTORS]
        )
        factor_values_written = factor_storage.upsert_factor_values(scored_values)

    return TushareDailyBatchSyncResult(
        universe_id=universe_id,
        trade_date=trade_date,
        members_seen=len(members),
        daily_rows_seen=daily_rows_seen,
        daily_basic_rows_seen=daily_basic_rows_seen,
        bars_written=bars_written,
        factor_values_written=factor_values_written,
        instruments_matched=len(matched_symbols),
    )


def _filter_source_symbols(frame: pd.DataFrame, source_symbols: set[str]) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    filtered = frame[frame["ts_code"].astype(str).isin(source_symbols)].copy()
    return filtered.reset_index(drop=True)


def _canonical_bars_from_daily(frame: pd.DataFrame, source_to_instrument: dict[str, str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    canonical_frames = []
    for source_symbol, group in frame.groupby("ts_code", sort=False):
        feed_bars = group.rename(columns={"trade_date": "timestamp", "vol": "volume"}).copy()
        feed_bars["timestamp"] = pd.to_datetime(feed_bars["timestamp"], format="%Y%m%d", utc=True).dt.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        feed_bars["amount"] = pd.to_numeric(feed_bars["amount"], errors="coerce") * 1000
        canonical_frames.append(
            normalize_bars(
                feed_bars,
                instrument_id=source_to_instrument[str(source_symbol)],
                interval="1d",
                source="tushare",
                adjustment="raw",
                currency="CNY",
            )
        )
    return pd.concat(canonical_frames, ignore_index=True) if canonical_frames else pd.DataFrame()


def _daily_basic_factor_values(
    frame: pd.DataFrame,
    source_to_instrument: dict[str, str],
    trade_date: str,
) -> list[FactorValue]:
    if frame.empty:
        return []
    values = []
    for _, row in frame.iterrows():
        instrument_id = source_to_instrument[str(row["ts_code"])]
        evidence = json.dumps(
            {
                "source": "tushare",
                "source_symbol": str(row["ts_code"]),
                "trade_date": _date(row.get("trade_date", trade_date)),
                "raw_endpoint": "daily_basic",
            },
            sort_keys=True,
        )
        for factor_name in DAILY_BASIC_FACTORS:
            if factor_name not in row:
                continue
            values.append(
                FactorValue(
                    instrument_id=instrument_id,
                    trade_date=trade_date,
                    interval="1d",
                    factor_name=factor_name,
                    factor_value=_float_or_none(row[factor_name]),
                    version="v1",
                    evidence_json=evidence,
                )
            )
    return values


def _date(value: object) -> str:
    return pd.Timestamp(str(value)).strftime("%Y-%m-%d")


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
