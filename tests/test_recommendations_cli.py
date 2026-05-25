from click.testing import CliRunner
import tomllib


def test_stock_recommend_entrypoint_targets_packaged_module():
    with open("pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["scripts"]["stock-recommend"].startswith("openstockagent.")


def test_recommendation_from_screen_cli_runs_pipeline(monkeypatch):
    from openstockagent.cli import run_recommendations
    from openstockagent.recommendations.models import RecommendationItem
    from openstockagent.recommendations.runner import RecommendationRunResult

    calls = {}

    def fake_pipeline(**kwargs):
        calls.update(kwargs)
        return RecommendationRunResult(
            run_id="rec-run-test",
            screen_run_id=kwargs["screen_run_id"],
            universe_id=kwargs["universe_id"],
            recommendation_date=kwargs["recommendation_date"],
            horizon=kwargs["horizon"],
            review_due_date="2026-05-29",
            status="completed",
            items_seen=1,
            buy_candidate_count=1,
            watch_count=0,
            skip_count=0,
            items=[
                RecommendationItem(
                    recommendation_id="rec-item-test",
                    run_id="rec-run-test",
                    instrument_id="EQUITY:US:MSFT",
                    rank=1,
                    action="buy_candidate",
                    source_screen_rank=1,
                    source_screen_score=0.82,
                    expected_return=0.0256,
                    expected_risk=0.18,
                    confidence=1.0,
                    thesis_json="{}",
                    confirmation_json="{}",
                    invalidation_json="{}",
                    risk_json="{}",
                    evidence_refs_json="{}",
                )
            ],
        )

    monkeypatch.setattr(run_recommendations, "run_recommendation_pipeline", fake_pipeline)
    monkeypatch.setattr(run_recommendations, "MySQLScreeningStorage", lambda config: object())
    monkeypatch.setattr(run_recommendations, "MySQLRecommendationStorage", lambda config: object())

    result = CliRunner().invoke(
        run_recommendations.main,
        [
            "from-screen",
            "screen-test",
            "--universe-id",
            "us_core",
            "--as-of",
            "2026-05-22",
            "--horizon",
            "5d",
            "--top-n",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert calls["screen_run_id"] == "screen-test"
    assert calls["universe_id"] == "us_core"
    assert calls["recommendation_date"] == "2026-05-22"
    assert calls["config"]["max_items"] == 3
    assert "buy_candidate_count=1" in result.output
    assert "1. EQUITY:US:MSFT action=buy_candidate" in result.output


def test_recommendation_add_review_cli_saves_review(monkeypatch):
    from openstockagent.cli import run_recommendations

    saved = {}

    class FakeStorage:
        def __init__(self, config):
            self.config = config

        def upsert_recommendation_review(self, review):
            saved["review"] = review

    monkeypatch.setattr(run_recommendations, "MySQLRecommendationStorage", FakeStorage)

    result = CliRunner().invoke(
        run_recommendations.main,
        [
            "add-review",
            "rec-item-test",
            "--review-date",
            "2026-05-29",
            "--entry-price",
            "100",
            "--review-price",
            "106",
            "--benchmark-return",
            "0.02",
            "--thesis-status",
            "confirmed",
        ],
    )

    assert result.exit_code == 0
    assert saved["review"].realized_return == 0.06
    assert saved["review"].excess_return == 0.04
    assert "hit=True" in result.output

