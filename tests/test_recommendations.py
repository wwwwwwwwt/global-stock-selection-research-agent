import json

from openstockagent.database.mysql import MySQLConfig
from openstockagent.recommendations.models import RecommendationItem, RecommendationReview
from openstockagent.recommendations.runner import (
    build_recommendation_review,
    build_recommendation_items,
    review_due_date_for,
    run_recommendation_pipeline,
)
from openstockagent.recommendations.storage import MySQLRecommendationStorage
from openstockagent.screening.models import ScreenResult


def test_build_recommendation_items_assigns_actions_and_review_due_date():
    results = [
        _screen_result("EQUITY:US:MSFT", rank=1, score=0.82),
        _screen_result("EQUITY:US:AAPL", rank=2, score=0.58),
        _screen_result("EQUITY:US:LOW", rank=3, score=0.44),
    ]

    items = build_recommendation_items(
        "rec-run-test",
        "5d",
        results,
        {"buy_threshold": 0.65, "watch_threshold": 0.55, "max_items": 3},
    )

    assert review_due_date_for("2026-05-22", "5d") == "2026-05-29"
    assert [item.action for item in items] == ["buy_candidate", "watch", "skip"]
    assert items[0].recommendation_id.startswith("rec-item-")
    assert items[0].expected_return == 0.0256
    assert items[0].confidence == 1.0
    assert json.loads(items[0].thesis_json)["top_components"][0]["component"] == "momentum_score"


def test_run_recommendation_pipeline_persists_run_and_items():
    screening_storage = FakeScreeningStorage(
        [
            _screen_result("EQUITY:US:MSFT", rank=1, score=0.82),
            _screen_result("EQUITY:US:AAPL", rank=2, score=0.58),
        ]
    )
    recommendation_storage = FakeRecommendationStorage()

    result = run_recommendation_pipeline(
        screen_run_id="screen-test",
        universe_id="us_core",
        recommendation_date="2026-05-22",
        horizon="5d",
        screening_storage=screening_storage,
        recommendation_storage=recommendation_storage,
        market_regime="neutral",
        config={"max_items": 2},
    )

    assert result.status == "completed"
    assert result.buy_candidate_count == 1
    assert result.watch_count == 1
    assert recommendation_storage.runs[0].market_regime == "neutral"
    assert recommendation_storage.deleted_run_ids == [result.run_id]
    assert [item.instrument_id for item in recommendation_storage.items] == ["EQUITY:US:MSFT", "EQUITY:US:AAPL"]
    assert screening_storage.calls == [("screen-test", True)]


def test_build_recommendation_review_calculates_returns_and_hit():
    review = build_recommendation_review(
        recommendation_id="rec-item-test",
        review_date="2026-05-29",
        entry_price=100.0,
        review_price=106.0,
        benchmark_return=0.02,
        max_drawdown=-0.03,
        max_favorable_return=0.08,
        thesis_status="confirmed",
    )

    assert review.review_id.startswith("rec-review-")
    assert review.realized_return == 0.06
    assert review.excess_return == 0.04
    assert review.hit is True
    assert review.to_record()["hit"] == 1


def test_mysql_recommendation_storage_creates_upserts_and_loads():
    item = RecommendationItem(
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
    review = RecommendationReview(
        review_id="rec-review-test",
        recommendation_id="rec-item-test",
        review_date="2026-05-29",
        entry_price=100.0,
        review_price=106.0,
        realized_return=0.06,
        benchmark_return=0.02,
        excess_return=0.04,
        max_drawdown=-0.03,
        max_favorable_return=0.08,
        hit=True,
        thesis_status="confirmed",
        invalidation_triggered=False,
        factor_snapshot_json="{}",
        review_notes_json="{}",
    )
    factory = FakeConnectionFactory(
        item_rows=[
            {
                **item.to_record(),
                "rank": 1,
            }
        ],
        review_rows=[review.to_record()],
    )
    storage = MySQLRecommendationStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
    )

    storage.upsert_recommendation_run(
        recommendation_storage_run(
            run_id="rec-run-test",
            screen_run_id="screen-test",
            universe_id="us_core",
        )
    )
    storage.delete_recommendation_items("rec-run-test")
    storage.upsert_recommendation_items([item])
    storage.upsert_recommendation_review(review)
    loaded_items = storage.load_recommendation_items("rec-run-test", actionable_only=True)
    loaded_reviews = storage.load_recommendation_reviews("rec-item-test")

    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS recommendation_runs" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS recommendation_items" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS recommendation_reviews" in executed_sql
    assert "rank_position INTEGER NOT NULL" in executed_sql
    assert "DELETE FROM recommendation_items WHERE run_id = %s" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql
    assert loaded_items[0].instrument_id == "EQUITY:US:MSFT"
    assert loaded_items[0].action == "buy_candidate"
    assert loaded_reviews[0].hit is True


def recommendation_storage_run(run_id, screen_run_id, universe_id):
    from openstockagent.recommendations.models import RecommendationRun

    return RecommendationRun(
        run_id=run_id,
        screen_run_id=screen_run_id,
        universe_id=universe_id,
        recommendation_date="2026-05-22",
        horizon="5d",
        review_due_date="2026-05-29",
        strategy_name="recommendation_mvp",
        strategy_version="v1",
        market_regime="neutral",
        status="completed",
    )


def _screen_result(instrument_id: str, *, rank: int, score: float) -> ScreenResult:
    return ScreenResult(
        run_id="screen-test",
        instrument_id=instrument_id,
        rank=rank,
        selected=True,
        total_score=score,
        score_breakdown_json=json.dumps({"total_score": score}, sort_keys=True),
        reason_json=json.dumps(
            {
                "top_components": [{"component": "momentum_score", "score": score}],
                "supporting_factors": [{"factor_name": "return_20d", "percentile": score}],
            },
            sort_keys=True,
        ),
        risk_json=json.dumps({"risk_penalty": 0.0, "flags": []}, sort_keys=True),
        evidence_refs_json=json.dumps({"factors": [{"factor_name": "return_20d"}]}, sort_keys=True),
    )


class FakeScreeningStorage:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def load_screen_results(self, run_id, selected_only=False):
        self.calls.append((run_id, selected_only))
        return self.results


class FakeRecommendationStorage:
    def __init__(self):
        self.runs = []
        self.items = []
        self.deleted_run_ids = []

    def upsert_recommendation_run(self, run):
        self.runs.append(run)

    def delete_recommendation_items(self, run_id):
        self.deleted_run_ids.append(run_id)

    def upsert_recommendation_items(self, items):
        self.items.extend(items)
        return len(items)


class FakeConnectionFactory:
    def __init__(self, item_rows=None, review_rows=None):
        self.item_rows = item_rows or []
        self.review_rows = review_rows or []
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
        self.last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        pass

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.factory.executed_sql.append(sql)
        self.factory.executed_params.append(params)
        return 1

    def executemany(self, sql, params):
        self.last_sql = sql
        self.factory.executed_sql.append(sql)
        self.factory.executed_params.extend(params)

    def fetchall(self):
        if "FROM recommendation_reviews" in self.last_sql:
            return self.factory.review_rows
        return self.factory.item_rows

