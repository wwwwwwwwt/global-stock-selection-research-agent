"""Entry timing orchestration."""
from __future__ import annotations

from collections import Counter
import hashlib
import json

import pandas as pd

from openstockagent.entry.models import EntryPlan, EntryPlanRun, EntryPlanRunResult
from openstockagent.entry.rules import EntryRuleConfig, build_entry_plan, build_entry_plan_review


def run_entry_plan_pipeline(
    *,
    recommendation_run_id: str,
    as_of: str,
    horizon: str,
    market_regime: str,
    recommendation_storage,
    bar_storage,
    entry_storage,
    market_reality_storage=None,
    source: str | None = None,
    adjustment: str | None = "split_adjusted",
    config: EntryRuleConfig | None = None,
) -> EntryPlanRunResult:
    config = config or EntryRuleConfig()
    run_id = _stable_entry_run_id(
        recommendation_run_id=recommendation_run_id,
        as_of=as_of,
        horizon=horizon,
        strategy_name=config.strategy_name,
        strategy_version=config.strategy_version,
    )
    recommendations = recommendation_storage.load_recommendation_items(recommendation_run_id, actionable_only=False)
    lookback_start = _lookback_start(as_of, config.lookback_bars)
    plans: list[EntryPlan] = []
    for item in recommendations:
        bars = bar_storage.load_bars(
            item.instrument_id,
            "1d",
            lookback_start,
            as_of,
            source=source,
            adjustment=adjustment,
        )
        status = None
        if market_reality_storage is not None and hasattr(market_reality_storage, "load_instrument_status"):
            status = market_reality_storage.load_instrument_status(item.instrument_id, as_of)
        plans.append(
            build_entry_plan(
                run_id=run_id,
                recommendation=item,
                bars=bars,
                as_of=as_of,
                horizon=horizon,
                market_regime=market_regime,
                status=status,
                config=config,
            )
        )

    summary = _entry_summary(plans)
    run = EntryPlanRun(
        run_id=run_id,
        recommendation_run_id=recommendation_run_id,
        as_of=as_of,
        horizon=horizon,
        market_regime=market_regime,
        strategy_name=config.strategy_name,
        strategy_version=config.strategy_version,
        status="complete",
        summary_json=json.dumps(summary, sort_keys=True),
    )
    entry_storage.upsert_entry_plan_run(run)
    entry_storage.delete_entry_plans(run_id)
    entry_storage.upsert_entry_plans(plans)
    return EntryPlanRunResult(run=run, plans=plans)


def run_due_entry_plan_reviews(
    *,
    as_of: str,
    entry_storage,
    bar_storage,
    limit: int | None = None,
    source: str | None = None,
    adjustment: str | None = "split_adjusted",
) -> list:
    plans = entry_storage.load_due_entry_plans(as_of=as_of, limit=limit)
    start = _lookback_start(as_of, 80)
    reviews = []
    for plan in plans:
        bars = bar_storage.load_bars(
            plan.instrument_id,
            "1d",
            start,
            as_of,
            source=source,
            adjustment=adjustment,
        )
        review = build_entry_plan_review(plan=plan, bars=bars, review_date=as_of)
        entry_storage.upsert_entry_plan_review(review)
        reviews.append(review)
    return reviews


def _stable_entry_run_id(
    *,
    recommendation_run_id: str,
    as_of: str,
    horizon: str,
    strategy_name: str,
    strategy_version: str,
) -> str:
    payload = "|".join([recommendation_run_id, as_of, horizon, strategy_name, strategy_version])
    return f"entry-run-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _lookback_start(as_of: str, lookback_bars: int) -> str:
    # Calendar days keep this storage-agnostic; exchange calendars can refine it later.
    return (pd.Timestamp(as_of) - pd.Timedelta(days=max(lookback_bars * 2, lookback_bars + 30))).date().isoformat()


def _entry_summary(plans: list[EntryPlan]) -> dict:
    statuses = Counter(plan.entry_status for plan in plans)
    modes = Counter(plan.entry_mode for plan in plans)
    return {
        "plan_count": len(plans),
        "ready_count": statuses.get("ready", 0),
        "wait_count": statuses.get("wait", 0),
        "avoid_count": statuses.get("avoid", 0),
        "invalid_count": statuses.get("invalid", 0),
        "status_counts": dict(sorted(statuses.items())),
        "mode_counts": dict(sorted(modes.items())),
    }
