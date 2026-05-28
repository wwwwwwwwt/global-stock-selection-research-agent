"""Rolling research evaluation for stock-selection screen strategies."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

import pandas as pd

from openstockagent.entry.runner import run_entry_plan_pipeline
from openstockagent.pipelines.real_data_factors import run_stored_bar_factor_pipeline
from openstockagent.recommendations.runner import run_recommendation_pipeline
from openstockagent.research.evaluation import (
    EntryPlanBacktestEvaluation,
    ScreenBacktestEvaluation,
    evaluate_entry_plan_run,
    evaluate_screen_run,
)
from openstockagent.research.models import ResearchExperimentDay, ResearchExperimentRun
from openstockagent.screening.runner import ScreeningRunResult, run_screening_pipeline
from openstockagent.screening.scoring import build_default_strategy


@dataclass(frozen=True)
class RollingScreenEvaluationResult:
    experiment: ResearchExperimentRun
    days: list[ResearchExperimentDay] = field(default_factory=list)
    evaluations: list[ScreenBacktestEvaluation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RollingEntryEvaluationResult:
    experiment: ResearchExperimentRun
    days: list[ResearchExperimentDay] = field(default_factory=list)
    evaluations: list[EntryPlanBacktestEvaluation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run_rolling_screen_evaluation(
    *,
    universe_id: str,
    start_date: str,
    end_date: str,
    horizon_days: int,
    rebalance_frequency: str,
    top_n: int,
    universe_storage,
    bar_storage,
    factor_storage,
    screening_storage,
    research_storage,
    market_reality_storage=None,
    calendar_storage=None,
    market: str | None = None,
    interval: str = "1d",
    lookback_days: int = 365,
    source: str | None = None,
    adjustment: str | None = "split_adjusted",
    benchmark_instrument_id: str | None = None,
    max_dates: int | None = None,
    experiment_id: str | None = None,
    factor_runner=run_stored_bar_factor_pipeline,
    screening_runner=run_screening_pipeline,
    screen_evaluator=evaluate_screen_run,
) -> RollingScreenEvaluationResult:
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")

    strategy = build_default_strategy(max_candidates=top_n)
    dates = rebalance_dates(
        start_date,
        end_date,
        rebalance_frequency,
        calendar_storage=calendar_storage,
        market=market,
    )
    if max_dates is not None:
        dates = dates[:max_dates]
    experiment_id = experiment_id or _stable_experiment_id(
        universe_id=universe_id,
        start_date=start_date,
        end_date=end_date,
        rebalance_frequency=rebalance_frequency,
        horizon_days=horizon_days,
        top_n=top_n,
        strategy_name=strategy.strategy_name,
        strategy_version=strategy.version,
        benchmark_instrument_id=benchmark_instrument_id,
        market=market,
    )

    experiment_days = []
    evaluations = []
    errors = []
    for as_of in dates:
        try:
            factor_runner(
                universe_id=universe_id,
                as_of=as_of,
                interval=interval,
                lookback_days=lookback_days,
                universe_storage=universe_storage,
                bar_storage=bar_storage,
                factor_storage=factor_storage,
                adjustment=adjustment,
                source=source,
            )
            screening_result = screening_runner(
                universe_id=universe_id,
                as_of=as_of,
                interval=interval,
                universe_storage=universe_storage,
                factor_storage=factor_storage,
                screening_storage=screening_storage,
                strategy=strategy,
                market_reality_storage=market_reality_storage,
            )
            evaluation = screen_evaluator(
                screen_run_id=screening_result.run_id,
                as_of=as_of,
                horizon_days=horizon_days,
                top_n=top_n,
                screening_storage=screening_storage,
                bar_storage=bar_storage,
                evaluation_storage=research_storage,
                universe_id=universe_id,
                interval=interval,
                source=source,
                adjustment=adjustment,
                benchmark_instrument_id=benchmark_instrument_id,
            )
        except Exception as exc:
            errors.append(f"{as_of}: {exc}")
            continue
        evaluations.append(evaluation)
        experiment_days.append(_experiment_day(experiment_id, as_of, screening_result, evaluation))

    summary = _experiment_summary(
        dates_seen=len(dates),
        days=experiment_days,
        evaluations=evaluations,
        errors=errors,
        market=market,
    )
    experiment = ResearchExperimentRun(
        experiment_id=experiment_id,
        universe_id=universe_id,
        start_date=start_date,
        end_date=end_date,
        rebalance_frequency=rebalance_frequency,
        horizon_days=horizon_days,
        top_n=top_n,
        strategy_name=strategy.strategy_name,
        strategy_version=strategy.version,
        benchmark_instrument_id=benchmark_instrument_id,
        status="completed" if summary["evaluated_count"] > 0 else "no_data",
        summary_json=json.dumps(summary, sort_keys=True),
    )
    research_storage.upsert_research_experiment_run(experiment)
    research_storage.delete_research_experiment_days(experiment_id)
    research_storage.upsert_research_experiment_days(experiment_days)
    return RollingScreenEvaluationResult(
        experiment=experiment,
        days=experiment_days,
        evaluations=evaluations,
        errors=errors,
    )


def run_rolling_entry_evaluation(
    *,
    universe_id: str,
    start_date: str,
    end_date: str,
    horizon: str,
    rebalance_frequency: str,
    top_n: int,
    universe_storage,
    bar_storage,
    factor_storage,
    screening_storage,
    recommendation_storage,
    entry_storage,
    research_storage,
    market_reality_storage=None,
    calendar_storage=None,
    market: str | None = None,
    market_regime: str = "unknown",
    interval: str = "1d",
    lookback_days: int = 365,
    source: str | None = None,
    adjustment: str | None = "split_adjusted",
    max_dates: int | None = None,
    experiment_id: str | None = None,
    factor_runner=run_stored_bar_factor_pipeline,
    screening_runner=run_screening_pipeline,
    recommendation_runner=run_recommendation_pipeline,
    entry_runner=run_entry_plan_pipeline,
    entry_evaluator=evaluate_entry_plan_run,
) -> RollingEntryEvaluationResult:
    horizon_days = _horizon_to_days(horizon)
    if horizon_days <= 0:
        raise ValueError("horizon must resolve to positive days")
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")

    strategy = build_default_strategy(max_candidates=top_n)
    dates = rebalance_dates(
        start_date,
        end_date,
        rebalance_frequency,
        calendar_storage=calendar_storage,
        market=market,
    )
    if max_dates is not None:
        dates = dates[:max_dates]
    strategy_name = "rolling_entry_timing"
    strategy_version = "v1"
    experiment_id = experiment_id or _stable_experiment_id(
        universe_id=universe_id,
        start_date=start_date,
        end_date=end_date,
        rebalance_frequency=rebalance_frequency,
        horizon_days=horizon_days,
        top_n=top_n,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        benchmark_instrument_id=None,
        market=market,
    )

    experiment_days = []
    evaluations = []
    errors = []
    for as_of in dates:
        try:
            factor_runner(
                universe_id=universe_id,
                as_of=as_of,
                interval=interval,
                lookback_days=lookback_days,
                universe_storage=universe_storage,
                bar_storage=bar_storage,
                factor_storage=factor_storage,
                adjustment=adjustment,
                source=source,
            )
            screening_result = screening_runner(
                universe_id=universe_id,
                as_of=as_of,
                interval=interval,
                universe_storage=universe_storage,
                factor_storage=factor_storage,
                screening_storage=screening_storage,
                strategy=strategy,
                market_reality_storage=market_reality_storage,
            )
            recommendation_result = recommendation_runner(
                screen_run_id=screening_result.run_id,
                universe_id=universe_id,
                recommendation_date=as_of,
                horizon=horizon,
                screening_storage=screening_storage,
                recommendation_storage=recommendation_storage,
                market_regime=market_regime,
                config={"max_items": top_n},
            )
            entry_result = entry_runner(
                recommendation_run_id=recommendation_result.run_id,
                as_of=as_of,
                horizon=horizon,
                market_regime=market_regime,
                recommendation_storage=recommendation_storage,
                bar_storage=bar_storage,
                entry_storage=entry_storage,
                market_reality_storage=market_reality_storage,
                source=source,
                adjustment=adjustment,
            )
            evaluation = entry_evaluator(
                entry_run_id=entry_result.run.run_id,
                entry_storage=entry_storage,
                bar_storage=bar_storage,
                research_storage=research_storage,
                interval=interval,
                source=source,
                adjustment=adjustment,
            )
        except Exception as exc:
            errors.append(f"{as_of}: {exc}")
            continue
        evaluations.append(evaluation)
        experiment_days.append(
            _entry_experiment_day(
                experiment_id=experiment_id,
                as_of=as_of,
                screening_result=screening_result,
                recommendation_run_id=recommendation_result.run_id,
                entry_run_id=entry_result.run.run_id,
                evaluation=evaluation,
            )
        )

    summary = _entry_experiment_summary(
        dates_seen=len(dates),
        days=experiment_days,
        evaluations=evaluations,
        errors=errors,
        market=market,
        market_regime=market_regime,
    )
    experiment = ResearchExperimentRun(
        experiment_id=experiment_id,
        universe_id=universe_id,
        start_date=start_date,
        end_date=end_date,
        rebalance_frequency=rebalance_frequency,
        horizon_days=horizon_days,
        top_n=top_n,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        benchmark_instrument_id=None,
        status="completed" if summary["reviewed_count"] > 0 else "no_data",
        summary_json=json.dumps(summary, sort_keys=True),
    )
    research_storage.upsert_research_experiment_run(experiment)
    research_storage.delete_research_experiment_days(experiment_id)
    research_storage.upsert_research_experiment_days(experiment_days)
    return RollingEntryEvaluationResult(
        experiment=experiment,
        days=experiment_days,
        evaluations=evaluations,
        errors=errors,
    )


def rebalance_dates(
    start_date: str,
    end_date: str,
    frequency: str,
    calendar_storage=None,
    market: str | None = None,
) -> list[str]:
    stored_dates = _stored_trading_dates(calendar_storage, market, start_date, end_date)
    dates = pd.to_datetime(stored_dates) if stored_dates else pd.bdate_range(start=start_date, end=end_date)
    if dates.empty:
        return []
    if frequency == "daily":
        selected = dates
    elif frequency == "weekly":
        selected = dates.to_series().groupby(dates.to_period("W-FRI")).max()
    elif frequency == "monthly":
        selected = dates.to_series().groupby(dates.to_period("M")).max()
    else:
        raise ValueError(f"Unsupported rebalance frequency: {frequency}")
    return [pd.Timestamp(date).strftime("%Y-%m-%d") for date in selected]


def _experiment_day(
    experiment_id: str,
    as_of: str,
    screening_result: ScreeningRunResult,
    evaluation: ScreenBacktestEvaluation,
) -> ResearchExperimentDay:
    summary = json.loads(evaluation.run.summary_json)
    return ResearchExperimentDay(
        experiment_id=experiment_id,
        as_of=as_of,
        screen_run_id=screening_result.run_id,
        backtest_run_id=evaluation.run.run_id,
        market_context_snapshot_id=None,
        candidate_count=screening_result.selected_count,
        evaluated_count=int(summary.get("evaluated_count", 0) or 0),
        mean_return=summary.get("mean_return"),
        mean_excess_return=summary.get("mean_excess_return"),
        hit_rate=summary.get("hit_rate"),
        summary_json=json.dumps(summary, sort_keys=True),
    )


def _entry_experiment_day(
    *,
    experiment_id: str,
    as_of: str,
    screening_result: ScreeningRunResult,
    recommendation_run_id: str,
    entry_run_id: str,
    evaluation: EntryPlanBacktestEvaluation,
) -> ResearchExperimentDay:
    summary = json.loads(evaluation.run.summary_json)
    day_summary = {
        **summary,
        "recommendation_run_id": recommendation_run_id,
        "entry_run_id": entry_run_id,
    }
    return ResearchExperimentDay(
        experiment_id=experiment_id,
        as_of=as_of,
        screen_run_id=screening_result.run_id,
        backtest_run_id=evaluation.run.run_id,
        market_context_snapshot_id=None,
        candidate_count=screening_result.selected_count,
        evaluated_count=int(summary.get("reviewed_count", 0) or 0),
        mean_return=summary.get("mean_realized_return"),
        mean_excess_return=None,
        hit_rate=summary.get("triggered_rate"),
        summary_json=json.dumps(day_summary, sort_keys=True),
    )


def _experiment_summary(
    *,
    dates_seen: int,
    days: list[ResearchExperimentDay],
    evaluations: list[ScreenBacktestEvaluation],
    errors: list[str],
    market: str | None,
) -> dict:
    results = [result for evaluation in evaluations for result in evaluation.results]
    returns = [result.forward_return for result in results]
    excess_returns = [result.excess_return for result in results if result.excess_return is not None]
    drawdowns = [result.max_drawdown for result in results if result.max_drawdown is not None]
    return {
        "dates_seen": dates_seen,
        "screen_runs_created": len(days),
        "backtest_runs_created": len(evaluations),
        "evaluated_count": len(results),
        "skipped_count": sum(len(evaluation.errors) for evaluation in evaluations) + len(errors),
        "mean_return": _mean(returns),
        "median_return": _median(returns),
        "mean_excess_return": _mean(excess_returns),
        "hit_rate": _mean([1.0 if result.hit else 0.0 for result in results]),
        "mean_max_drawdown": _mean(drawdowns),
        "market": market,
        "errors": errors[:20],
    }


def _entry_experiment_summary(
    *,
    dates_seen: int,
    days: list[ResearchExperimentDay],
    evaluations: list[EntryPlanBacktestEvaluation],
    errors: list[str],
    market: str | None,
    market_regime: str,
) -> dict:
    summaries = [json.loads(evaluation.run.summary_json) for evaluation in evaluations]
    reviewed_counts = [int(summary.get("reviewed_count", 0) or 0) for summary in summaries]
    return {
        "dates_seen": dates_seen,
        "screen_runs_created": len(days),
        "recommendation_runs_created": len(days),
        "entry_runs_created": len(days),
        "backtest_runs_created": len(evaluations),
        "plans_seen": sum(int(summary.get("plans_seen", 0) or 0) for summary in summaries),
        "reviewed_count": sum(reviewed_counts),
        "skipped_count": sum(int(summary.get("skipped_count", 0) or 0) for summary in summaries) + len(errors),
        "triggered_rate": _weighted_summary_mean(summaries, "triggered_rate", "reviewed_count"),
        "mean_realized_return": _weighted_summary_mean(summaries, "mean_realized_return", "reviewed_count"),
        "mean_entry_quality_score": _weighted_summary_mean(
            summaries,
            "mean_entry_quality_score",
            "reviewed_count",
        ),
        "mean_missed_opportunity": _weighted_summary_mean(
            summaries,
            "mean_missed_opportunity",
            "reviewed_count",
        ),
        "mean_avoided_chase_loss": _weighted_summary_mean(
            summaries,
            "mean_avoided_chase_loss",
            "reviewed_count",
        ),
        "by_status": _merge_entry_groups(summaries, "by_status"),
        "by_mode": _merge_entry_groups(summaries, "by_mode"),
        "market": market,
        "market_regime": market_regime,
        "errors": errors[:20],
    }


def _stored_trading_dates(calendar_storage, market: str | None, start_date: str, end_date: str) -> list[str]:
    if calendar_storage is None or market is None:
        return []
    loader = getattr(calendar_storage, "load_trading_dates", None)
    if loader is None:
        return []
    try:
        return loader(market, start_date, end_date)
    except Exception:
        return []


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(sum(values) / len(values)), 8)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(pd.Series(values).median()), 8)


def _weighted_summary_mean(summaries: list[dict], metric: str, count_key: str) -> float | None:
    weighted = [
        (float(summary[metric]), int(summary.get(count_key, 0) or 0))
        for summary in summaries
        if summary.get(metric) is not None and int(summary.get(count_key, 0) or 0) > 0
    ]
    total_weight = sum(weight for _, weight in weighted)
    if total_weight <= 0:
        return None
    return round(sum(value * weight for value, weight in weighted) / total_weight, 8)


def _merge_entry_groups(summaries: list[dict], group_key: str) -> dict:
    merged: dict[str, dict] = {}
    for summary in summaries:
        for key, values in (summary.get(group_key) or {}).items():
            group = merged.setdefault(key, {"count": 0, "_metrics": {}})
            count = int(values.get("count", 0) or 0)
            group["count"] += count
            for metric, metric_value in values.items():
                if metric == "count" or metric_value is None:
                    continue
                group["_metrics"].setdefault(metric, []).append((float(metric_value), count))
    result = {}
    for key, values in sorted(merged.items()):
        result[key] = {"count": values["count"]}
        for metric, weighted_values in values["_metrics"].items():
            total_weight = sum(weight for _, weight in weighted_values)
            result[key][metric] = (
                None
                if total_weight <= 0
                else round(sum(value * weight for value, weight in weighted_values) / total_weight, 8)
            )
    return result


def _horizon_to_days(horizon: str) -> int:
    if horizon.endswith("d") and horizon[:-1].isdigit():
        return int(horizon[:-1])
    return {"daily": 1, "weekly": 5, "monthly": 20, "quarterly": 60}.get(horizon, 5)


def _stable_experiment_id(
    *,
    universe_id: str,
    start_date: str,
    end_date: str,
    rebalance_frequency: str,
    horizon_days: int,
    top_n: int,
    strategy_name: str,
    strategy_version: str,
    benchmark_instrument_id: str | None,
    market: str | None,
) -> str:
    payload = "|".join(
        [
            universe_id,
            start_date,
            end_date,
            rebalance_frequency,
            str(horizon_days),
            str(top_n),
            strategy_name,
            strategy_version,
            benchmark_instrument_id or "",
            market or "",
        ]
    )
    return f"research-exp-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"
