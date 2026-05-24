"""Universe data models."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Universe:
    universe_id: str
    name: str
    market: str
    asset_type: str
    description: str | None = None

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UniverseMember:
    universe_id: str
    instrument_id: str
    start_date: str
    end_date: str | None = None
    reason: str | None = None

    def to_record(self) -> dict:
        return asdict(self)
