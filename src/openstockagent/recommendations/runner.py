"""Build horizon-aware recommendations from screen results."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

import pandas as pd

from openstockagent.recommendations.models import RecommendationItem, RecommendationReview, RecommendationRun
from openstockagent.screening.models import ScreenResult


HORIZON_BUSINESS_DAYS = {
    "1d": 1,
    "5d": 5,
    "20d": 20,
    "60d": 60,
}

DEFAULT_RECOMMENDATION_CONFIG: dict[str, Any] = {
    "buy_threshold": 0.65,
    "watch_threshold": 0.55,
    "max_items": 20,
    "neutral_score": 0.5,
    "expected_return_scale": {
        "1d": 0.02,
        "5d": 0.08,
        "20d": 0.18,
        "60d": 0.30,
    },
}

HORIZON_STRATEGY_PRESETS: dict[str, dict[str, Any]] = {
    "1d": {
        "strategy_name": "recommendation_1d_momentum",
        "strategy_version": "v1",
        "config": {"buy_threshold": 0.72, "watch_threshold": 0.62, "max_items": 10},
    },
    "5d": {
        "strategy_name": "recommendation_5d_swing",
        "strategy_version": "v1",
        "config": {"buy_threshold": 0.65, "watch_threshold": 0.55, "max_items": 20},
    },
    "20d": {
        "strategy_name": "recommendation_20d_trend",
        "strategy_version": "v1",
        "config": {"buy_threshold": 0.60, "watch_threshold": 0.52, "max_items": 30},
    },
    "60d": {
        "strategy_name": "recommendation_60d_midterm",
        "strategy_version": "v1",
        "config": {"buy_threshold": 0.58, "watch_threshold": 0.50, "max_items": 40},
    },
}


@dataclass(frozen=True)
class RecommendationRunResult:
    run_id: str
    screen_run_id: str
    universe_id: str
    recommendation_date: str
    horizon: str
    review_due_date: str
    status: str
    items_seen: int
    buy_candidate_count: int
    watch_count: int
    skip_count: int
    items: list[RecommendationItem] = field(default_factory=list)


@dataclass(frozen=True)
class DueReviewRunResult:
    as_of: str
    due_items_seen: int
    reviews_written: int
    skipped_count: int
    errors: list[str]
    reviews: list[RecommendationReview] = field(default_factory=list)


def run_recommendation_pipeline(
    *,
    screen_run_id: str,
    universe_id: str,
    recommendation_date: str,
    horizon: str,
    screening_storage,
    recommendation_storage,
    strategy_name: str | None = None,
    strategy_version: str | None = None,
    market_regime: str = "unknown",
    config: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> RecommendationRunResult:
    preset = horizon_strategy_preset(horizon)
    strategy_name = strategy_name or preset["strategy_name"]
    strategy_version = strategy_version or preset["strategy_version"]
    config = _merge_config({**preset["config"], **(config or {})})
    review_due_date = review_due_date_for(recommendation_date, horizon)
    run_id = run_id or _stable_run_id(screen_run_id, recommendation_date, horizon, strategy_name, strategy_version)
    screen_results = screening_storage.load_screen_results(screen_run_id, selected_only=True)
    items = build_recommendation_items(run_id, horizon, screen_results, config, market_regime=market_regime)
    buy_count = sum(1 for item in items if item.action == "buy_candidate")
    watch_count = sum(1 for item in items if item.action == "watch")
    skip_count = sum(1 for item in items if item.action == "skip")
    status = "completed" if buy_count or watch_count else "no_signal"

    run = RecommendationRun(
        run_id=run_id,
        screen_run_id=screen_run_id,
        universe_id=universe_id,
        recommendation_date=recommendation_date,
        horizon=horizon,
        review_due_date=review_due_date,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        market_regime=market_regime,
        status=status,
    )
    recommendation_storage.upsert_recommendation_run(run)
    recommendation_storage.delete_recommendation_items(run_id)
    recommendation_storage.upsert_recommendation_items(items)

    return RecommendationRunResult(
        run_id=run_id,
        screen_run_id=screen_run_id,
        universe_id=universe_id,
        recommendation_date=recommendation_date,
        horizon=horizon,
        review_due_date=review_due_date,
        status=status,
        items_seen=len(items),
        buy_candidate_count=buy_count,
        watch_count=watch_count,
        skip_count=skip_count,
        items=items,
    )


def build_recommendation_items(
    run_id: str,
    horizon: str,
    screen_results: list[ScreenResult],
    config: dict[str, Any] | None = None,
    market_regime: str = "unknown",
) -> list[RecommendationItem]:
    config = _merge_config({**horizon_strategy_preset(horizon)["config"], **(config or {})})
    _horizon_days(horizon)
    max_items = int(config["max_items"])
    ordered_results = sorted(screen_results, key=lambda result: (result.rank, -result.total_score, result.instrument_id))[:max_items]
    items = []
    for rank, screen_result in enumerate(ordered_results, start=1):
        action = _action_for_score(screen_result.total_score, config)
        action, market_flags = _apply_market_regime_gate(action, market_regime)
        items.append(_item_from_screen_result(run_id, horizon, rank, screen_result, action, config, market_flags))
    return items


def build_recommendation_review(
    *,
    recommendation_id: str,
    review_date: str,
    entry_price: float,
    review_price: float,
    benchmark_return: float | None = None,
    max_drawdown: float | None = None,
    max_favorable_return: float | None = None,
    thesis_status: str = "unknown",
    invalidation_triggered: bool = False,
    factor_snapshot_json: str = "{}",
    review_notes_json: str = "{}",
    review_id: str | None = None,
) -> RecommendationReview:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    realized_return = round((review_price - entry_price) / entry_price, 8)
    excess_return = None if benchmark_return is None else round(realized_return - benchmark_return, 8)
    hit = realized_return > 0 if benchmark_return is None else excess_return > 0
    review_id = review_id or _stable_review_id(recommendation_id, review_date)
    return RecommendationReview(
        review_id=review_id,
        recommendation_id=recommendation_id,
        review_date=review_date,
        entry_price=float(entry_price),
        review_price=float(review_price),
        realized_return=realized_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        max_drawdown=max_drawdown,
        max_favorable_return=max_favorable_return,
        hit=hit,
        thesis_status=thesis_status,
        invalidation_triggered=invalidation_triggered,
        factor_snapshot_json=factor_snapshot_json,
        review_notes_json=review_notes_json,
    )


def run_due_recommendation_reviews(
    *,
    as_of: str,
    recommendation_storage,
    bar_storage,
    benchmark_return: float | None = None,
    max_items: int | None = None,
) -> DueReviewRunResult:
    due_items = recommendation_storage.load_due_recommendation_items(as_of, limit=max_items)
    reviews = []
    errors = []
    skipped = 0
    for due_item in due_items:
        item = due_item["item"]
        recommendation_date = due_item["recommendation_date"]
        review_due_date = due_item["review_due_date"]
        horizon = due_item["horizon"]
        try:
            frame = bar_storage.load_bars(
                item.instrument_id,
                "1d",
                f"{recommendation_date}T00:00:00Z",
                f"{as_of}T23:59:59Z",
            )
            review = build_review_from_bars(
                item,
                frame,
                recommendation_date=str(recommendation_date),
                review_date=str(review_due_date),
                benchmark_return=benchmark_return,
                horizon=horizon,
            )
            if review is None:
                skipped += 1
                continue
            recommendation_storage.upsert_recommendation_review(review)
            reviews.append(review)
        except Exception as exc:
            errors.append(f"{item.recommendation_id}: {exc}")
    return DueReviewRunResult(
        as_of=as_of,
        due_items_seen=len(due_items),
        reviews_written=len(reviews),
        skipped_count=skipped,
        errors=errors,
        reviews=reviews,
    )


def build_review_from_bars(
    item: RecommendationItem,
    bars,
    *,
    recommendation_date: str,
    review_date: str,
    benchmark_return: float | None = None,
    horizon: str,
) -> RecommendationReview | None:
    if bars.empty:
        return None
    frame = bars.copy().sort_values("timestamp")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"])
    if frame.empty:
        return None
    entry_price = float(frame.iloc[0]["close"])
    review_price = float(frame.iloc[-1]["close"])
    if entry_price <= 0:
        return None
    path_returns = frame["close"] / entry_price - 1.0
    factor_snapshot = {
        "source_screen_rank": item.source_screen_rank,
        "source_screen_score": item.source_screen_score,
        "action": item.action,
        "confidence": item.confidence,
    }
    review_notes = {
        "auto_review": True,
        "recommendation_date": recommendation_date,
        "horizon": horizon,
        "bars_seen": int(len(frame)),
    }
    return build_recommendation_review(
        recommendation_id=item.recommendation_id,
        review_date=review_date,
        entry_price=entry_price,
        review_price=review_price,
        benchmark_return=benchmark_return,
        max_drawdown=round(float(path_returns.min()), 8),
        max_favorable_return=round(float(path_returns.max()), 8),
        thesis_status="confirmed" if review_price >= entry_price else "invalidated",
        invalidation_triggered=review_price < entry_price,
        factor_snapshot_json=json.dumps(factor_snapshot, sort_keys=True),
        review_notes_json=json.dumps(review_notes, sort_keys=True),
    )


def review_due_date_for(recommendation_date: str, horizon: str) -> str:
    days = _horizon_days(horizon)
    return (pd.Timestamp(recommendation_date) + pd.offsets.BDay(days)).strftime("%Y-%m-%d")


def horizon_strategy_preset(horizon: str) -> dict[str, Any]:
    _horizon_days(horizon)
    preset = HORIZON_STRATEGY_PRESETS[horizon]
    return {
        "strategy_name": preset["strategy_name"],
        "strategy_version": preset["strategy_version"],
        "config": preset["config"].copy(),
    }


def _item_from_screen_result(
    run_id: str,
    horizon: str,
    rank: int,
    screen_result: ScreenResult,
    action: str,
    config: dict[str, Any],
    market_flags: list[str] | None = None,
) -> RecommendationItem:
    score_breakdown = _json_loads(screen_result.score_breakdown_json)
    reason = _json_loads(screen_result.reason_json)
    risk = _json_loads(screen_result.risk_json)
    if market_flags:
        risk["flags"] = [*risk.get("flags", []), *market_flags]
    evidence_refs = _json_loads(screen_result.evidence_refs_json)
    recommendation_id = _stable_item_id(run_id, screen_result.instrument_id)
    return RecommendationItem(
        recommendation_id=recommendation_id,
        run_id=run_id,
        instrument_id=screen_result.instrument_id,
        rank=rank,
        action=action,
        source_screen_rank=screen_result.rank,
        source_screen_score=screen_result.total_score,
        expected_return=_expected_return(screen_result.total_score, horizon, config),
        expected_risk=_expected_risk(screen_result.total_score, risk),
        confidence=_confidence(screen_result.total_score, config),
        thesis_json=json.dumps(
            {
                "summary": "Ranked candidate generated from screen result evidence.",
                "horizon": horizon,
                "source_screen_score": screen_result.total_score,
                "top_components": reason.get("top_components", []),
                "supporting_factors": reason.get("supporting_factors", []),
            },
            sort_keys=True,
        ),
        confirmation_json=json.dumps(
            {
                "conditions": [
                    "score remains above watch threshold at next refresh",
                    "no new severe data quality or liquidity risk flag appears",
                    "price-volume evidence remains consistent with top-ranked factors",
                ],
                "score_breakdown": score_breakdown,
            },
            sort_keys=True,
        ),
        invalidation_json=json.dumps(
            {
                "conditions": [
                    "score falls below watch threshold",
                    "risk flags expand materially",
                    "market regime moves to data_bad or high_risk",
                ],
                "watch_threshold": config["watch_threshold"],
            },
            sort_keys=True,
        ),
        risk_json=json.dumps(risk, sort_keys=True),
        evidence_refs_json=json.dumps(evidence_refs, sort_keys=True),
    )


def _action_for_score(score: float, config: dict[str, Any]) -> str:
    if score >= float(config["buy_threshold"]):
        return "buy_candidate"
    if score >= float(config["watch_threshold"]):
        return "watch"
    return "skip"


def _apply_market_regime_gate(action: str, market_regime: str) -> tuple[str, list[str]]:
    if market_regime in {"data_bad", "high_risk"} and action != "skip":
        return "skip", [f"market_regime_{market_regime}"]
    return action, []


def _expected_return(score: float, horizon: str, config: dict[str, Any]) -> float:
    neutral = float(config["neutral_score"])
    scale = float(config["expected_return_scale"][horizon])
    return round(max(0.0, score - neutral) * scale, 8)


def _expected_risk(score: float, risk: dict[str, Any]) -> float:
    risk_penalty = float(risk.get("risk_penalty", 0.0) or 0.0)
    score_risk = max(0.0, 1.0 - score)
    return round(score_risk + risk_penalty, 8)


def _confidence(score: float, config: dict[str, Any]) -> float:
    watch_threshold = float(config["watch_threshold"])
    buy_threshold = float(config["buy_threshold"])
    if buy_threshold <= watch_threshold:
        return round(min(1.0, max(0.0, score)), 8)
    confidence = 0.5 + (score - watch_threshold) / (buy_threshold - watch_threshold) * 0.25
    return round(min(1.0, max(0.0, confidence)), 8)


def _merge_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = {
        **DEFAULT_RECOMMENDATION_CONFIG,
        "expected_return_scale": DEFAULT_RECOMMENDATION_CONFIG["expected_return_scale"].copy(),
    }
    if not config:
        return merged
    for key, value in config.items():
        if key == "expected_return_scale":
            merged["expected_return_scale"].update(value)
        else:
            merged[key] = value
    return merged


def _horizon_days(horizon: str) -> int:
    try:
        return HORIZON_BUSINESS_DAYS[horizon]
    except KeyError as exc:
        raise ValueError(f"Unsupported recommendation horizon: {horizon}") from exc


def _json_loads(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


def _stable_run_id(screen_run_id: str, recommendation_date: str, horizon: str, strategy_name: str, strategy_version: str) -> str:
    payload = "|".join([screen_run_id, recommendation_date, horizon, strategy_name, strategy_version])
    return f"rec-run-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _stable_item_id(run_id: str, instrument_id: str) -> str:
    payload = "|".join([run_id, instrument_id])
    return f"rec-item-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _stable_review_id(recommendation_id: str, review_date: str) -> str:
    payload = "|".join([recommendation_id, review_date])
    return f"rec-review-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"
