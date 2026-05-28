"""Entry timing models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class EntryPlanRun:
    run_id: str
    recommendation_run_id: str
    as_of: str
    horizon: str
    market_regime: str
    strategy_name: str
    strategy_version: str
    status: str
    summary_json: str

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EntryPlan:
    plan_id: str
    run_id: str
    recommendation_id: str
    instrument_id: str
    rank: int
    entry_mode: str
    entry_status: str
    reference_price: float | None
    trigger_price: float | None
    pullback_price: float | None
    stop_loss: float | None
    take_profit: float | None
    time_limit_date: str
    confidence: float
    reason_json: str
    confirmation_json: str
    invalidation_json: str
    risk_json: str
    evidence_refs_json: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["rank_position"] = record.pop("rank")
        return record


@dataclass(frozen=True)
class EntryPlanReview:
    review_id: str
    plan_id: str
    review_date: str
    triggered: bool
    trigger_date: str | None
    entry_price: float | None
    review_price: float | None
    realized_return: float | None
    max_drawdown: float | None
    max_favorable_return: float | None
    avoided_chase_loss: float | None
    missed_opportunity: float | None
    entry_quality_score: float | None
    review_notes_json: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["triggered"] = int(self.triggered)
        return record


@dataclass(frozen=True)
class EntryPlanRunResult:
    run: EntryPlanRun
    plans: list[EntryPlan] = field(default_factory=list)
