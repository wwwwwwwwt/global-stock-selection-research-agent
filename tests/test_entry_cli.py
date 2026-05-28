from click.testing import CliRunner
import tomllib

from openstockagent.entry.models import EntryPlan, EntryPlanRun, EntryPlanRunResult


def test_stock_entry_entrypoint_targets_packaged_module():
    with open("pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["scripts"]["stock-entry"] == "openstockagent.cli.run_entry:main"


def test_entry_from_recommendation_cli_builds_and_prints_plans(monkeypatch):
    from openstockagent.cli import run_entry

    called = {}
    plan = EntryPlan(
        plan_id="entry-plan-test",
        run_id="entry-run-test",
        recommendation_id="rec-item-test",
        instrument_id="EQUITY:CN:000001",
        rank=1,
        entry_mode="breakout_buy",
        entry_status="ready",
        reference_price=10.0,
        trigger_price=10.5,
        pullback_price=9.8,
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
    run = EntryPlanRun(
        run_id="entry-run-test",
        recommendation_run_id="rec-run-test",
        as_of="2026-05-27",
        horizon="5d",
        market_regime="neutral",
        strategy_name="daily_entry_timing",
        strategy_version="v1",
        status="complete",
        summary_json='{"ready_count": 1, "wait_count": 0, "avoid_count": 0, "invalid_count": 0}',
    )

    class FakeStorage:
        def __init__(self, config):
            self.config = config

    def fake_pipeline(**kwargs):
        called.update(kwargs)
        return EntryPlanRunResult(run=run, plans=[plan])

    monkeypatch.setattr(run_entry, "MySQLRecommendationStorage", FakeStorage)
    monkeypatch.setattr(run_entry, "MySQLMarketDataStorage", FakeStorage)
    monkeypatch.setattr(run_entry, "MySQLEntryStorage", FakeStorage)
    monkeypatch.setattr(run_entry, "MySQLMarketRealityStorage", FakeStorage)
    monkeypatch.setattr(run_entry, "run_entry_plan_pipeline", fake_pipeline)

    result = CliRunner().invoke(
        run_entry.main,
        [
            "from-recommendation",
            "rec-run-test",
            "--as-of",
            "2026-05-27",
            "--horizon",
            "5d",
            "--market-regime",
            "neutral",
        ],
    )

    assert result.exit_code == 0
    assert called["recommendation_run_id"] == "rec-run-test"
    assert called["source"] == "tushare"
    assert "Entry plan run complete" in result.output
    assert "mode=breakout_buy" in result.output
