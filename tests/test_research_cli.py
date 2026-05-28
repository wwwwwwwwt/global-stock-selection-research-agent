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
