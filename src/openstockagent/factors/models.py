"""Factor data models."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FactorDefinition:
    factor_name: str
    category: str
    direction: str
    description: str
    version: str = "v1"

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FactorValue:
    instrument_id: str
    trade_date: str
    interval: str
    factor_name: str
    factor_value: float | None
    percentile: float | None = None
    zscore: float | None = None
    version: str = "v1"
    evidence_json: str | None = None

    def to_record(self) -> dict:
        return asdict(self)
