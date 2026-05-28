import json

import pandas as pd

from openstockagent.database.mysql import MySQLConfig
from openstockagent.entry.models import EntryPlan, EntryPlanRun
from openstockagent.research.evaluation import evaluate_entry_plan_run, evaluate_screen_run
from openstockagent.research.models import BacktestResult, BacktestRun, ResearchExperimentDay, ResearchExperimentRun
from openstockagent.research.storage import MySQLResearchStorage
from openstockagent.screening.models import ScreenResult


def test_evaluate_screen_run_computes_forward_returns_and_persists_results():
    screening_storage = FakeScreeningStorage(
        [
            _screen_result("screen-test", "EQUITY:CN:000001", 1, 0.90),
            _screen_result("screen-test", "EQUITY:CN:000002", 2, 0.80),
            _screen_result("screen-test", "EQUITY:CN:000003", 3, 0.70),
        ]
    )
    bar_storage = FakeBarStorage(
        {
            "EQUITY:CN:000001": _bars(["2026-05-20", "2026-05-21", "2026-05-22"], [100, 110, 104]),
            "EQUITY:CN:000002": _bars(["2026-05-20", "2026-05-21", "2026-05-22"], [50, 49, 48]),
            "EQUITY:CN:000300": _bars(["2026-05-20", "2026-05-21", "2026-05-22"], [1000, 1000, 1020]),
        }
    )
    evaluation_storage = FakeEvaluationStorage()

    result = evaluate_screen_run(
        screen_run_id="screen-test",
        as_of="2026-05-20",
        horizon_days=2,
        top_n=2,
        universe_id="cn_core",
        benchmark_instrument_id="EQUITY:CN:000300",
        screening_storage=screening_storage,
        bar_storage=bar_storage,
        evaluation_storage=evaluation_storage,
        run_id="backtest-test",
    )

    summary = json.loads(result.run.summary_json)
    assert result.run.status == "completed"
    assert result.run.universe_id == "cn_core"
    assert summary["candidates_seen"] == 2
    assert summary["evaluated_count"] == 2
    assert summary["skipped_count"] == 0
    assert summary["hit_rate"] == 0.5
    assert summary["mean_return"] == 0.0
    assert summary["mean_excess_return"] == -0.02
    assert [item.instrument_id for item in result.results] == ["EQUITY:CN:000001", "EQUITY:CN:000002"]
    assert result.results[0].forward_return == 0.04
    assert result.results[0].benchmark_return == 0.02
    assert result.results[0].excess_return == 0.02
    assert result.results[0].max_drawdown == -0.05454545
    assert result.results[0].max_favorable_return == 0.1
    assert result.results[1].forward_return == -0.04
    assert evaluation_storage.runs == [result.run]
    assert evaluation_storage.deleted_run_ids == ["backtest-test"]
    assert evaluation_storage.results == result.results


def test_evaluate_screen_run_records_no_data_when_forward_bars_are_missing():
    result = evaluate_screen_run(
        screen_run_id="screen-test",
        as_of="2026-05-20",
        horizon_days=2,
        top_n=1,
        screening_storage=FakeScreeningStorage([_screen_result("screen-test", "EQUITY:CN:000001", 1, 0.90)]),
        bar_storage=FakeBarStorage({"EQUITY:CN:000001": _bars(["2026-05-20"], [100])}),
    )

    summary = json.loads(result.run.summary_json)
    assert result.run.status == "no_data"
    assert result.results == []
    assert summary["evaluated_count"] == 0
    assert summary["skipped_count"] == 1
    assert result.errors == ["EQUITY:CN:000001: insufficient_forward_bars"]


