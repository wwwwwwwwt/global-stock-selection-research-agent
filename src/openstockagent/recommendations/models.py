"""Recommendation and review data models."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RecommendationRun:
    run_id: str
    screen_run_id: str
    universe_id: str
    recommendation_date: str
    horizon: str
    review_due_date: str
    strategy_name: str
    strategy_version: str
    market_regime: str
    status: str

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationItem:
    recommendation_id: str
    run_id: str
    instrument_id: str
    rank: int
    action: str
    source_screen_rank: int
    source_screen_score: float
    expected_return: float | None
    expected_risk: float | None
    confidence: float
    thesis_json: str
    confirmation_json: str
    invalidation_json: str
    risk_json: str
    evidence_refs_json: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["rank_position"] = record.pop("rank")
        return record


@dataclass(frozen=True)
class RecommendationReview:
    review_id: str
    recommendation_id: str
    review_date: str
    entry_price: float
    review_price: float
    realized_return: float
    benchmark_return: float | None
    excess_return: float | None
    max_drawdown: float | None
    max_favorable_return: float | None
    hit: bool
    thesis_status: str
    invalidation_triggered: bool
    factor_snapshot_json: str
    review_notes_json: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["hit"] = int(self.hit)
        record["invalidation_triggered"] = int(self.invalidation_triggered)
        return record

