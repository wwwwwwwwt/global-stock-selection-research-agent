"""Portfolio decision models."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PortfolioAccount:
    account_id: str
    base_currency: str
    capital: float
    risk_profile: str = "balanced"
    metadata_json: str = "{}"

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioPolicy:
    policy_id: str
    max_gross_exposure: float
    max_single_position_pct: float
    max_positions: int
    cash_floor_pct: float
    max_new_positions_per_day: int
    min_recommendation_confidence: float
    min_expected_return: float
    market_regime_exposure_json: str
    description: str | None = None

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioPosition:
    account_id: str
    instrument_id: str
    quantity: float
    cost_basis: float
    market_value: float
    unrealized_return: float | None = None
    opened_at: str | None = None

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioDecision:
    decision_id: str
    recommendation_run_id: str
    account_id: str
    decision_date: str
    policy_id: str
    market_regime: str
    target_gross_exposure: float
    cash_pct: float
    action: str
    reason_json: str
    risk_json: str

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TargetAllocation:
    decision_id: str
    instrument_id: str
    action: str
    target_weight: float
    max_position_value: float
    source_recommendation_id: str | None
    reason_json: str
    risk_json: str

    def to_record(self) -> dict:
        return asdict(self)

