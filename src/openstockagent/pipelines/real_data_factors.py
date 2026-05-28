"""Pipeline that turns real feed bars into stored cross-sectional factors."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from openstockagent.data.normalize import normalize_bars
from openstockagent.data.symbols import to_source_symbol
from openstockagent.factors.definitions import DEFAULT_FACTOR_DEFINITIONS
from openstockagent.factors.engine import compute_universe_factors


@dataclass(frozen=True)
class RealDataFactorRunResult:
    universe_id: str
    trade_date: str
    interval: str
    members_seen: int
    instruments_fetched: int
    failed_instruments: int
    bars_written: int
    factor_values_written: int
    errors: list[str]


@dataclass(frozen=True)
class StoredBarFactorRunResult:
    universe_id: str
    trade_date: str
    interval: str
    members_seen: int
    instruments_loaded: int
    missing_instruments: int
    factor_values_written: int
    errors: list[str]


def run_real_data_factor_pipeline(
    universe_id: str,
    as_of: str,
    interval: str,
    period: str,
    universe_storage,
    bar_storage,
    factor_storage,
    feed=None,
    feed_registry=None,
    adjustment: str = "split_adjusted",
    max_symbols: int | None = None,
) -> RealDataFactorRunResult:
    members = universe_storage.load_universe_members(universe_id, as_of=as_of)
    if max_symbols is not None:
        members = members[:max_symbols]
    bars_by_instrument = {}
    bars_written = 0
    errors = []

    for member in members:
        feed_for_member = _resolve_feed(member.instrument_id, interval, feed, feed_registry)
        source_symbol = to_source_symbol(member.instrument_id, source=feed_for_member.source)
        try:
            raw_bars = feed_for_member.fetch_bars(
                source_symbol,
                interval=interval,
                end=as_of,
                period=period,
                adjusted=True,
            )
        except Exception as exc:
            errors.append(f"{source_symbol}: {exc}")
            continue
        normalized = normalize_bars(
            raw_bars,
            instrument_id=member.instrument_id,
            interval=interval,
            source=feed_for_member.source,
            adjustment=adjustment,
            currency=_currency_from_instrument(member.instrument_id),
        )
        bars_written += bar_storage.upsert_bars(normalized)
        bars_by_instrument[member.instrument_id] = _bars_up_to_as_of(normalized, as_of)

    values = compute_universe_factors(
        members,
        bars_by_instrument,
        trade_date=as_of,
        interval=interval,
    )
    factor_storage.upsert_factor_definitions(DEFAULT_FACTOR_DEFINITIONS)
    factor_values_written = factor_storage.upsert_factor_values(values)
    return RealDataFactorRunResult(
        universe_id=universe_id,
        trade_date=as_of,
        interval=interval,
        members_seen=len(members),
        instruments_fetched=len(bars_by_instrument),
        failed_instruments=len(errors),
        bars_written=bars_written,
        factor_values_written=factor_values_written,
        errors=errors,
    )


def run_stored_bar_factor_pipeline(
    universe_id: str,
    as_of: str,
    interval: str,
    lookback_days: int,
    universe_storage,
    bar_storage,
    factor_storage,
    adjustment: str | None = "split_adjusted",
    source: str | None = None,
    max_symbols: int | None = None,
) -> StoredBarFactorRunResult:
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    members = universe_storage.load_universe_members(universe_id, as_of=as_of)
    if max_symbols is not None:
        members = members[:max_symbols]
    start, end = _bar_load_range(as_of, lookback_days)
    errors = []
    loaded_bars = _load_stored_bars_for_members(
        members,
        bar_storage,
        interval=interval,
        start=start,
        end=end,
        source=source,
        adjustment=adjustment,
        errors=errors,
    )
    bars_by_instrument = {
        instrument_id: _bars_up_to_as_of(bars, as_of)
        for instrument_id, bars in loaded_bars.items()
        if not bars.empty
    }

    values = compute_universe_factors(
        members,
        bars_by_instrument,
        trade_date=as_of,
        interval=interval,
    )
    factor_storage.upsert_factor_definitions(DEFAULT_FACTOR_DEFINITIONS)
    factor_values_written = factor_storage.upsert_factor_values(values)
    return StoredBarFactorRunResult(
        universe_id=universe_id,
        trade_date=as_of,
        interval=interval,
        members_seen=len(members),
        instruments_loaded=len(bars_by_instrument),
        missing_instruments=max(0, len(members) - len(bars_by_instrument) - len(errors)),
        factor_values_written=factor_values_written,
        errors=errors,
    )


def _load_stored_bars_for_members(
    members,
    bar_storage,
    *,
    interval: str,
    start: str,
    end: str,
    source: str | None,
    adjustment: str | None,
    errors: list[str],
) -> dict[str, pd.DataFrame]:
    instrument_ids = [member.instrument_id for member in members]
    batch_loader = getattr(bar_storage, "load_bars_for_instruments", None)
    if batch_loader is not None:
        try:
            return batch_loader(
                instrument_ids,
                interval,
                start,
                end,
                source=source,
                adjustment=adjustment,
            )
        except Exception as exc:
            errors.append(f"batch_load: {exc}")
            return {}

    bars_by_instrument = {}
    for member in members:
        try:
            bars = bar_storage.load_bars(
                member.instrument_id,
                interval,
                start,
                end,
                source=source,
                adjustment=adjustment,
            )
        except Exception as exc:
            errors.append(f"{member.instrument_id}: {exc}")
            continue
        if bars.empty:
            continue
        bars_by_instrument[member.instrument_id] = bars
    return bars_by_instrument


def _bars_up_to_as_of(bars: pd.DataFrame, as_of: str) -> pd.DataFrame:
    frame = bars.copy()
    if "local_date" not in frame.columns:
        frame["local_date"] = pd.to_datetime(frame["timestamp"], utc=True).dt.strftime("%Y-%m-%d")
    else:
        frame["local_date"] = pd.to_datetime(frame["local_date"]).dt.strftime("%Y-%m-%d")
    return frame[frame["local_date"] <= as_of].copy()


def _bar_load_range(as_of: str, lookback_days: int) -> tuple[str, str]:
    as_of_date = pd.Timestamp(as_of)
    start = (as_of_date - pd.DateOffset(days=lookback_days)).strftime("%Y-%m-%dT00:00:00Z")
    end = as_of_date.strftime("%Y-%m-%dT23:59:59Z")
    return start, end


def _resolve_feed(instrument_id: str, interval: str, feed, feed_registry):
    if feed_registry is None:
        if feed is None:
            raise ValueError("run_real_data_factor_pipeline requires feed or feed_registry")
        return feed
    _, market, _ = instrument_id.split(":", 2)
    return feed_registry.resolve(market=market, asset_type="equity", interval=interval)


def _currency_from_instrument(instrument_id: str) -> str | None:
    _, market, _ = instrument_id.split(":", 2)
    return {"US": "USD", "CN": "CNY", "HK": "HKD"}.get(market)
