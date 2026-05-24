"""Pipeline that turns stored factor values into ranked screen results."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib

from openstockagent.screening.models import ScreenResult, ScreenRun, ScreenStrategy
from openstockagent.screening.scoring import build_default_strategy, rank_screen_candidates


@dataclass(frozen=True)
class ScreeningRunResult:
    run_id: str
    universe_id: str
    trade_date: str
    interval: str
    candidates_seen: int
    factor_values_seen: int
    ranked_count: int
    selected_count: int
    filtered_count: int
    errors: list[str]
    results: list[ScreenResult] = field(default_factory=list)


def run_screening_pipeline(
    universe_id: str,
    as_of: str,
    interval: str,
    universe_storage,
    factor_storage,
    screening_storage,
    strategy: ScreenStrategy | None = None,
    run_id: str | None = None,
    market_context_snapshot_id: str | None = None,
) -> ScreeningRunResult:
    strategy = strategy or build_default_strategy()
    run_id = run_id or _stable_run_id(universe_id, as_of, interval, strategy)

    members = universe_storage.load_universe_members(universe_id, as_of=as_of)
    values = factor_storage.load_factor_values(as_of, interval)
    results = rank_screen_candidates(run_id, members, values, strategy)

    screening_storage.upsert_strategy(strategy)
    screening_storage.upsert_screen_run(
        ScreenRun(
            run_id=run_id,
            universe_id=universe_id,
            trade_date=as_of,
            interval=interval,
            strategy_name=strategy.strategy_name,
            version=strategy.version,
            market_context_snapshot_id=market_context_snapshot_id,
            status="completed",
        )
    )
    screening_storage.delete_screen_results(run_id)
    screening_storage.upsert_screen_results(results)

    return ScreeningRunResult(
        run_id=run_id,
        universe_id=universe_id,
        trade_date=as_of,
        interval=interval,
        candidates_seen=len(members),
        factor_values_seen=len(values),
        ranked_count=len(results),
        selected_count=sum(1 for result in results if result.selected),
        filtered_count=max(0, len(members) - len(results)),
        errors=[],
        results=results,
    )


def _stable_run_id(universe_id: str, as_of: str, interval: str, strategy: ScreenStrategy) -> str:
    payload = "|".join([universe_id, as_of, interval, strategy.strategy_name, strategy.version])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"screen-{digest}"
