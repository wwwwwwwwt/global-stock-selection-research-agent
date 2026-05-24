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
) -> RealDataFactorRunResult:
    members = universe_storage.load_universe_members(universe_id, as_of=as_of)
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


def _bars_up_to_as_of(bars: pd.DataFrame, as_of: str) -> pd.DataFrame:
    return bars[bars["local_date"] <= as_of].copy()


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
