"""Universe builders from deterministic local sources."""
from __future__ import annotations

import csv
from pathlib import Path

from openstockagent.universe.models import Universe, UniverseMember


def load_universe_csv(
    path: Path,
    universe_id: str,
    name: str,
    market: str,
    asset_type: str,
    description: str | None = None,
) -> tuple[Universe, list[UniverseMember]]:
    universe = Universe(
        universe_id=universe_id,
        name=name,
        market=market,
        asset_type=asset_type,
        description=description,
    )
    with path.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        members = [
            UniverseMember(
                universe_id=universe_id,
                instrument_id=row["instrument_id"],
                start_date=row["start_date"],
                end_date=row.get("end_date") or None,
                reason=row.get("reason") or None,
            )
            for row in rows
        ]
    return universe, members
