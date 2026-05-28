"""Deterministic daily-bar entry timing rules."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

import pandas as pd

from openstockagent.entry.models import EntryPlan, EntryPlanReview
from openstockagent.market.models import InstrumentStatus
from openstockagent.recommendations.models import RecommendationItem
from openstockagent.recommendations.runner import review_due_date_for


ENTRY_MODES = {
    "breakout_buy",
    "pullback_buy",
    "range_buy",
    "reversal_buy",
    "wait_confirm",
    "avoid_chase",
    "no_entry",
}

ENTRY_STATUSES = {"ready", "wait", "avoid", "invalid", "expired"}

BLOCKING_MARKET_REGIMES = {"data_bad", "high_risk"}


@dataclass(frozen=True)
class EntryRuleConfig:
    strategy_name: str = "daily_entry_timing"
    strategy_version: str = "v1"
    lookback_bars: int = 60
    breakout_buffer: float = 0.005
    pullback_buffer: float = 0.015
    max_extension_from_ma20: float = 0.12
    extended_wait_from_ma20: float = 0.06
    stop_loss_pct: float = 0.07
    take_profit_pct: float = 0.12
    min_wait_confidence: float = 0.45


def build_entry_plan(
    *,
    run_id: str,
    recommendation: RecommendationItem,
    bars: pd.DataFrame,
    as_of: str,
    horizon: str,
    market_regime: str,
    status: InstrumentStatus | None = None,
    factor_values: dict[str, float] | None = None,
    config: EntryRuleConfig | None = None,
) -> EntryPlan:
    """Build one entry plan from one recommendation and recent daily bars."""
    config = config or EntryRuleConfig()
    time_limit_date = review_due_date_for(as_of, horizon)
    clean = _prepare_bars(bars)
    factor_values = factor_values or {}

    if recommendation.action == "skip":
        return _plan(
            run_id=run_id,
            recommendation=recommendation,
            time_limit_date=time_limit_date,
            entry_mode="no_entry",
            entry_status="invalid",
            confidence=0.0,
            reason={"reason": "recommendation_skipped"},
        )
    if market_regime in BLOCKING_MARKET_REGIMES:
        return _plan(
            run_id=run_id,
            recommendation=recommendation,
            time_limit_date=time_limit_date,
            entry_mode="no_entry",
            entry_status="invalid",
            confidence=0.0,
            reason={"reason": "market_regime_blocks_entry", "market_regime": market_regime},
        )
    if status is not None and (not status.is_tradable or status.is_suspended or status.is_st):
        return _plan(
            run_id=run_id,
            recommendation=recommendation,
            time_limit_date=time_limit_date,
            entry_mode="no_entry",
            entry_status="invalid",
            confidence=0.0,
            reason={
                "reason": "instrument_status_blocks_entry",
                "status": status.status,
                "is_tradable": status.is_tradable,
                "is_suspended": status.is_suspended,
                "is_st": status.is_st,
            },
        )
    if clean.empty:
        return _plan(
            run_id=run_id,
            recommendation=recommendation,
            time_limit_date=time_limit_date,
            entry_mode="no_entry",
            entry_status="invalid",
            confidence=0.0,
            reason={"reason": "missing_daily_bars"},
        )

    latest = clean.iloc[-1]
    reference_price = _finite_float(latest.get("close"))
    if reference_price is None or reference_price <= 0:
        return _plan(
            run_id=run_id,
            recommendation=recommendation,
            time_limit_date=time_limit_date,
            entry_mode="no_entry",
            entry_status="invalid",
            confidence=0.0,
            reason={"reason": "invalid_latest_close", "reference_price": reference_price},
        )

    metrics = _entry_metrics(clean)
    ma5 = metrics["ma5"]
    ma20 = metrics["ma20"]
    recent_high_20d = metrics["recent_high_20d"]
    extension_from_ma20 = metrics["extension_from_ma20"]
    near_breakout = reference_price >= recent_high_20d * (1.0 - config.breakout_buffer)
    strong_trend = reference_price > ma5 > ma20
    improving_trend = reference_price > ma5 or ma5 >= ma20
    base_confidence = _base_confidence(recommendation.confidence)

    if extension_from_ma20 >= config.max_extension_from_ma20:
        entry_mode = "avoid_chase"
        entry_status = "avoid"
        trigger_price = None
        pullback_price = _round_price(ma20 * (1.0 + config.pullback_buffer))
        confidence = min(base_confidence, 0.35)
        reason = {"reason": "too_extended_from_ma20"}
    elif strong_trend and near_breakout:
        entry_mode = "breakout_buy"
        entry_status = "ready"
        trigger_price = _round_price(recent_high_20d * (1.0 + config.breakout_buffer))
        pullback_price = _round_price(ma5)
        confidence = base_confidence
        reason = {"reason": "strong_trend_near_breakout"}
    elif strong_trend and extension_from_ma20 >= config.extended_wait_from_ma20:
        entry_mode = "pullback_buy"
        entry_status = "wait"
        trigger_price = None
        pullback_price = _round_price(ma5)
        confidence = max(config.min_wait_confidence, base_confidence - 0.08)
        reason = {"reason": "trend_extended_wait_for_pullback"}
    elif strong_trend:
        entry_mode = "pullback_buy"
        entry_status = "wait"
        trigger_price = None
        pullback_price = _round_price(ma5)
        confidence = max(config.min_wait_confidence, base_confidence - 0.05)
        reason = {"reason": "strong_trend_wait_for_better_price"}
    elif improving_trend:
        entry_mode = "wait_confirm"
        entry_status = "wait"
        trigger_price = _round_price(reference_price * (1.0 + config.breakout_buffer))
        pullback_price = None
        confidence = max(config.min_wait_confidence, base_confidence - 0.1)
        reason = {"reason": "improving_but_not_strong_trend"}
    else:
        entry_mode = "no_entry"
        entry_status = "avoid"
        trigger_price = None
        pullback_price = None
        confidence = min(base_confidence, 0.4)
        reason = {"reason": "weak_entry_structure"}

    planned_entry = trigger_price or pullback_price or reference_price
    stop_loss = _round_price(planned_entry * (1.0 - config.stop_loss_pct)) if planned_entry else None
    take_profit = _round_price(planned_entry * (1.0 + config.take_profit_pct)) if planned_entry else None
    reason.update(
        {
            "market_regime": market_regime,
            "source_recommendation_action": recommendation.action,
            "metrics": metrics,
            "factor_values": factor_values,
        }
    )
    confirmation = {
        "entry_mode": entry_mode,
        "entry_status": entry_status,
        "trigger_price": trigger_price,
        "pullback_price": pullback_price,
        "time_limit_date": time_limit_date,
    }
    invalidation = {
        "stop_loss": stop_loss,
        "market_regime_invalid": sorted(BLOCKING_MARKET_REGIMES),
        "status_invalid": ["st", "suspended", "not_tradable"],
    }
    risk = _merge_json(
        recommendation.risk_json,
        {
            "entry_timing": {
                "stop_loss_pct": config.stop_loss_pct,
                "max_extension_from_ma20": config.max_extension_from_ma20,
            }
        },
    )
    evidence = _merge_json(
        recommendation.evidence_refs_json,
        {"entry_metrics": metrics, "entry_rule_version": config.strategy_version},
    )
    return EntryPlan(
        plan_id=_stable_plan_id(run_id, recommendation.recommendation_id),
        run_id=run_id,
        recommendation_id=recommendation.recommendation_id,
        instrument_id=recommendation.instrument_id,
        rank=recommendation.rank,
        entry_mode=entry_mode,
        entry_status=entry_status,
        reference_price=_round_price(reference_price),
        trigger_price=trigger_price,
        pullback_price=pullback_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        time_limit_date=time_limit_date,
        confidence=round(confidence, 6),
        reason_json=json.dumps(reason, sort_keys=True),
        confirmation_json=json.dumps(confirmation, sort_keys=True),
        invalidation_json=json.dumps(invalidation, sort_keys=True),
        risk_json=json.dumps(risk, sort_keys=True),
        evidence_refs_json=json.dumps(evidence, sort_keys=True),
    )


def build_entry_plan_review(
    *,
    plan: EntryPlan,
    bars: pd.DataFrame,
    review_date: str,
) -> EntryPlanReview:
    clean = _prepare_bars(bars)
    review_id = f"entry-review-{hashlib.sha256((plan.plan_id + '|' + review_date).encode('utf-8')).hexdigest()[:16]}"
    if clean.empty:
        return EntryPlanReview(
            review_id=review_id,
            plan_id=plan.plan_id,
            review_date=review_date,
            triggered=False,
            trigger_date=None,
            entry_price=None,
            review_price=None,
            realized_return=None,
            max_drawdown=None,
            max_favorable_return=None,
            avoided_chase_loss=None,
            missed_opportunity=None,
            entry_quality_score=None,
            review_notes_json=json.dumps({"reason": "missing_review_bars"}, sort_keys=True),
        )

    review_price = _finite_float(clean.iloc[-1].get("close"))
    trigger_idx = None
    entry_price = None
    if plan.entry_status in {"ready", "wait"}:
        if plan.entry_mode == "pullback_buy" and plan.pullback_price is not None:
            trigger_idx, entry_price = _first_low_touch(clean, plan.pullback_price)
        elif plan.trigger_price is not None:
            trigger_idx, entry_price = _first_high_touch(clean, plan.trigger_price)
        elif plan.entry_status == "ready" and plan.reference_price is not None:
            trigger_idx, entry_price = 0, plan.reference_price

    triggered = trigger_idx is not None and entry_price is not None
    trigger_date = None
    realized_return = None
    max_drawdown = None
    max_favorable_return = None
    if triggered:
        after_entry = clean.iloc[trigger_idx:]
        trigger_date = str(after_entry.iloc[0].get("local_date") or after_entry.iloc[0].get("timestamp"))
        realized_return = _safe_return(review_price, entry_price)
        lowest = _finite_float(after_entry["low"].min())
        highest = _finite_float(after_entry["high"].max())
        max_drawdown = _safe_return(lowest, entry_price)
        max_favorable_return = _safe_return(highest, entry_price)

    avoided_chase_loss = None
    missed_opportunity = None
    if not triggered and plan.reference_price and review_price:
        reference_return = _safe_return(review_price, plan.reference_price)
        if plan.entry_status == "avoid":
            avoided_chase_loss = min(reference_return or 0.0, 0.0)
        else:
            missed_opportunity = max(reference_return or 0.0, 0.0)

    entry_quality_score = _entry_quality_score(realized_return, avoided_chase_loss, missed_opportunity)
    notes = {
        "entry_mode": plan.entry_mode,
        "entry_status": plan.entry_status,
        "triggered": triggered,
        "time_limit_date": plan.time_limit_date,
    }
    return EntryPlanReview(
        review_id=review_id,
        plan_id=plan.plan_id,
        review_date=review_date,
        triggered=triggered,
        trigger_date=trigger_date,
        entry_price=_round_price(entry_price),
        review_price=_round_price(review_price),
        realized_return=_round_ratio(realized_return),
        max_drawdown=_round_ratio(max_drawdown),
        max_favorable_return=_round_ratio(max_favorable_return),
        avoided_chase_loss=_round_ratio(avoided_chase_loss),
        missed_opportunity=_round_ratio(missed_opportunity),
        entry_quality_score=_round_ratio(entry_quality_score),
        review_notes_json=json.dumps(notes, sort_keys=True),
    )


def ready_plan_ids_by_recommendation(plans: list[EntryPlan]) -> dict[str, str]:
    return {plan.recommendation_id: plan.plan_id for plan in plans if plan.entry_status == "ready"}


def _plan(
    *,
    run_id: str,
    recommendation: RecommendationItem,
    time_limit_date: str,
    entry_mode: str,
    entry_status: str,
    confidence: float,
    reason: dict[str, Any],
) -> EntryPlan:
    return EntryPlan(
        plan_id=_stable_plan_id(run_id, recommendation.recommendation_id),
        run_id=run_id,
        recommendation_id=recommendation.recommendation_id,
        instrument_id=recommendation.instrument_id,
        rank=recommendation.rank,
        entry_mode=entry_mode,
        entry_status=entry_status,
        reference_price=None,
        trigger_price=None,
        pullback_price=None,
        stop_loss=None,
        take_profit=None,
        time_limit_date=time_limit_date,
        confidence=confidence,
        reason_json=json.dumps(reason, sort_keys=True),
        confirmation_json=json.dumps({"entry_mode": entry_mode, "entry_status": entry_status}, sort_keys=True),
        invalidation_json=recommendation.invalidation_json,
        risk_json=recommendation.risk_json,
        evidence_refs_json=recommendation.evidence_refs_json,
    )


def _prepare_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame()
    frame = bars.copy()
    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp")
    elif "local_date" in frame.columns:
        frame = frame.sort_values("local_date")
    for column in ["open", "high", "low", "close"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["close"])
    return frame.reset_index(drop=True)


def _entry_metrics(bars: pd.DataFrame) -> dict[str, float]:
    close = bars["close"]
    high = bars["high"] if "high" in bars.columns else close
    low = bars["low"] if "low" in bars.columns else close
    latest_close = float(close.iloc[-1])
    recent = bars.tail(20)
    ma5 = float(close.tail(5).mean())
    ma20 = float(close.tail(20).mean())
    recent_high = float((recent["high"] if "high" in recent.columns else recent["close"]).max())
    recent_low = float((recent["low"] if "low" in recent.columns else recent["close"]).min())
    extension = latest_close / ma20 - 1.0 if ma20 > 0 else 0.0
    return {
        "latest_close": round(latest_close, 6),
        "recent_high_20d": round(recent_high, 6),
        "recent_low_20d": round(recent_low, 6),
        "ma5": round(ma5, 6),
        "ma20": round(ma20, 6),
        "extension_from_ma20": round(extension, 6),
        "bar_count": int(len(bars)),
        "latest_high": round(float(high.iloc[-1]), 6),
        "latest_low": round(float(low.iloc[-1]), 6),
    }


def _first_high_touch(bars: pd.DataFrame, price: float) -> tuple[int, float] | tuple[None, None]:
    for index, row in bars.iterrows():
        high = _finite_float(row.get("high"))
        if high is not None and high >= price:
            return int(index), price
    return None, None


def _first_low_touch(bars: pd.DataFrame, price: float) -> tuple[int, float] | tuple[None, None]:
    for index, row in bars.iterrows():
        low = _finite_float(row.get("low"))
        if low is not None and low <= price:
            return int(index), price
    return None, None


def _stable_plan_id(run_id: str, recommendation_id: str) -> str:
    payload = "|".join([run_id, recommendation_id])
    return f"entry-plan-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _base_confidence(confidence: float) -> float:
    return max(0.0, min(1.0, float(confidence)))


def _merge_json(raw: str, extra: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
    except json.JSONDecodeError:
        parsed = {"raw": raw}
    parsed.update(extra)
    return parsed


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_return(value: float | None, base: float | None) -> float | None:
    if value is None or base is None or base == 0:
        return None
    return value / base - 1.0


def _entry_quality_score(
    realized_return: float | None,
    avoided_chase_loss: float | None,
    missed_opportunity: float | None,
) -> float | None:
    if realized_return is not None:
        return max(0.0, min(1.0, 0.5 + realized_return * 5.0))
    if avoided_chase_loss is not None:
        return max(0.0, min(1.0, 0.55 + abs(min(0.0, avoided_chase_loss)) * 3.0))
    if missed_opportunity is not None:
        return max(0.0, min(1.0, 0.45 - missed_opportunity * 2.0))
    return None


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _round_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 8)
