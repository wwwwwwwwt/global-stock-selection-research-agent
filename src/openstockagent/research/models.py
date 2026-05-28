"""Research evaluation data models."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BacktestRun:
    run_id: str
    source_type: str
    source_run_id: str
    universe_id: str | None
    as_of: str
    horizon_days: int
    top_n: int
    benchmark_instrument_id: str | None
    status: str
    summary_json: str

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    instrument_id: str
    rank: int
    source_score: float
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    forward_return: float
    benchmark_return: float | None = None
    excess_return: float | None = None
    max_drawdown: float | None = None
    max_favorable_return: float | None = None
    hit: bool = False
    evidence_json: str = "{}"

    def to_record(self) -> dict:
        record = asdict(self)
        record["rank_position"] = record.pop("rank")
        record["hit"] = int(self.hit)
        return record


@dataclass(frozen=True)
class ResearchExperimentRun:
    experiment_id: str
    universe_id: str
    start_date: str
    end_date: str
    rebalance_frequency: str
    horizon_days: int
    top_n: int
    strategy_name: str
    strategy_version: str
    benchmark_instrument_id: str | None
    status: str
    summary_json: str

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ResearchExperimentDay:
    experiment_id: str
    as_of: str
    screen_run_id: str
    backtest_run_id: str
    market_context_snapshot_id: str | None
    candidate_count: int
    evaluated_count: int
    mean_return: float | None
    mean_excess_return: float | None
    hit_rate: float | None
    summary_json: str

    def to_record(self) -> dict:
        return asdict(self)
