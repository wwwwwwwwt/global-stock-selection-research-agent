"""Factor-based screening scores."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from openstockagent.factors.models import FactorValue
from openstockagent.screening.filters import apply_hard_filters
from openstockagent.screening.models import ScreenResult, ScreenStrategy
from openstockagent.universe.models import UniverseMember


DEFAULT_SCREEN_CONFIG: dict[str, Any] = {
    "max_candidates": 20,
    "neutral_score": 0.5,
    "risk_penalty_weight": 0.05,
    "hard_filters": {
        "min_turnover_amount_20d": 0,
        "min_bar_count": 0,
        "min_factor_count": 1,
        "exclude_suspended": True,
        "exclude_incomplete_latest_bar": True,
        "exclude_severe_data_quality_issues": True,
    },
    "weights": {
        "momentum_score": 0.25,
        "trend_score": 0.25,
        "volume_score": 0.15,
        "volatility_score": 0.10,
        "theory_score": 0.10,
        "market_context_score": 0.10,
        "kronos_score": 0.05,
    },
    "components": {
        "momentum_score": ["return_5d", "return_20d", "return_60d"],
        "trend_score": ["ma_trend_score", "ma_slope_20d"],
        "volume_score": ["volume_expansion_20d"],
        "volatility_score": ["atr_14d", "max_drawdown_20d"],
        "theory_score": ["chan_structure_score"],
        "market_context_score": ["market_context_score"],
        "kronos_score": ["kronos_score"],
    },
}


def build_default_strategy(
    *,
    hard_filters: dict[str, Any] | None = None,
    max_candidates: int | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> ScreenStrategy:
    config = deepcopy(DEFAULT_SCREEN_CONFIG)
    if hard_filters:
        config["hard_filters"].update(hard_filters)
    if max_candidates is not None:
        config["max_candidates"] = max_candidates
    if config_overrides:
        _deep_update(config, config_overrides)
    return ScreenStrategy(
        strategy_name="mvp_factor_rank",
        version="v1",
        config=config,
        description="MVP factor ranking strategy with neutral optional theory/context/Kronos scores.",
    )


def rank_screen_candidates(
    run_id: str,
    members: list[UniverseMember],
    factor_values: list[FactorValue],
    strategy: ScreenStrategy,
) -> list[ScreenResult]:
    values_by_instrument = _group_factor_values(factor_values)
    max_candidates = int(strategy.config.get("max_candidates", 20))
    scored = []

    for member in members:
        factors_by_name = values_by_instrument.get(member.instrument_id, {})
        filter_result = apply_hard_filters(factors_by_name, strategy.config)
        if not filter_result.passed:
            continue
        scored.append(_score_member(run_id, member.instrument_id, factors_by_name, strategy, filter_result.flags))

    scored.sort(key=lambda result: (-result.total_score, result.instrument_id))
    ranked = []
    for rank, result in enumerate(scored, start=1):
        ranked.append(
            ScreenResult(
                run_id=result.run_id,
                instrument_id=result.instrument_id,
                rank=rank,
                selected=rank <= max_candidates,
                total_score=result.total_score,
                score_breakdown_json=result.score_breakdown_json,
                reason_json=result.reason_json,
                risk_json=result.risk_json,
                evidence_refs_json=result.evidence_refs_json,
            )
        )
    return ranked


def _score_member(
    run_id: str,
    instrument_id: str,
    factors_by_name: dict[str, FactorValue],
    strategy: ScreenStrategy,
    filter_flags: list[str],
) -> ScreenResult:
    neutral = float(strategy.config.get("neutral_score", 0.5))
    weights = strategy.config["weights"]
    components = strategy.config["components"]
    component_scores = {}

    for component_name, factor_names in components.items():
        component_scores[component_name] = _component_score(factors_by_name, factor_names, neutral)

    volatility_score = component_scores["volatility_score"]["score"]
    risk_penalty = max(0.0, neutral - volatility_score) * float(strategy.config.get("risk_penalty_weight", 0.0))
    total_score = sum(weights[name] * component_scores[name]["score"] for name in weights) - risk_penalty
    total_score = round(float(total_score), 8)

    score_breakdown = {
        **component_scores,
        "risk_penalty": {"score": round(risk_penalty, 8), "weight": -1.0},
        "total_score": total_score,
    }
    reason_json = _reason_json(component_scores, factors_by_name)
    risk_json = {
        "volatility_score": volatility_score,
        "risk_penalty": round(risk_penalty, 8),
        "flags": filter_flags,
    }
    if volatility_score < neutral:
        risk_json["flags"] = [*risk_json["flags"], "below_neutral_volatility_score"]

    return ScreenResult(
        run_id=run_id,
        instrument_id=instrument_id,
        rank=0,
        selected=False,
        total_score=total_score,
        score_breakdown_json=json.dumps(score_breakdown, sort_keys=True),
        reason_json=json.dumps(reason_json, sort_keys=True),
        risk_json=json.dumps(risk_json, sort_keys=True),
        evidence_refs_json=json.dumps(_evidence_refs(factors_by_name), sort_keys=True),
    )


def _component_score(factors_by_name: dict[str, FactorValue], factor_names: list[str], neutral: float) -> dict:
    scores = []
    missing = []
    used = []
    for factor_name in factor_names:
        value = factors_by_name.get(factor_name)
        if value is None or value.percentile is None:
            missing.append(factor_name)
            continue
        scores.append(float(value.percentile))
        used.append(factor_name)
    score = sum(scores) / len(scores) if scores else neutral
    return {
        "score": round(float(score), 8),
        "factor_names": used,
        "missing_factor_names": missing,
    }


def _reason_json(component_scores: dict[str, dict], factors_by_name: dict[str, FactorValue]) -> dict:
    ranked_components = sorted(
        (
            {"component": component_name, "score": values["score"]}
            for component_name, values in component_scores.items()
        ),
        key=lambda item: (-item["score"], item["component"]),
    )
    factor_percentiles = sorted(
        (
            {
                "factor_name": factor.factor_name,
                "percentile": factor.percentile,
                "factor_value": factor.factor_value,
                "version": factor.version,
            }
            for factor in factors_by_name.values()
            if factor.percentile is not None
        ),
        key=lambda item: (-(item["percentile"] or 0), item["factor_name"]),
    )
    return {
        "top_components": ranked_components[:3],
        "supporting_factors": factor_percentiles[:5],
    }


def _evidence_refs(factors_by_name: dict[str, FactorValue]) -> dict:
    factors = []
    for factor in sorted(factors_by_name.values(), key=lambda item: item.factor_name):
        factors.append(
            {
                "factor_name": factor.factor_name,
                "trade_date": factor.trade_date,
                "interval": factor.interval,
                "version": factor.version,
                "evidence_json": factor.evidence_json,
            }
        )
    return {"factors": factors}


def _group_factor_values(factor_values: list[FactorValue]) -> dict[str, dict[str, FactorValue]]:
    grouped: dict[str, dict[str, FactorValue]] = {}
    for value in factor_values:
        grouped.setdefault(value.instrument_id, {})[value.factor_name] = value
    return grouped


def _deep_update(base: dict[str, Any], overrides: dict[str, Any]) -> None:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
