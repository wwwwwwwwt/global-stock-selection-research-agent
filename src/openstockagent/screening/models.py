"""Screening data models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any


@dataclass(frozen=True)
class ScreenStrategy:
    strategy_name: str
    version: str
    config: dict[str, Any]
    description: str | None = None

    def to_record(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "version": self.version,
            "config_json": json.dumps(self.config, sort_keys=True),
            "description": self.description,
        }


@dataclass(frozen=True)
class ScreenRun:
    run_id: str
    universe_id: str
    trade_date: str
    interval: str
    strategy_name: str
    version: str
    status: str
    market_context_snapshot_id: str | None = None

    def to_record(self) -> dict:
        record = asdict(self)
        record["bar_interval"] = record.pop("interval")
        return record


@dataclass(frozen=True)
class ScreenResult:
    run_id: str
    instrument_id: str
    rank: int
    selected: bool
    total_score: float
    score_breakdown_json: str
    reason_json: str
    risk_json: str
    evidence_refs_json: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["selected"] = int(self.selected)
        record["rank_position"] = record.pop("rank")
        return record
