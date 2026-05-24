"""Cross-sectional factor scoring."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from openstockagent.factors.definitions import FACTOR_DEFINITIONS_BY_NAME
from openstockagent.factors.models import FactorValue


def add_cross_section_scores(values: list[FactorValue]) -> list[FactorValue]:
    if not values:
        return []

    frame = pd.DataFrame([value.to_record() for value in values])
    scored_frames = []
    for factor_name, group in frame.groupby("factor_name", sort=False):
        direction = FACTOR_DEFINITIONS_BY_NAME[factor_name].direction
        ascending = direction == "higher_better"
        group = group.copy()
        group["percentile"] = group["factor_value"].rank(pct=True, ascending=ascending)
        std = group["factor_value"].std(ddof=0)
        if std and not pd.isna(std):
            group["zscore"] = (group["factor_value"] - group["factor_value"].mean()) / std
        else:
            group["zscore"] = 0.0
        scored_frames.append(group)

    scored = pd.concat(scored_frames, ignore_index=True)
    values_by_key = {
        (value.instrument_id, value.trade_date, value.interval, value.factor_name, value.version): value
        for value in values
    }
    results = []
    for row in scored.to_dict("records"):
        key = (row["instrument_id"], row["trade_date"], row["interval"], row["factor_name"], row["version"])
        original = values_by_key[key]
        results.append(
            replace(
                original,
                percentile=None if pd.isna(row["percentile"]) else float(row["percentile"]),
                zscore=None if pd.isna(row["zscore"]) else float(row["zscore"]),
            )
        )
    return results
