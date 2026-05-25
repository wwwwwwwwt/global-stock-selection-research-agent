from click.testing import CliRunner
import tomllib


def test_stock_portfolio_entrypoint_targets_packaged_module():
    with open("pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["scripts"]["stock-portfolio"].startswith("openstockagent.")


def test_portfolio_decide_cli_builds_and_persists_decision(monkeypatch):
    from openstockagent.cli import run_portfolio
    from openstockagent.portfolio.decision import build_default_policy, build_portfolio_decision
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
    assert saved["policies"][0].policy_id == "balanced_v1"
    assert saved["decisions"][0].action == "allocate"
    assert saved["allocations"][0].instrument_id == "EQUITY:US:AAPL"
    assert "Portfolio decision complete" in result.output