def test_evaluate_entry_plan_run_reviews_plans_and_summarizes_entry_quality():
    ready_plan = _entry_plan("entry-plan-ready", "EQUITY:CN:000001", "rec-ready", "breakout_buy", "ready")
    avoid_plan = _entry_plan("entry-plan-avoid", "EQUITY:CN:000002", "rec-avoid", "avoid_chase", "avoid")
    entry_storage = FakeEntryStorage([ready_plan, avoid_plan])
    bar_storage = FakeBarStorage(
        {
            "EQUITY:CN:000001": _entry_bars(
                ["2026-05-27", "2026-05-28", "2026-05-29", "2026-06-03"],
                [10.0, 10.8, 11.2, 11.5],
                [10.2, 10.9, 11.3, 11.6],
                [9.8, 10.4, 10.9, 11.1],
            ),
            "EQUITY:CN:000002": _entry_bars(
                ["2026-05-27", "2026-05-28", "2026-05-29", "2026-06-03"],
                [20.0, 19.0, 18.8, 18.0],
                [20.2, 19.2, 19.0, 18.2],
                [19.8, 18.8, 18.5, 17.8],
            ),
        }
    )
    research_storage = FakeEvaluationStorage()

    result = evaluate_entry_plan_run(
        entry_run_id="entry-run-test",
        entry_storage=entry_storage,
        bar_storage=bar_storage,
        research_storage=research_storage,
        run_id="entry-backtest-test",
    )

    summary = json.loads(result.run.summary_json)
    assert result.run.source_type == "entry"
    assert result.run.source_run_id == "entry-run-test"
    assert result.run.horizon_days == 5
    assert result.run.top_n == 2
    assert summary["plans_seen"] == 2
    assert summary["reviewed_count"] == 2
    assert summary["triggered_rate"] == 0.5
    assert summary["by_status"]["ready"]["count"] == 1
    assert summary["by_status"]["avoid"]["count"] == 1
    assert summary["mean_entry_quality_score"] is not None
    assert entry_storage.reviews == result.reviews
    assert research_storage.runs == [result.run]


def test_mysql_research_storage_creates_upserts_deletes_and_loads_results():
    factory = FakeConnectionFactory(
        rows=[
            {
                "run_id": "backtest-test",
                "instrument_id": "EQUITY:CN:000001",
                "rank_position": 1,
                "source_score": 0.9,
                "entry_date": "2026-05-20",
                "exit_date": "2026-05-22",
                "entry_price": 100,
                "exit_price": 105,
                "forward_return": 0.05,
                "benchmark_return": 0.01,
                "excess_return": 0.04,
                "max_drawdown": -0.02,
                "max_favorable_return": 0.05,
                "hit": 1,
                "evidence_json": "{}",
            }
        ]
    )
    storage = MySQLResearchStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
    )

    run = BacktestRun(
        run_id="backtest-test",
        source_type="screen",
        source_run_id="screen-test",
        universe_id="cn_core",
        as_of="2026-05-20",
        horizon_days=2,
        top_n=1,
        benchmark_instrument_id="EQUITY:CN:000300",
        status="completed",
        summary_json="{}",
    )
    storage.upsert_backtest_run(run)
    storage.delete_backtest_results(run.run_id)
    storage.upsert_backtest_results(
        [
            BacktestResult(
                run_id=run.run_id,
                instrument_id="EQUITY:CN:000001",
                rank=1,
                source_score=0.9,
                entry_date="2026-05-20",
                exit_date="2026-05-22",
                entry_price=100,
                exit_price=105,
                forward_return=0.05,
                benchmark_return=0.01,
                excess_return=0.04,
                max_drawdown=-0.02,
                max_favorable_return=0.05,
                hit=True,
            )
        ]
    )
    experiment = ResearchExperimentRun(
        experiment_id="research-exp-test",
        universe_id="cn_core",
        start_date="2026-05-20",
        end_date="2026-05-29",
        rebalance_frequency="weekly",
        horizon_days=2,
        top_n=1,
        strategy_name="default",
        strategy_version="v1",
        benchmark_instrument_id="EQUITY:CN:000300",
        status="completed",
        summary_json="{}",
    )
    storage.upsert_research_experiment_run(experiment)
    storage.delete_research_experiment_days(experiment.experiment_id)
    storage.upsert_research_experiment_days(
        [
            ResearchExperimentDay(
                experiment_id=experiment.experiment_id,
                as_of="2026-05-22",
                screen_run_id="screen-test",
                backtest_run_id=run.run_id,
                market_context_snapshot_id=None,
                candidate_count=10,
                evaluated_count=1,
                mean_return=0.05,
                mean_excess_return=0.04,
                hit_rate=1.0,
                summary_json="{}",
            )
        ]
    )
    loaded = storage.load_backtest_results(run.run_id)

    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS backtest_runs" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS backtest_results" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS research_experiment_runs" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS research_experiment_days" in executed_sql
    assert "rank_position INTEGER NOT NULL" in executed_sql
    assert "DELETE FROM backtest_results WHERE run_id = %s" in executed_sql
    assert "DELETE FROM research_experiment_days WHERE experiment_id = %s" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql
    assert loaded[0].instrument_id == "EQUITY:CN:000001"
    assert loaded[0].excess_return == 0.04
    assert loaded[0].hit is True


