from click.testing import CliRunner
import tomllib


def test_stock_portfolio_entrypoint_targets_packaged_module():
    with open("pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["scripts"]["stock-portfolio"].startswith("openstockagent.")


def test_portfolio_decide_cli_builds_and_persists_decision(monkeypatch):
    from openstockagent.cli import run_portfolio
    from openstockagent.recommendations.models import RecommendationItem

    saved = {"accounts": [], "policies": [], "decisions": [], "allocations": []}
    item = RecommendationItem(
        recommendation_id="rec-item-test",
        run_id="rec-run-test",
        instrument_id="EQUITY:US:AAPL",
        rank=1,
        action="buy_candidate",
        source_screen_rank=1,
        source_screen_score=0.82,
        expected_return=0.02,
        expected_risk=0.1,
        confidence=0.9,
        thesis_json="{}",
        confirmation_json="{}",
        invalidation_json="{}",
        risk_json="{}",
        evidence_refs_json="{}",
    )

    class FakeRecommendationStorage:
        def __init__(self, config):
            self.config = config

        def load_recommendation_items(self, run_id, actionable_only=False):
            assert run_id == "rec-run-test"
            assert actionable_only is True
            return [item]

    class FakePortfolioStorage:
        def __init__(self, config):
            self.config = config

        def upsert_account(self, account):
            saved["accounts"].append(account)

        def upsert_policy(self, policy):
            saved["policies"].append(policy)

        def upsert_decision(self, decision):
            saved["decisions"].append(decision)

        def load_positions(self, account_id):
            saved["loaded_positions_for"] = account_id
            return []

        def delete_target_allocations(self, decision_id):
            saved["deleted"] = decision_id

        def upsert_target_allocations(self, allocations):
            saved["allocations"].extend(allocations)
            return len(allocations)

    monkeypatch.setattr(run_portfolio, "MySQLRecommendationStorage", FakeRecommendationStorage)
    monkeypatch.setattr(run_portfolio, "MySQLPortfolioStorage", FakePortfolioStorage)

    result = CliRunner().invoke(
        run_portfolio.main,
        [
            "decide",
            "rec-run-test",
            "--account-id",
            "paper",
            "--capital",
            "100000",
            "--decision-date",
            "2026-05-25",
            "--market-regime",
            "neutral",
        ],
    )

    assert result.exit_code == 0
    assert saved["accounts"][0].account_id == "paper"
    assert saved["loaded_positions_for"] == "paper"
    assert saved["policies"][0].policy_id == "balanced_v1"
    assert saved["policies"][0].allow_watch_allocation is False
    assert saved["decisions"][0].action == "allocate"
    assert saved["allocations"][0].instrument_id == "EQUITY:US:AAPL"
    assert "Portfolio decision complete" in result.output


def test_portfolio_decide_cli_can_enable_watch_allocation(monkeypatch):
    from openstockagent.cli import run_portfolio
    from openstockagent.recommendations.models import RecommendationItem

    saved = {"policies": [], "decisions": [], "allocations": []}
    item = RecommendationItem(
        recommendation_id="rec-item-test",
        run_id="rec-run-test",
        instrument_id="EQUITY:US:AAPL",
        rank=1,
        action="watch",
        source_screen_rank=1,
        source_screen_score=0.62,
        expected_return=0.01,
        expected_risk=0.1,
        confidence=0.9,
        thesis_json="{}",
        confirmation_json="{}",
        invalidation_json="{}",
        risk_json="{}",
        evidence_refs_json="{}",
    )

    class FakeRecommendationStorage:
        def __init__(self, config):
            self.config = config

        def load_recommendation_items(self, run_id, actionable_only=False):
            return [item]

    class FakePortfolioStorage:
        def __init__(self, config):
            self.config = config

        def upsert_account(self, account):
            pass

        def upsert_policy(self, policy):
            saved["policies"].append(policy)

        def upsert_decision(self, decision):
            saved["decisions"].append(decision)

        def load_positions(self, account_id):
            return []

        def delete_target_allocations(self, decision_id):
            return 0

        def upsert_target_allocations(self, allocations):
            saved["allocations"].extend(allocations)
            return len(allocations)

    monkeypatch.setattr(run_portfolio, "MySQLRecommendationStorage", FakeRecommendationStorage)
    monkeypatch.setattr(run_portfolio, "MySQLPortfolioStorage", FakePortfolioStorage)

    result = CliRunner().invoke(
        run_portfolio.main,
        [
            "decide",
            "rec-run-test",
            "--capital",
            "100000",
            "--decision-date",
            "2026-05-25",
            "--market-regime",
            "neutral",
            "--allow-watch-allocation",
        ],
    )

    assert result.exit_code == 0
    assert saved["policies"][0].allow_watch_allocation is True
    assert saved["decisions"][0].action == "allocate"
    assert saved["allocations"][0].action == "watch"


def test_portfolio_decide_cli_can_allocate_only_ready_entry_plans(monkeypatch):
    from openstockagent.cli import run_portfolio
    from openstockagent.entry.models import EntryPlan
    from openstockagent.portfolio.models import PortfolioPosition
    from openstockagent.recommendations.models import RecommendationItem

    saved = {"decisions": [], "allocations": []}
    ready_item = RecommendationItem(
        recommendation_id="rec-ready",
        run_id="rec-run-test",
        instrument_id="EQUITY:US:AAPL",
        rank=1,
        action="buy_candidate",
        source_screen_rank=1,
        source_screen_score=0.82,
        expected_return=0.02,
        expected_risk=0.1,
        confidence=0.9,
        thesis_json="{}",
        confirmation_json="{}",
        invalidation_json="{}",
        risk_json="{}",
        evidence_refs_json="{}",
    )
    wait_item = RecommendationItem(
        recommendation_id="rec-wait",
        run_id="rec-run-test",
        instrument_id="EQUITY:US:MSFT",
        rank=2,
        action="buy_candidate",
        source_screen_rank=2,
        source_screen_score=0.80,
        expected_return=0.02,
        expected_risk=0.1,
        confidence=0.88,
        thesis_json="{}",
        confirmation_json="{}",
        invalidation_json="{}",
        risk_json="{}",
        evidence_refs_json="{}",
    )
    ready_plan = EntryPlan(
        plan_id="entry-plan-ready",
        run_id="entry-run-test",
        recommendation_id="rec-ready",
        instrument_id="EQUITY:US:AAPL",
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

    class FakeRecommendationStorage:
        def __init__(self, config):
            self.config = config

        def load_recommendation_items(self, run_id, actionable_only=False):
            return [ready_item, wait_item]

    class FakeEntryStorage:
        def __init__(self, config):
            self.config = config

        def load_entry_plans(self, run_id, ready_only=False):
            assert run_id == "entry-run-test"
            assert ready_only is True
            return [ready_plan]

    class FakePortfolioStorage:
        def __init__(self, config):
            self.config = config

        def upsert_account(self, account):
            pass

        def upsert_policy(self, policy):
            pass

        def upsert_decision(self, decision):
            saved["decisions"].append(decision)

        def load_positions(self, account_id):
            return [PortfolioPosition(account_id, "EQUITY:US:OLD", 10, 100, 10_000)]

        def delete_target_allocations(self, decision_id):
            return 0

        def upsert_target_allocations(self, allocations):
            saved["allocations"].extend(allocations)
            return len(allocations)

    monkeypatch.setattr(run_portfolio, "MySQLRecommendationStorage", FakeRecommendationStorage)
    monkeypatch.setattr(run_portfolio, "MySQLEntryStorage", FakeEntryStorage)
    monkeypatch.setattr(run_portfolio, "MySQLPortfolioStorage", FakePortfolioStorage)

    result = CliRunner().invoke(
        run_portfolio.main,
        [
            "decide",
            "rec-run-test",
            "--capital",
            "100000",
            "--decision-date",
            "2026-05-25",
            "--market-regime",
            "neutral",
            "--entry-run-id",
            "entry-run-test",
        ],
    )

    assert result.exit_code == 0
    assert saved["decisions"][0].action == "rebalance"
    assert [allocation.instrument_id for allocation in saved["allocations"]] == ["EQUITY:US:AAPL", "EQUITY:US:OLD"]
    assert saved["allocations"][0].source_entry_plan_id == "entry-plan-ready"
    assert saved["allocations"][1].action == "reduce"
