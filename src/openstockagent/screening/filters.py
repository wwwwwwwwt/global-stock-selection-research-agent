"""Hard filters for screen candidates."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from openstockagent.factors.models import FactorValue


@dataclass(frozen=True)
class CandidateFilterResult:
    passed: bool
    flags: list[str]


def apply_hard_filters(factors_by_name: dict[str, FactorValue], config: dict[str, Any]) -> CandidateFilterResult:
    hard_filters = config.get("hard_filters", {})
    flags = []

    min_turnover = float(hard_filters.get("min_turnover_amount_20d", 0) or 0)
    turnover = factors_by_name.get("turnover_amount_20d")
    if min_turnover > 0:
        if turnover is None or turnover.factor_value is None:
            flags.append("missing_turnover_amount_20d")
        elif turnover.factor_value < min_turnover:
            flags.append("turnover_amount_20d_below_minimum")

    min_bar_count = int(hard_filters.get("min_bar_count", 0) or 0)
    if min_bar_count > 0 and _max_bar_count(factors_by_name.values()) < min_bar_count:
        flags.append("bar_count_below_minimum")

    if hard_filters.get("exclude_suspended", True) and _any_evidence_flag(factors_by_name.values(), "suspended", True):
        flags.append("suspended")

    if hard_filters.get("exclude_incomplete_latest_bar", True) and _any_evidence_flag(
        factors_by_name.values(), "latest_bar_complete", False
    ):
        flags.append("incomplete_latest_bar")

    if hard_filters.get("exclude_severe_data_quality_issues", True) and _any_evidence_flag(
        factors_by_name.values(), "severe_data_quality_issue", True
    ):
        flags.append("severe_data_quality_issue")

    min_factor_count = int(hard_filters.get("min_factor_count", 1) or 0)
    if len(factors_by_name) < min_factor_count:
        flags.append("factor_count_below_minimum")

    return CandidateFilterResult(passed=not flags, flags=flags)


def _max_bar_count(values) -> int:
    counts = []
    for value in values:
        evidence = _evidence(value)
        if isinstance(evidence.get("bar_count"), int):
            counts.append(evidence["bar_count"])
    return max(counts, default=0)


def _any_evidence_flag(values, key: str, expected: bool) -> bool:
    return any(_evidence(value).get(key) is expected for value in values)


def _evidence(value: FactorValue) -> dict:
    if not value.evidence_json:
        return {}
    try:
        evidence = json.loads(value.evidence_json)
    except json.JSONDecodeError:
        return {}
    return evidence if isinstance(evidence, dict) else {}
