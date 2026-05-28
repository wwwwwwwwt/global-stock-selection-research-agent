"""Market regime snapshots derived from stored stock factors."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from openstockagent.factors.models import FactorValue
from openstockagent.market.models import MarketContextSnapshot
from openstockagent.universe.models import UniverseMember


REGIME_FACTOR_NAMES = {
    "return_20d",
    "return_60d",
    "ma_trend_score",
    "ma_slope_20d",
    "atr_14d",
    "max_drawdown_20d",
}


@dataclass(frozen=True)
class MarketRegimeConfig:
    min_any_factor_coverage: float = 0.10
    min_regime_factor_coverage: float = 0.35
    risk_on_threshold: float = 0.65
    neutral_threshold: float = 0.50
    risk_off_threshold: float = 0.35
    severe_volatility_threshold: float = 0.25


def build_market_context_snapshot(
    *,
    universe_id: str,
    as_of: str,
    market: str,
    universe_storage,
    factor_storage,
    interval: str = "1d",
    config: MarketRegimeConfig | None = None,
    snapshot_id: str | None = None,
) -> MarketContextSnapshot:
    config = config or MarketRegimeConfig()
    members = universe_storage.load_universe_members(universe_id, as_of=as_of)
    factor_values = factor_storage.load_factor_values(as_of, interval)
    return build_market_context_snapshot_from_values(
        universe_id=universe_id,
        as_of=as_of,
        market=market,
        members=members,
        factor_values=factor_values,
        config=config,
        snapshot_id=snapshot_id,
    )


def build_market_context_snapshot_from_values(
    *,
    universe_id: str,
    as_of: str,
    market: str,
    members: list[UniverseMember],
    factor_values: list[FactorValue],
    config: MarketRegimeConfig | None = None,
    snapshot_id: str | None = None,
) -> MarketContextSnapshot:
    config = config or MarketRegimeConfig()
    member_ids = {member.instrument_id for member in members}
    member_count = len(member_ids)
    values = [value for value in factor_values if value.instrument_id in member_ids]
    values_by_factor = _group_by_factor(values)
    any_factor_coverage = _coverage({value.instrument_id for value in values}, member_count)
    regime_factor_ids = {
        value.instrument_id
        for value in values
        if value.factor_name in REGIME_FACTOR_NAMES and value.factor_value is not None
    }
    regime_factor_coverage = _coverage(regime_factor_ids, member_count)

    breadth_score = _average_available(
        [
            _share_positive(values_by_factor.get("return_20d", {})),
            _share_positive(values_by_factor.get("return_60d", {})),
        ]
    )
    trend_score = _average_available(
        [
            _share_at_least(values_by_factor.get("ma_trend_score", {}), 0.5),
            _share_positive(values_by_factor.get("ma_slope_20d", {})),
        ]
    )
    volatility_score = _average_available(
        [
            _share_at_most(values_by_factor.get("atr_14d", {}), 0.06),
            _share_at_least(values_by_factor.get("max_drawdown_20d", {}), -0.08),
        ]
    )
    liquidity_score = _liquidity_score(values_by_factor)
    regime_score = _weighted_score(
        [
            (breadth_score, 0.45),
            (trend_score, 0.35),
            (volatility_score, 0.20),
        ]
    )
    flags = []
    risk_regime = _risk_regime(
        member_count=member_count,
        any_factor_coverage=any_factor_coverage,
        regime_factor_coverage=regime_factor_coverage,
        regime_score=regime_score,
        trend_score=trend_score,
        volatility_score=volatility_score,
        config=config,
        flags=flags,
    )
    reportable_regime_score = None if _has_insufficient_coverage(flags) else regime_score
    snapshot_id = snapshot_id or _stable_snapshot_id(market, universe_id, as_of, risk_regime)
    summary = {
        "member_count": member_count,
        "factor_value_count": len(values),
        "any_factor_coverage": any_factor_coverage,
        "regime_factor_coverage": regime_factor_coverage,
        "raw_regime_score": regime_score,
        "input_factor_counts": {factor_name: len(items) for factor_name, items in sorted(values_by_factor.items())},
        "flags": flags,
        "rules": {
            "risk_on_threshold": config.risk_on_threshold,
            "neutral_threshold": config.neutral_threshold,
            "risk_off_threshold": config.risk_off_threshold,
            "min_any_factor_coverage": config.min_any_factor_coverage,
            "min_regime_factor_coverage": config.min_regime_factor_coverage,
        },
    }
    return MarketContextSnapshot(
        snapshot_id=snapshot_id,
        as_of=as_of,
        market=market.upper(),
        universe_id=universe_id,
        risk_regime=risk_regime,
        regime_score=_round_or_none(reportable_regime_score),
        coverage=_round_or_none(regime_factor_coverage),
        breadth_score=_round_or_none(breadth_score),
        trend_score=_round_or_none(trend_score),
        volatility_score=_round_or_none(volatility_score),
        liquidity_score=_round_or_none(liquidity_score),
        summary_json=json.dumps(summary, sort_keys=True),
    )


def _risk_regime(
    *,
    member_count: int,
    any_factor_coverage: float,
    regime_factor_coverage: float,
    regime_score: float | None,
    trend_score: float | None,
    volatility_score: float | None,
    config: MarketRegimeConfig,
    flags: list[str],
) -> str:
    if member_count == 0:
        flags.append("empty_universe")
        return "data_bad"
    if any_factor_coverage < config.min_any_factor_coverage:
        flags.append("insufficient_factor_coverage")
        return "data_bad"
    if regime_factor_coverage < config.min_regime_factor_coverage or regime_score is None:
        flags.append("insufficient_regime_factor_coverage")
        return "unknown"
    if (
        volatility_score is not None
        and volatility_score < config.severe_volatility_threshold
        and trend_score is not None
        and trend_score < config.risk_off_threshold
    ):
        flags.append("severe_volatility_and_weak_trend")
        return "high_risk"
    if regime_score >= config.risk_on_threshold:
        return "risk_on"
    if regime_score >= config.neutral_threshold:
        return "neutral"
    if regime_score >= config.risk_off_threshold:
        return "risk_off"
    return "high_risk"


def _group_by_factor(values: list[FactorValue]) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, float]] = {}
    for value in values:
        if value.factor_value is None:
            continue
        grouped.setdefault(value.factor_name, {})[value.instrument_id] = float(value.factor_value)
    return grouped


def _coverage(instrument_ids: set[str], member_count: int) -> float:
    if member_count <= 0:
        return 0.0
    return len(instrument_ids) / member_count


def _share_positive(values: dict[str, float]) -> float | None:
    return _share(values, lambda value: value > 0)


def _share_at_least(values: dict[str, float], threshold: float) -> float | None:
    return _share(values, lambda value: value >= threshold)


def _share_at_most(values: dict[str, float], threshold: float) -> float | None:
    return _share(values, lambda value: value <= threshold)


def _share(values: dict[str, float], predicate) -> float | None:
    if not values:
        return None
    return sum(1 for value in values.values() if predicate(value)) / len(values)


def _liquidity_score(values_by_factor: dict[str, dict[str, float]]) -> float | None:
    turnover_amount = values_by_factor.get("turnover_amount_20d", {})
    turnover_rate = values_by_factor.get("turnover_rate", {})
    return _average_available(
        [
            _share_at_least(turnover_amount, 10_000_000),
            _share_at_least(turnover_rate, 1.0),
        ]
    )


def _average_available(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    if not available:
        return None
    return sum(available) / len(available)


def _weighted_score(values: list[tuple[float | None, float]]) -> float | None:
    available = [(value, weight) for value, weight in values if value is not None]
    if not available:
        return None
    total_weight = sum(weight for _, weight in available)
    return sum(value * weight for value, weight in available) / total_weight


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(float(value), 8)


def _has_insufficient_coverage(flags: list[str]) -> bool:
    return any(flag in {"insufficient_factor_coverage", "insufficient_regime_factor_coverage"} for flag in flags)


def _stable_snapshot_id(market: str, universe_id: str, as_of: str, risk_regime: str) -> str:
    payload = "|".join([market.upper(), universe_id, as_of, risk_regime])
    return f"market-context-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"
