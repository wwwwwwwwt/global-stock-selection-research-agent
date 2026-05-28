"""Evaluate historical screening results against forward bars."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

import pandas as pd

from openstockagent.entry.models import EntryPlan, EntryPlanReview
from openstockagent.entry.rules import build_entry_plan_review
from openstockagent.research.models import BacktestResult, BacktestRun
from openstockagent.screening.models import ScreenResult


@dataclass(frozen=True)
class ScreenBacktestEvaluation:
    run: BacktestRun
    results: list[BacktestResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EntryPlanBacktestEvaluation:
    run: BacktestRun
    reviews: list[EntryPlanReview] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def evaluate_screen_run(
    *,
    screen_run_id: str,
    as_of: str,
    horizon_days: int,
    top_n: int,
    screening_storage,
    bar_storage,
    evaluation_storage=None,
    universe_id: str | None = None,
    interval: str = "1d",
    source: str | None = None,
    adjustment: str | None = "split_adjusted",
    benchmark_instrument_id: str | None = None,
    run_id: str | None = None,
) -> ScreenBacktestEvaluation:
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if top_n <= 0:
        raise ValueError("top_n must be positive")

    screen_results = screening_storage.load_screen_results(screen_run_id, selected_only=True)
    candidates = sorted(screen_results, key=lambda item: (item.rank, -item.total_score, item.instrument_id))[:top_n]
    run_id = run_id or _stable_run_id(screen_run_id, as_of, horizon_days, top_n)
    start, end = _forward_bar_range(as_of, horizon_days)
    benchmark_return = _load_benchmark_return(
        benchmark_instrument_id=benchmark_instrument_id,
        bar_storage=bar_storage,
        interval=interval,
        start=start,
        end=end,
        source=source,
        adjustment=adjustment,
        horizon_days=horizon_days,
    )

    results = []
    errors = []
    for candidate in candidates:
        try:
            bars = bar_storage.load_bars(
                candidate.instrument_id,
                interval,
                start,
                end,
                source=source,
                adjustment=adjustment,
            )
            result = build_forward_return_result(
                run_id=run_id,
                candidate=candidate,
                bars=bars,
                horizon_days=horizon_days,
                benchmark_return=benchmark_return,
            )
        except Exception as exc:
            errors.append(f"{candidate.instrument_id}: {exc}")
            continue
        if result is None:
            errors.append(f"{candidate.instrument_id}: insufficient_forward_bars")
            continue
        results.append(result)

    summary = _summary(candidates_seen=len(candidates), results=results, errors=errors)
    run = BacktestRun(
        run_id=run_id,
        source_type="screen",
        source_run_id=screen_run_id,
        universe_id=universe_id,
        as_of=as_of,
        horizon_days=horizon_days,
        top_n=top_n,
        benchmark_instrument_id=benchmark_instrument_id,
        status="completed" if results else "no_data",
        summary_json=json.dumps(summary, sort_keys=True),
    )
    if evaluation_storage is not None:
        evaluation_storage.upsert_backtest_run(run)
        evaluation_storage.delete_backtest_results(run_id)
        evaluation_storage.upsert_backtest_results(results)
    return ScreenBacktestEvaluation(run=run, results=results, errors=errors)


def evaluate_entry_plan_run(
    *,
    entry_run_id: str,
    entry_storage,
    bar_storage,
    research_storage=None,
    review_date: str | None = None,
    interval: str = "1d",
    source: str | None = None,
    adjustment: str | None = "split_adjusted",
    run_id: str | None = None,
) -> EntryPlanBacktestEvaluation:
    entry_run = entry_storage.load_entry_plan_run(entry_run_id)
    if entry_run is None:
        raise ValueError(f"entry plan run not found: {entry_run_id}")
    plans = entry_storage.load_entry_plans(entry_run_id, ready_only=False)
    horizon_days = _horizon_to_days(entry_run.horizon)
    run_id = run_id or _stable_entry_backtest_run_id(entry_run_id, review_date or "", horizon_days)

    reviews = []
    errors = []
    for plan in plans:
        plan_review_date = review_date or plan.time_limit_date
        try:
            start, end = _entry_review_bar_range(entry_run.as_of, plan_review_date, horizon_days)
            bars = bar_storage.load_bars(
                plan.instrument_id,
                interval,
                start,
                end,
                source=source,
                adjustment=adjustment,
            )
            review = build_entry_plan_review(plan=plan, bars=bars, review_date=plan_review_date)
        except Exception as exc:
            errors.append(f"{plan.instrument_id}: {exc}")
            continue
        entry_storage.upsert_entry_plan_review(review)
        reviews.append(review)

    summary = _entry_evaluation_summary(plans=plans, reviews=reviews, errors=errors)
    run = BacktestRun(
        run_id=run_id,
        source_type="entry",
        source_run_id=entry_run_id,
        universe_id=None,
        as_of=entry_run.as_of,
        horizon_days=horizon_days,
        top_n=len(plans),
        benchmark_instrument_id=None,
        status="completed" if reviews else "no_data",
        summary_json=json.dumps(summary, sort_keys=True),
    )
    if research_storage is not None:
        research_storage.upsert_backtest_run(run)
    return EntryPlanBacktestEvaluation(run=run, reviews=reviews, errors=errors)


def build_forward_return_result(
    *,
    run_id: str,
    candidate: ScreenResult,
    bars,
    horizon_days: int,
    benchmark_return: float | None = None,
) -> BacktestResult | None:
    metrics = _forward_bar_metrics(bars, horizon_days)
    if metrics is None:
        return None
    excess_return = None if benchmark_return is None else round(metrics["forward_return"] - benchmark_return, 8)
    evidence = {
        "source_screen_run_id": candidate.run_id,
        "source_rank": candidate.rank,
        "horizon_days": horizon_days,
        "bars_seen": metrics["bars_seen"],
        "benchmark_return": benchmark_return,
    }
    return BacktestResult(
        run_id=run_id,
        instrument_id=candidate.instrument_id,
        rank=candidate.rank,
        source_score=candidate.total_score,
        entry_date=metrics["entry_date"],
        exit_date=metrics["exit_date"],
        entry_price=metrics["entry_price"],
        exit_price=metrics["exit_price"],
        forward_return=metrics["forward_return"],
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        max_drawdown=metrics["max_drawdown"],
        max_favorable_return=metrics["max_favorable_return"],
        hit=metrics["forward_return"] > 0,
        evidence_json=json.dumps(evidence, sort_keys=True),
    )


def _load_benchmark_return(
    *,
    benchmark_instrument_id: str | None,
    bar_storage,
    interval: str,
    start: str,
    end: str,
    source: str | None,
    adjustment: str | None,
    horizon_days: int,
) -> float | None:
    if benchmark_instrument_id is None:
        return None
    try:
        bars = bar_storage.load_bars(
            benchmark_instrument_id,
            interval,
            start,
            end,
            source=source,
            adjustment=adjustment,
        )
    except Exception:
        return None
    metrics = _forward_bar_metrics(bars, horizon_days)
    return None if metrics is None else metrics["forward_return"]


def _forward_bar_metrics(bars, horizon_days: int) -> dict | None:
    frame = _prepare_forward_bars(bars)
    if len(frame) <= horizon_days:
        return None
    entry = frame.iloc[0]
    exit_row = frame.iloc[horizon_days]
    entry_price = float(entry["close"])
    exit_price = float(exit_row["close"])
    if entry_price <= 0:
        return None
    path = frame.iloc[: horizon_days + 1].copy()
    path_returns = path["close"] / entry_price - 1.0
    path_drawdowns = path["close"] / path["close"].cummax() - 1.0
    return {
        "entry_date": _date_from_row(entry),
        "exit_date": _date_from_row(exit_row),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "forward_return": round(exit_price / entry_price - 1.0, 8),
        "max_drawdown": round(float(path_drawdowns.min()), 8),
        "max_favorable_return": round(float(path_returns.max()), 8),
        "bars_seen": int(len(frame)),
    }


def _prepare_forward_bars(bars) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame()
    frame = bars.copy()
    frame["timestamp_sort"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"]).sort_values("timestamp_sort")
    return frame.drop(columns=["timestamp_sort"])


def _date_from_row(row) -> str:
    if "local_date" in row and not pd.isna(row["local_date"]):
        return pd.Timestamp(row["local_date"]).strftime("%Y-%m-%d")
    return pd.Timestamp(row["timestamp"]).strftime("%Y-%m-%d")


def _summary(*, candidates_seen: int, results: list[BacktestResult], errors: list[str]) -> dict:
    returns = [result.forward_return for result in results]
    return {
        "candidates_seen": candidates_seen,
        "evaluated_count": len(results),
        "skipped_count": len(errors),
        "hit_rate": _mean([1.0 if result.hit else 0.0 for result in results]),
        "mean_return": _mean(returns),
        "median_return": _median(returns),
        "mean_excess_return": _mean(
            [result.excess_return for result in results if result.excess_return is not None]
        ),
        "best_return": max(returns) if returns else None,
        "worst_return": min(returns) if returns else None,
        "mean_max_drawdown": _mean([result.max_drawdown for result in results if result.max_drawdown is not None]),
        "errors": errors[:20],
    }


def _entry_evaluation_summary(
    *,
    plans: list[EntryPlan],
    reviews: list[EntryPlanReview],
    errors: list[str],
) -> dict:
    plan_by_id = {plan.plan_id: plan for plan in plans}
    joined = [(plan_by_id[review.plan_id], review) for review in reviews if review.plan_id in plan_by_id]
    return {
        "plans_seen": len(plans),
        "reviewed_count": len(reviews),
        "skipped_count": len(errors),
        "triggered_rate": _mean([1.0 if review.triggered else 0.0 for review in reviews]),
        "mean_realized_return": _mean(
            [review.realized_return for review in reviews if review.realized_return is not None]
        ),
        "mean_max_drawdown": _mean([review.max_drawdown for review in reviews if review.max_drawdown is not None]),
        "mean_entry_quality_score": _mean(
            [review.entry_quality_score for review in reviews if review.entry_quality_score is not None]
        ),
        "mean_missed_opportunity": _mean(
            [review.missed_opportunity for review in reviews if review.missed_opportunity is not None]
        ),
        "mean_avoided_chase_loss": _mean(
            [review.avoided_chase_loss for review in reviews if review.avoided_chase_loss is not None]
        ),
        "by_status": _entry_group_summary(joined, key=lambda plan: plan.entry_status),
        "by_mode": _entry_group_summary(joined, key=lambda plan: plan.entry_mode),
        "errors": errors[:20],
    }


def _entry_group_summary(joined: list[tuple[EntryPlan, EntryPlanReview]], key) -> dict:
    groups = {}
    for plan, review in joined:
        groups.setdefault(key(plan), []).append(review)
    return {
        group_key: {
            "count": len(group_reviews),
            "triggered_rate": _mean([1.0 if review.triggered else 0.0 for review in group_reviews]),
            "mean_realized_return": _mean(
                [review.realized_return for review in group_reviews if review.realized_return is not None]
            ),
            "mean_entry_quality_score": _mean(
                [review.entry_quality_score for review in group_reviews if review.entry_quality_score is not None]
            ),
            "mean_missed_opportunity": _mean(
                [review.missed_opportunity for review in group_reviews if review.missed_opportunity is not None]
            ),
            "mean_avoided_chase_loss": _mean(
                [review.avoided_chase_loss for review in group_reviews if review.avoided_chase_loss is not None]
            ),
        }
        for group_key, group_reviews in sorted(groups.items())
    }


def _horizon_to_days(horizon: str) -> int:
    if horizon.endswith("d") and horizon[:-1].isdigit():
        return int(horizon[:-1])
    mapping = {"daily": 1, "weekly": 5, "monthly": 20, "quarterly": 60}
    return mapping.get(horizon, 5)


def _entry_review_bar_range(as_of: str, review_date: str, horizon_days: int) -> tuple[str, str]:
    start = pd.Timestamp(as_of).strftime("%Y-%m-%dT00:00:00Z")
    end_date = max(pd.Timestamp(review_date), pd.Timestamp(as_of) + pd.DateOffset(days=max(7, horizon_days * 3)))
    return start, end_date.strftime("%Y-%m-%dT23:59:59Z")


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(sum(values) / len(values)), 8)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(pd.Series(values).median()), 8)


def _forward_bar_range(as_of: str, horizon_days: int) -> tuple[str, str]:
    as_of_date = pd.Timestamp(as_of)
    end = as_of_date + pd.DateOffset(days=max(7, horizon_days * 3 + 7))
    return as_of_date.strftime("%Y-%m-%dT00:00:00Z"), end.strftime("%Y-%m-%dT23:59:59Z")


def _stable_run_id(screen_run_id: str, as_of: str, horizon_days: int, top_n: int) -> str:
    payload = "|".join([screen_run_id, as_of, str(horizon_days), str(top_n)])
    return f"backtest-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _stable_entry_backtest_run_id(entry_run_id: str, review_date: str, horizon_days: int) -> str:
    payload = "|".join([entry_run_id, review_date, str(horizon_days)])
    return f"entry-backtest-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"
