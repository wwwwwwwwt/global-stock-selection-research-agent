import json

from openstockagent.research.evaluation import ScreenBacktestEvaluation
from openstockagent.research.models import BacktestResult, BacktestRun
from openstockagent.research.rolling import rebalance_dates, run_rolling_screen_evaluation
from openstockagent.screening.models import ScreenResult
from openstockagent.screening.runner import ScreeningRunResult


def test_rebalance_dates_supports_daily_weekly_and_monthly():
    assert rebalance_dates("2026-05-18", "2026-05-20", "daily") == [
        "2026-05-18",
        "2026-05-19",
        "2026-05-20",
    ]
    assert rebalance_dates("2026-05-18", "2026-05-29", "weekly") == [
        "2026-05-22",
        "2026-05-29",
    ]
    assert rebalance_dates("2026-05-01", "2026-06-05", "monthly") == [
        "2026-05-29",
        "2026-06-05",
    ]


def test_rebalance_dates_use_stored_trading_calendar_when_available():
    calendar_storage = FakeCalendarStorage(
        ["2026-05-18", "2026-05-19", "2026-05-21", "2026-05-22", "2026-05-25", "2026-05-27"]
    )

    assert rebalance_dates(
        "2026-05-18",
        "2026-05-29",
        "weekly",
        calendar_storage=calendar_storage,
        market="CN",
    ) == ["2026-05-22", "2026-05-27"]
    assert calendar_storage.calls == [("CN", "2026-05-18", "2026-05-29")]


def test_run_rolling_screen_evaluation_persists_experiment_days():
    research_storage = FakeResearchStorage()
    calls = {"factor_dates": [], "screen_dates": [], "evaluation_dates": []}

    def fake_factor_runner(**kwargs):
        calls["factor_dates"].append(kwargs["as_of"])

    def fake_screening_runner(**kwargs):
        as_of = kwargs["as_of"]
        calls["screen_dates"].append(as_of)
        return ScreeningRunResult(
            run_id=f"screen-{as_of}",
            universe_id=kwargs["universe_id"],
            trade_date=as_of,
            interval=kwargs["interval"],
            candidates_seen=2,
            factor_values_seen=18,
            ranked_count=2,
            selected_count=1,
            filtered_count=0,
            errors=[],
            results=[
                ScreenResult(
                    run_id=f"screen-{as_of}",
                    instrument_id="EQUITY:CN:000001",
                    rank=1,
                    selected=True,
                    total_score=0.9,
                    score_breakdown_json="{}",
                    reason_json="{}",
                    risk_json="{}",
                    evidence_refs_json="{}",
                )
            ],
        )

    def fake_screen_evaluator(**kwargs):
        as_of = kwargs["as_of"]
        calls["evaluation_dates"].append(as_of)
        return ScreenBacktestEvaluation(
            run=BacktestRun(
                run_id=f"backtest-{as_of}",
                source_type="screen",
                source_run_id=kwargs["screen_run_id"],
                universe_id=kwargs["universe_id"],
                as_of=as_of,
                horizon_days=kwargs["horizon_days"],
                top_n=kwargs["top_n"],
                benchmark_instrument_id=kwargs["benchmark_instrument_id"],
                status="completed",
                summary_json=json.dumps(
                    {
                        "candidates_seen": 1,
                        "evaluated_count": 1,
                        "skipped_count": 0,
                        "hit_rate": 1.0,
                        "mean_return": 0.05,
                        "median_return": 0.05,
                        "mean_excess_return": 0.03,
                        "mean_max_drawdown": -0.02,
                    }
                ),
            ),
            results=[
                BacktestResult(
                    run_id=f"backtest-{as_of}",
                    instrument_id="EQUITY:CN:000001",
                    rank=1,
                    source_score=0.9,
                    entry_date=as_of,
                    exit_date="2026-06-01",
                    entry_price=100,
                    exit_price=105,
                    forward_return=0.05,
                    benchmark_return=0.02,
                    excess_return=0.03,
                    max_drawdown=-0.02,
                    max_favorable_return=0.07,
                    hit=True,
                )
            ],
        )

    result = run_rolling_screen_evaluation(
        universe_id="cn_core",
        start_date="2026-05-18",
        end_date="2026-05-29",
        horizon_days=2,
        rebalance_frequency="weekly",
        top_n=1,
        universe_storage=object(),
        bar_storage=object(),
        factor_storage=object(),
        screening_storage=object(),
        research_storage=research_storage,
        benchmark_instrument_id="EQUITY:CN:000300",
        experiment_id="research-exp-test",
        factor_runner=fake_factor_runner,
        screening_runner=fake_screening_runner,
        screen_evaluator=fake_screen_evaluator,
    )

    summary = json.loads(result.experiment.summary_json)
    assert calls["factor_dates"] == ["2026-05-22", "2026-05-29"]
    assert calls["screen_dates"] == ["2026-05-22", "2026-05-29"]
    assert calls["evaluation_dates"] == ["2026-05-22", "2026-05-29"]
    assert result.experiment.experiment_id == "research-exp-test"
    assert result.experiment.status == "completed"
    assert summary["dates_seen"] == 2
    assert summary["screen_runs_created"] == 2
    assert summary["backtest_runs_created"] == 2
    assert summary["evaluated_count"] == 2
    assert summary["hit_rate"] == 1.0
    assert summary["mean_return"] == 0.05
    assert summary["mean_excess_return"] == 0.03
    assert research_storage.run == result.experiment
    assert research_storage.deleted_experiment_ids == ["research-exp-test"]
    assert [day.as_of for day in research_storage.days] == ["2026-05-22", "2026-05-29"]
    assert research_storage.days[0].screen_run_id == "screen-2026-05-22"
    assert research_storage.days[0].backtest_run_id == "backtest-2026-05-22"


class FakeResearchStorage:
    def __init__(self):
        self.run = None
        self.days = []
        self.deleted_experiment_ids = []

    def upsert_research_experiment_run(self, run):
        self.run = run

    def delete_research_experiment_days(self, experiment_id):
        self.deleted_experiment_ids.append(experiment_id)
        return 0

    def upsert_research_experiment_days(self, days):
        self.days.extend(days)
        return len(days)


class FakeCalendarStorage:
    def __init__(self, dates):
        self.dates = dates
        self.calls = []

    def load_trading_dates(self, market, start_date, end_date):
        self.calls.append((market, start_date, end_date))
        return self.dates
