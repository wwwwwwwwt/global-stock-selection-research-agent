"""Portfolio decision construction from recommendation items."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from openstockagent.portfolio.models import PortfolioDecision, PortfolioPolicy, PortfolioPosition, TargetAllocation
from openstockagent.recommendations.models import RecommendationItem


DEFAULT_MARKET_REGIME_EXPOSURE = {
    "risk_on": 0.85,
    "neutral": 0.50,
    "risk_off": 0.20,
    "high_risk": 0.0,
    "data_bad": 0.0,
    "unknown": 0.30,
}


@dataclass(frozen=True)
class PortfolioDecisionResult:
    decision: PortfolioDecision
    allocations: list[TargetAllocation] = field(default_factory=list)


def build_default_policy(
    *,
    policy_id: str = "balanced_v1",
    max_gross_exposure: float = 0.8,
    max_single_position_pct: float = 0.1,
    max_positions: int = 10,
    cash_floor_pct: float = 0.1,
    max_new_positions_per_day: int = 5,
    min_recommendation_confidence: float = 0.55,
    min_expected_return: float = 0.0,
    allow_watch_allocation: bool = False,
) -> PortfolioPolicy:
    return PortfolioPolicy(
        policy_id=policy_id,
        max_gross_exposure=max_gross_exposure,
        max_single_position_pct=max_single_position_pct,
        max_positions=max_positions,
        cash_floor_pct=cash_floor_pct,
        max_new_positions_per_day=max_new_positions_per_day,
        min_recommendation_confidence=min_recommendation_confidence,
        min_expected_return=min_expected_return,
        market_regime_exposure_json=json.dumps(DEFAULT_MARKET_REGIME_EXPOSURE, sort_keys=True),
        description="Balanced MVP portfolio policy with market-regime exposure caps.",
        allow_watch_allocation=allow_watch_allocation,
    )


def build_portfolio_decision(
    *,
    recommendation_run_id: str,
    account_id: str,
    decision_date: str,
    market_regime: str,
    capital: float,
    policy: PortfolioPolicy,
    recommendation_items: list[RecommendationItem],
    current_positions: list[PortfolioPosition] | None = None,
    entry_plan_ids_by_recommendation_id: dict[str, str] | None = None,
    decision_id: str | None = None,
) -> PortfolioDecisionResult:
    if capital <= 0:
        raise ValueError("capital must be positive")
    decision_id = decision_id or _stable_decision_id(recommendation_run_id, account_id, decision_date, policy.policy_id)
    regime_cap = _market_regime_cap(market_regime, policy)
    target_gross = min(policy.max_gross_exposure, max(0.0, regime_cap))
    target_gross = min(target_gross, max(0.0, 1.0 - policy.cash_floor_pct))
    actionable = _actionable_items(recommendation_items, policy)
    entry_plan_ids_by_recommendation_id = entry_plan_ids_by_recommendation_id or {}
    current_positions = current_positions or []
    current_weights = _current_position_weights(current_positions, capital)

    if target_gross <= 0:
        action = "empty"
        reason = {"reason": "market_regime_blocks_exposure", "market_regime": market_regime}
        allocations = [
            _exit_allocation(
                decision_id=decision_id,
                position=position,
                capital=capital,
                action="sell",
                reason="market_regime_blocks_exposure",
            )
            for position in current_positions
            if position.market_value > 0
        ]
    elif not actionable:
        action = "no_new_position"
        reason = {"reason": "no_actionable_recommendations", "market_regime": market_regime}
        allocations = [
            _exit_allocation(
                decision_id=decision_id,
                position=position,
                capital=capital,
                action="reduce",
                reason="no_actionable_recommendations",
            )
            for position in current_positions
            if position.market_value > 0
        ]
        target_gross = 0.0
    else:
        selected = actionable[: min(policy.max_positions, policy.max_new_positions_per_day)]
        per_name = min(policy.max_single_position_pct, target_gross / len(selected))
        selected_instruments = {item.instrument_id for item in selected}
        allocations = [
            TargetAllocation(
                decision_id=decision_id,
                instrument_id=item.instrument_id,
                action=_target_action(
                    item=item,
                    current_weight=current_weights.get(item.instrument_id, 0.0),
                    target_weight=per_name,
                ),
                target_weight=round(per_name, 8),
                max_position_value=round(capital * per_name, 2),
                source_recommendation_id=item.recommendation_id,
                reason_json=json.dumps(
                    {
                        "source_screen_score": item.source_screen_score,
                        "confidence": item.confidence,
                        "expected_return": item.expected_return,
                        "source_entry_plan_id": entry_plan_ids_by_recommendation_id.get(
                            item.recommendation_id
                        ),
                        "current_weight": round(current_weights.get(item.instrument_id, 0.0), 8),
                        "target_weight": round(per_name, 8),
                    },
                    sort_keys=True,
                ),
                risk_json=item.risk_json,
                source_entry_plan_id=entry_plan_ids_by_recommendation_id.get(item.recommendation_id),
            )
            for item in selected
        ]
        allocations.extend(
            _exit_allocation(
                decision_id=decision_id,
                position=position,
                capital=capital,
                action="reduce",
                reason="position_not_in_selected_targets",
            )
            for position in current_positions
            if position.instrument_id not in selected_instruments and position.market_value > 0
        )
        target_gross = round(sum(allocation.target_weight for allocation in allocations), 8)
        action = "rebalance" if current_positions else ("allocate" if target_gross > 0 else "no_new_position")
        reason = {
            "reason": "allocated_from_recommendations",
            "market_regime": market_regime,
            "selected_count": len(selected),
            "current_position_count": len(current_positions),
        }

    decision = PortfolioDecision(
        decision_id=decision_id,
        recommendation_run_id=recommendation_run_id,
        account_id=account_id,
        decision_date=decision_date,
        policy_id=policy.policy_id,
        market_regime=market_regime,
        target_gross_exposure=round(target_gross, 8),
        cash_pct=round(1.0 - target_gross, 8),
        action=action,
        reason_json=json.dumps(reason, sort_keys=True),
        risk_json=json.dumps(
            {
                "policy_id": policy.policy_id,
                "regime_cap": regime_cap,
                "max_single_position_pct": policy.max_single_position_pct,
                "cash_floor_pct": policy.cash_floor_pct,
            },
            sort_keys=True,
        ),
    )
    return PortfolioDecisionResult(decision=decision, allocations=allocations)


def _actionable_items(items: list[RecommendationItem], policy: PortfolioPolicy) -> list[RecommendationItem]:
    allowed_actions = {"buy_candidate"}
    if policy.allow_watch_allocation:
        allowed_actions.add("watch")
    candidates = [
        item
        for item in items
        if item.action in allowed_actions
        and item.confidence >= policy.min_recommendation_confidence
        and (item.expected_return is None or item.expected_return >= policy.min_expected_return)
    ]
    return sorted(candidates, key=lambda item: (-item.confidence, -item.source_screen_score, item.rank, item.instrument_id))


def _market_regime_cap(market_regime: str, policy: PortfolioPolicy) -> float:
    caps = json.loads(policy.market_regime_exposure_json)
    return float(caps.get(market_regime, caps.get("unknown", 0.0)))


def _current_position_weights(positions: list[PortfolioPosition], capital: float) -> dict[str, float]:
    return {
        position.instrument_id: max(0.0, float(position.market_value) / capital)
        for position in positions
        if position.market_value > 0
    }


def _target_action(item: RecommendationItem, current_weight: float, target_weight: float) -> str:
    if item.action == "watch" and current_weight <= 0:
        return "watch"
    if current_weight <= 0:
        return "buy"
    tolerance = max(0.005, target_weight * 0.2)
    if current_weight < target_weight - tolerance:
        return "add"
    if current_weight > target_weight + tolerance:
        return "reduce"
    return "hold"


def _exit_allocation(
    *,
    decision_id: str,
    position: PortfolioPosition,
    capital: float,
    action: str,
    reason: str,
) -> TargetAllocation:
    current_weight = max(0.0, float(position.market_value) / capital)
    return TargetAllocation(
        decision_id=decision_id,
        instrument_id=position.instrument_id,
        action=action,
        target_weight=0.0,
        max_position_value=0.0,
        source_recommendation_id=None,
        reason_json=json.dumps(
            {
                "reason": reason,
                "current_weight": round(current_weight, 8),
                "target_weight": 0.0,
                "market_value": position.market_value,
            },
            sort_keys=True,
        ),
        risk_json=json.dumps({"position_exit": True}, sort_keys=True),
    )


def _stable_decision_id(recommendation_run_id: str, account_id: str, decision_date: str, policy_id: str) -> str:
    payload = "|".join([recommendation_run_id, account_id, decision_date, policy_id])
    return f"portfolio-decision-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"
