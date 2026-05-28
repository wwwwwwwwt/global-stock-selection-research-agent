"""Rolling research evaluation for stock-selection screen strategies."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

import pandas as pd

from openstockagent.pipelines.real_data_factors import run_stored_bar_factor_pipeline
from openstockagent.research.evaluation import ScreenBacktestEvaluation, evaluate_screen_run
from openstockagent.research.models import ResearchExperimentDay, ResearchExperimentRun
from openstockagent.screening.runner import ScreeningRunResult, run_screening_pipeline
from openstockagent.screening.scoring import build_default_strategy


@dataclass(frozen=True)
class RollingScreenEvaluationResult:
    experiment: ResearchExperimentRun
    days: list[ResearchExperimentDay] = field(default_factory=list)
    evaluations: list[ScreenBacktestEvaluation] = field(default_factory=list)
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