def _screen_result(run_id: str, instrument_id: str, rank: int, score: float) -> ScreenResult:
    return ScreenResult(
        run_id=run_id,
        instrument_id=instrument_id,
        rank=rank,
        selected=True,
        total_score=score,
        score_breakdown_json="{}",
        reason_json="{}",
        risk_json="{}",
        evidence_refs_json="{}",
    )


def _bars(dates: list[str], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [f"{date}T00:00:00Z" for date in dates],
            "local_date": dates,
            "close": closes,
        }
    )


def _entry_bars(dates: list[str], closes: list[float], highs: list[float], lows: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [f"{date}T00:00:00Z" for date in dates],
            "local_date": dates,
            "close": closes,
            "high": highs,
            "low": lows,
        }
    )


def _entry_plan(plan_id: str, instrument_id: str, recommendation_id: str, mode: str, status: str) -> EntryPlan:
    return EntryPlan(
        plan_id=plan_id,
        run_id="entry-run-test",
        recommendation_id=recommendation_id,
        instrument_id=instrument_id,
        rank=1,
        entry_mode=mode,
        entry_status=status,
        reference_price=10.0 if instrument_id.endswith("000001") else 20.0,
        trigger_price=10.5 if status == "ready" else None,
        pullback_price=None,
        stop_loss=9.5,
        take_profit=11.5,
        time_limit_date="2026-06-03",
        confidence=0.8,
        reason_json="{}",
        confirmation_json="{}",
        invalidation_json="{}",
        risk_json="{}",
        evidence_refs_json="{}",
    )


class FakeScreeningStorage:
    def __init__(self, results):
        self.results = results

    def load_screen_results(self, run_id, selected_only=False):
        assert run_id == "screen-test"
        assert selected_only is True
        return self.results


class FakeBarStorage:
    def __init__(self, bars_by_instrument):
        self.bars_by_instrument = bars_by_instrument
        self.calls = []

    def load_bars(self, instrument_id, interval, start, end, source=None, adjustment=None):
        self.calls.append((instrument_id, interval, start, end, source, adjustment))
        return self.bars_by_instrument.get(instrument_id, pd.DataFrame())


class FakeEvaluationStorage:
    def __init__(self):
        self.runs = []
        self.deleted_run_ids = []
        self.results = []

    def upsert_backtest_run(self, run):
        self.runs.append(run)

    def delete_backtest_results(self, run_id):
        self.deleted_run_ids.append(run_id)
        return 0

    def upsert_backtest_results(self, results):
        self.results.extend(results)
        return len(results)


class FakeEntryStorage:
    def __init__(self, plans):
        self.run = EntryPlanRun(
            run_id="entry-run-test",
            recommendation_run_id="rec-run-test",
            as_of="2026-05-27",
            horizon="5d",
            market_regime="neutral",
            strategy_name="daily_entry_timing",
            strategy_version="v1",
            status="complete",
            summary_json="{}",
        )
        self.plans = plans
        self.reviews = []

    def load_entry_plan_run(self, run_id):
        assert run_id == "entry-run-test"
        return self.run

    def load_entry_plans(self, run_id, ready_only=False):
        assert run_id == "entry-run-test"
        if ready_only:
            return [plan for plan in self.plans if plan.entry_status == "ready"]
        return self.plans

    def upsert_entry_plan_review(self, review):
        self.reviews.append(review)


class FakeConnectionFactory:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed_sql = []
        self.executed_params = []

    def __call__(self, config):
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, factory):
        self.factory = factory

    def cursor(self):
        return FakeCursor(self.factory)

    def commit(self):
        pass

    def close(self):
        pass


class FakeCursor:
    def __init__(self, factory):
        self.factory = factory

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        pass

    def execute(self, sql, params=None):
        self.factory.executed_sql.append(sql)
        self.factory.executed_params.append(params)
        return 1

    def executemany(self, sql, params):
        self.factory.executed_sql.append(sql)
        self.factory.executed_params.extend(params)

    def fetchall(self):
        return self.factory.rows
