"""Canonical data models used by feeds, storage, predictors, and analysis context."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


BAR_COLUMNS = ["open", "high", "low", "close", "volume", "amount"]
PRICE_COLUMNS = ["open", "high", "low", "close"]
INTERVALS = {"1m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo"}
ADJUSTMENTS = {"raw", "split_adjusted", "total_return_adjusted"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    symbol: str
    market: str
    exchange: str | None
    asset_type: str
    currency: str | None
    name: str | None
    timezone: str | None
    active: bool = True
    metadata_json: str | None = None

    def to_record(self) -> dict:
        record = asdict(self)
        record["active"] = 1 if self.active else 0
        return record


@dataclass(frozen=True)
class InstrumentAlias:
    instrument_id: str
    source: str
    source_symbol: str
    priority: int = 1

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MarketBar:
    instrument_id: str
    timestamp: str
    local_date: str
    interval: str
    source: str
    adjustment: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None
    currency: str | None = None
    is_complete: bool = True
    provider_payload_hash: str | None = None

    def to_record(self) -> dict:
        record = asdict(self)
        record["is_complete"] = 1 if self.is_complete else 0
        return record


@dataclass(frozen=True)
class PredictionRun:
    run_id: str
    model_name: str
    model_variant: str
    instrument_id: str
    interval: str
    lookback_start: str
    lookback_end: str
    horizon: int
    source_selection_json: str
    metadata_json: str | None = None

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TechnicalSignal:
    signal_id: str
    instrument_id: str
    timestamp: str
    interval: str
    signal_type: str
    direction: str
    strength: float
    confidence: float | None
    severity: str
    summary: str
    evidence_json: str
    input_range_start: str
    input_range_end: str
    created_at: str = field(default_factory=utc_now_iso)

    def to_record(self) -> dict:
        return asdict(self)
