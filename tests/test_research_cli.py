import json
import tomllib

from click.testing import CliRunner


def test_stock_research_entrypoint_targets_packaged_module():
    with open("pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["scripts"]["stock-research"] == "openstockagent.cli.stock_research:main"


def test_research_evaluate_screen_cli_runs_pipeline(monkeypatch):
    from openstockagent.cli import stock_research
    from openstockagent.research.evaluation import ScreenBacktestEvaluation
    from openstockagent.research.models import BacktestResult, BacktestRun

    calls = {}

    def fake_evaluate_screen_run(**kwargs):
        calls.update(kwargs)
        return ScreenBacktestEvaluation(
            run=BacktestRun(
                run_id="backtest-test",
                source_type="screen",
                source_run_id=kwargs["screen_run_id"],
                universe_id=kwargs["universe_id"],
                as_of=kwargs["as_of"],
                horizon_days=kwargs["horizon_days"],
                top_n=kwargs["top_n"],
                benchmark_instrument_id=kwargs["benchmark_instrument_id"],
                status="completed",
                summary_json=json.dumps(
                    {
                        "evaluated_count": 1,
                        "skipped_count": 0,
                        "hit_rate": 1.0,
                        "mean_return": 0.05,
                        "median_return": 0.05,
                        "mean_excess_return": 0.04,
                    }
                ),
            ),
            results=[
                BacktestResult(
                    run_id="backtest-test",
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
            ],
        )

    monkeypatch.setattr(stock_research, "evaluate_screen_run", fake_evaluate_screen_run)
    monkeypatch.setattr(stock_research, "MySQLScreeningStorage", lambda config: object())
    monkeypatch.setattr(stock_research, "MySQLMarketDataStorage", lambda config: object())
    monkeypatch.setattr(stock_research, "MySQLResearchStorage", lambda config: object())

    result = CliRunner().invoke(
        stock_research.main,
        [
            "evaluate-screen",
            "--screen-run-id",
            "screen-test",
            "--as-of",
            "2026-05-20",
            "--horizon-days",
            "2",
            "--top-n",
            "5",
            "--universe",
            "cn_core",
            "--interval",
            "1d",
            "--benchmark-instrument-id",
            "EQUITY:CN:000300",
        ],
    )

    assert result.exit_code == 0
    assert calls["screen_run_id"] == "screen-test"
    assert calls["as_of"] == "2026-05-20"
    assert calls["horizon_days"] == 2
    assert calls["top_n"] == 5
    assert calls["universe_id"] == "cn_core"
    assert calls["interval"] == "1d"
    assert calls["benchmark_instrument_id"] == "EQUITY:CN:000300"
    assert "Screen evaluation complete" in result.output
    assert "mean_excess_return=0.040000" in result.output
    assert "1. EQUITY:CN:000001 return=0.050000 excess=0.040000" in result.output


def test_research_init_db_cli_initializes_storage(monkeypatch):
    from openstockagent.cli import stock_research

    created = {}

    class FakeResearchStorage:
        def __init__(self, config):
            created["config"] = config

    monkeypatch.setattr(stock_research, "MySQLResearchStorage", FakeResearchStorage)

    result = CliRunner().invoke(stock_research.main, ["init-db"])

    assert result.exit_code == 0
    assert created["config"].database == "openstockagent"
    assert "Research storage initialized" in result.output


def test_research_rolling_screen_cli_runs_pipeline(monkeypatch):
    from openstockagent.cli import stock_research
    from openstockagent.research.models import ResearchExperimentDay, ResearchExperimentRun
    from openstockagent.research.rolling import RollingScreenEvaluationResult

    calls = {}

    def fake_run_rolling_screen_evaluation(**kwargs):
        calls.update(kwargs)
        return RollingScreenEvaluationResult(
            experiment=ResearchExperimentRun(
                experiment_id="research-exp-test",
                universe_id=kwargs["universe_id"],
                start_date=kwargs["start_date"],
                end_date=kwargs["end_date"],
                rebalance_frequency=kwargs["rebalance_frequency"],
                horizon_days=kwargs["horizon_days"],
                top_n=kwargs["top_n"],
                strategy_name="default",
                strategy_version="v1",
                benchmark_instrument_id=kwargs["benchmark_instrument_id"],
                status="completed",
                summary_json=json.dumps(
                    {
                        "dates_seen": 2,
                        "screen_runs_created": 2,
                        "backtest_runs_created": 2,
                        "evaluated_count": 4,
                        "skipped_count": 0,
                        "hit_rate": 0.75,
                        "mean_return": 0.04,
                        "mean_excess_return": 0.02,
                        "mean_max_drawdown": -0.03,
                    }
                ),
            ),
            days=[
                ResearchExperimentDay(
                    experiment_id="research-exp-test",
                    as_of="2026-05-22",
                    screen_run_id="screen-test",
                    backtest_run_id="backtest-test",
                    market_context_snapshot_id=None,
                    candidate_count=3,
                    evaluated_count=2,
                    mean_return=0.04,
                    mean_excess_return=0.02,
                    hit_rate=0.5,
                    summary_json="{}",
                )
            ],
        )

    monkeypatch.setattr(stock_research, "run_rolling_screen_evaluation", fake_run_rolling_screen_evaluation)
    monkeypatch.setattr(stock_research, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(stock_research, "MySQLMarketDataStorage", lambda config: object())
    monkeypatch.setattr(stock_research, "MySQLFactorStorage", lambda config: object())
    monkeypatch.setattr(stock_research, "MySQLScreeningStorage", lambda config: object())
    monkeypatch.setattr(stock_research, "MySQLResearchStorage", lambda config: object())
    monkeypatch.setattr(stock_research, "MySQLMarketRealityStorage", lambda config: object())

    result = CliRunner().invoke(
        stock_research.main,
        [
            "rolling-screen",
            "--universe",
            "cn_core",
            "--start-date",
            "2026-05-18",
            "--end-date",
            "2026-05-29",
            "--horizon-days",
            "2",
            "--rebalance",
            "weekly",
            "--top-n",
            "3",
            "--lookback-days",
            "180",
            "--benchmark-instrument-id",
            "EQUITY:CN:000300",
            "--max-dates",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert calls["universe_id"] == "cn_core"
    assert calls["start_date"] == "2026-05-18"
    assert calls["end_date"] == "2026-05-29"
    assert calls["horizon_days"] == 2
    assert calls["rebalance_frequency"] == "weekly"
    assert calls["top_n"] == 3
    assert calls["lookback_days"] == 180
    assert calls["benchmark_instrument_id"] == "EQUITY:CN:000300"
    assert calls["max_dates"] == 2
    assert "Rolling screen evaluation complete" in result.output
    assert "experiment_id=research-exp-test" in result.output
    assert "hit_rate=0.750000" in result.output
