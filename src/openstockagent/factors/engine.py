"""Universe-level factor orchestration."""
from __future__ import annotations

import pandas as pd

from openstockagent.factors.cross_section import add_cross_section_scores
from openstockagent.factors.models import FactorValue
from openstockagent.factors.technical import compute_technical_factors
from openstockagent.universe.models import UniverseMember


def compute_universe_factors(
    members: list[UniverseMember],
    bars_by_instrument: dict[str, pd.DataFrame],
    trade_date: str,
    interval: str,
) -> list[FactorValue]:
    values: list[FactorValue] = []
    for member in members:
        bars = bars_by_instrument.get(member.instrument_id)
        if bars is None:
            continue
        values.extend(
            compute_technical_factors(
                member.instrument_id,
                bars,
                trade_date=trade_date,
                interval=interval,
            )
        )
    return add_cross_section_scores(values)
