"""Universe-driven market data synchronization."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import time

from openstockagent.data.models import utc_now_iso
from openstockagent.data.normalize import normalize_bars
from openstockagent.data.symbols import to_source_symbol


@dataclass(frozen=True)
class DataSyncPlan:
    plan_id: str
    universe_id: str
    market: str
    interval: str = "1d"
    provider: str = "auto"
    adjustment: str = "split_adjusted"
    mode: str = "incremental"
    lookback_years: int = 3
    incremental_days: int = 10
    config_json: str | None = None

    def period(self) -> str:
        if self.mode == "backfill":
            return f"{self.lookback_years}y"
        if self.mode == "incremental":
            return f"{self.incremental_days}d"
        raise ValueError(f"Unsupported data sync mode: {self.mode}")

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DataSyncRunResult:
    run_id: str
    plan_id: str
    universe_id: str
    market: str
    as_of: str
    mode: str
    interval: str
    period: str
    members_seen: int
    instruments_fetched: int
    failed_instruments: int
    bars_written: int
    errors: list[str]
    started_at: str
    ended_at: str
    status: str


def build_sync_plan(
    *,
    universe_id: str,
    market: str,
    mode: str,
    interval: str = "1d",
    provider: str = "auto",
    adjustment: str = "split_adjusted",
    lookback_years: int = 3,
    incremental_days: int = 10,
) -> DataSyncPlan:
    plan_id = f"{universe_id}-{market.lower()}-{interval}-{mode}"
    config = {
        "daily_incremental_policy": "fetch_recent_window_and_upsert",
        "gap_repair_policy": "same_recent_window_repairs_missing_or_changed_bars",
    }
    return DataSyncPlan(
        plan_id=plan_id,
        universe_id=universe_id,
        market=market.upper(),
        interval=interval,
        provider=provider,
        adjustment=adjustment,
        mode=mode,
        lookback_years=lookback_years,
        incremental_days=incremental_days,
        config_json=json.dumps(config, sort_keys=True),
    )


def run_data_sync_plan(
    plan: DataSyncPlan,
    as_of: str,
    universe_storage,
    bar_storage,
    feed_registry,
    sync_storage=None,
    max_symbols: int | None = None,
    max_attempts: int = 3,
    retry_sleep_seconds: float = 0.5,
) -> DataSyncRunResult:
    started_at = utc_now_iso()
    members = universe_storage.load_universe_members(plan.universe_id, as_of=as_of)
    if max_symbols is not None:
        members = members[:max_symbols]
    period = plan.period()
    bars_written = 0
    fetched = 0
    errors = []

    for member in members:
        try:
            feed = feed_registry.resolve(market=plan.market, asset_type="equity", interval=plan.interval)
            source_symbol = to_source_symbol(member.instrument_id, source=feed.source)
            raw_bars = _fetch_bars_with_retries(
                feed,
                source_symbol,
                interval=plan.interval,
                end=as_of,
                period=period,
                max_attempts=max_attempts,
                retry_sleep_seconds=retry_sleep_seconds,
            )
            normalized = normalize_bars(
                raw_bars,
                instrument_id=member.instrument_id,
                interval=plan.interval,
                source=feed.source,
                adjustment=plan.adjustment,
                currency=_currency_from_market(plan.market),
            )
            bars_written += bar_storage.upsert_bars(normalized)
            fetched += 1
        except Exception as exc:
            symbol = member.instrument_id.split(":")[-1]
            errors.append(f"{symbol}: {exc}")

    ended_at = utc_now_iso()
    result = DataSyncRunResult(
        run_id=_stable_run_id(plan, as_of, started_at),
        plan_id=plan.plan_id,
        universe_id=plan.universe_id,
        market=plan.market,
        as_of=as_of,
        mode=plan.mode,
        interval=plan.interval,
        period=period,
        members_seen=len(members),
        instruments_fetched=fetched,
        failed_instruments=len(errors),
        bars_written=bars_written,
        errors=errors,
        started_at=started_at,
        ended_at=ended_at,
        status="completed_with_errors" if errors else "completed",
    )
    if sync_storage is not None:
        sync_storage.upsert_plan(plan)
        sync_storage.save_run(result)
    return result


def _stable_run_id(plan: DataSyncPlan, as_of: str, started_at: str) -> str:
    payload = "|".join([plan.plan_id, as_of, started_at])
    return f"sync-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _fetch_bars_with_retries(
    feed,
    source_symbol: str,
    *,
    interval: str,
    end: str,
    period: str,
    max_attempts: int,
    retry_sleep_seconds: float,
):
    attempts = max(1, max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            return feed.fetch_bars(
                source_symbol,
                interval=interval,
                end=end,
                period=period,
                adjusted=True,
            )
        except Exception:
            if attempt == attempts:
                raise
            if retry_sleep_seconds > 0:
                time.sleep(retry_sleep_seconds)


def _currency_from_market(market: str) -> str | None:
    return {"US": "USD", "CN": "CNY"}.get(market.upper())
