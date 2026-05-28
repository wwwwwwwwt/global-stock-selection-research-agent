from openstockagent.database.mysql import MySQLConfig
from openstockagent.entry.models import EntryPlan, EntryPlanReview, EntryPlanRun
from openstockagent.entry.storage import MySQLEntryStorage


def test_mysql_entry_storage_creates_and_upserts_records():
    factory = FakeConnectionFactory()
    storage = MySQLEntryStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
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
        summary_json="{}",
    )
    plan = _plan()
    review = EntryPlanReview(
        review_id="entry-review-test",
        plan_id=plan.plan_id,
        review_date="2026-06-03",
        triggered=True,
        trigger_date="2026-05-28",
        entry_price=10.5,
        review_price=11.0,
        realized_return=0.0476,
        max_drawdown=-0.02,
        max_favorable_return=0.08,
        avoided_chase_loss=None,
        missed_opportunity=None,
        entry_quality_score=0.7,
        review_notes_json="{}",
    )

    storage.upsert_entry_plan_run(run)
    storage.delete_entry_plans(run.run_id)
    storage.upsert_entry_plans([plan])
    storage.upsert_entry_plan_review(review)

    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS entry_plan_runs" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS entry_plans" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS entry_plan_reviews" in executed_sql
    assert "DELETE FROM entry_plans WHERE run_id = %s" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql


def test_mysql_entry_storage_loads_ready_plans_by_run():
    row = _plan().to_record()
    row["rank"] = row.pop("rank_position")
    factory = FakeConnectionFactory(rows=[row])
    storage = MySQLEntryStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
        ensure_tables=False,
    )

    plans = storage.load_entry_plans("entry-run-test", ready_only=True)

    assert plans[0].plan_id == "entry-plan-test"
    assert plans[0].entry_status == "ready"
    assert "entry_status = %s" in factory.executed_sql[-1]
    assert factory.executed_params[-1] == ["entry-run-test", "ready"]


def _plan():
    return EntryPlan(
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


class FakeConnectionFactory:
    def __init__(self, rows=None):
        self.executed_sql = []
        self.executed_params = []
        self.rows = rows or []

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
