import json

from openstockagent.database.mysql import MySQLConfig
from openstockagent.portfolio.decision import build_default_policy, build_portfolio_decision
from openstockagent.portfolio.models import PortfolioAccount, PortfolioPosition
from openstockagent.portfolio.storage import MySQLPortfolioStorage
from openstockagent.recommendations.models import RecommendationItem


def test_portfolio_decision_allocates_with_market_regime_and_policy_caps():
    policy = build_default_policy(max_gross_exposure=0.8, max_single_position_pct=0.1, max_new_positions_per_day=2)
    items = [
        _item("rec-a", "EQUITY:US:AAPL", confidence=0.90, score=0.82, expected_return=0.03),
        _item("rec-b", "EQUITY:US:MSFT", confidence=0.80, score=0.76, expected_return=0.02),
        _item("rec-c", "EQUITY:US:LOW", action="skip", confidence=0.95, score=0.9, expected_return=0.04),
    ]

    result = build_portfolio_decision(
        recommendation_run_id="rec-run-test",
        account_id="paper",
        decision_date="2026-05-25",
        market_regime="risk_on",
        capital=100_000,
        policy=policy,
        recommendation_items=items,
    )

    assert result.decision.action == "allocate"
    assert result.decision.target_gross_exposure == 0.2
    assert result.decision.cash_pct == 0.8
    assert [allocation.instrument_id for allocation in result.allocations] == ["EQUITY:US:AAPL", "EQUITY:US:MSFT"]
    assert result.allocations[0].max_position_value == 10_000


def test_portfolio_decision_can_empty_or_skip_when_risk_bad_or_no_signal():
    policy = build_default_policy()
    empty = build_portfolio_decision(
        recommendation_run_id="rec-run-test",
        account_id="paper",
        decision_date="2026-05-25",
        market_regime="data_bad",
        capital=100_000,
        policy=policy,
        recommendation_items=[_item("rec-a", "EQUITY:US:AAPL", confidence=0.95, score=0.9)],
    )
    no_signal = build_portfolio_decision(
        recommendation_run_id="rec-run-test",
        account_id="paper",
        decision_date="2026-05-25",
        market_regime="neutral",
        capital=100_000,
        policy=policy,
        recommendation_items=[_item("rec-a", "EQUITY:US:AAPL", action="skip", confidence=0.95, score=0.9)],
    )

    assert empty.decision.action == "empty"
    assert empty.decision.cash_pct == 1.0
    assert no_signal.decision.action == "no_new_position"
    assert no_signal.allocations == []


def test_portfolio_decision_does_not_allocate_watch_items_by_default():
    policy = build_default_policy()

    result = build_portfolio_decision(
        recommendation_run_id="rec-run-test",
        account_id="paper",
        decision_date="2026-05-25",
        market_regime="neutral",
        capital=100_000,
        policy=policy,
        recommendation_items=[_item("rec-watch", "EQUITY:CN:000001", action="watch", confidence=0.95, score=0.62)],
    )

    assert result.decision.action == "no_new_position"
    assert result.decision.target_gross_exposure == 0.0
    assert result.decision.cash_pct == 1.0
    assert result.allocations == []


def test_portfolio_decision_can_allocate_watch_items_when_policy_allows_it():
    policy = build_default_policy(allow_watch_allocation=True)

    result = build_portfolio_decision(
        recommendation_run_id="rec-run-test",
        account_id="paper",
        decision_date="2026-05-25",
        market_regime="neutral",
        capital=100_000,
        policy=policy,
        recommendation_items=[_item("rec-watch", "EQUITY:CN:000001", action="watch", confidence=0.95, score=0.62)],
    )

    assert result.decision.action == "allocate"
    assert result.allocations[0].action == "watch"
    assert result.allocations[0].target_weight == 0.1


def test_portfolio_decision_can_link_allocations_to_ready_entry_plans():
    policy = build_default_policy()

    result = build_portfolio_decision(
        recommendation_run_id="rec-run-test",
        account_id="paper",
        decision_date="2026-05-25",
        market_regime="neutral",
        capital=100_000,
        policy=policy,
        recommendation_items=[_item("rec-a", "EQUITY:US:AAPL", confidence=0.95, score=0.9)],
        entry_plan_ids_by_recommendation_id={"rec-a": "entry-plan-a"},
    )

    assert result.decision.action == "allocate"
    assert result.allocations[0].source_entry_plan_id == "entry-plan-a"
    assert json.loads(result.allocations[0].reason_json)["source_entry_plan_id"] == "entry-plan-a"


def test_portfolio_decision_rebalances_against_current_positions():
    policy = build_default_policy(max_single_position_pct=0.1, max_new_positions_per_day=2)
    positions = [
        PortfolioPosition("paper", "EQUITY:US:AAPL", 10, 100, 10_000),
        PortfolioPosition("paper", "EQUITY:US:MSFT", 10, 100, 5_000),
        PortfolioPosition("paper", "EQUITY:US:OLD", 10, 100, 12_000),
    ]

    result = build_portfolio_decision(
        recommendation_run_id="rec-run-test",
        account_id="paper",
        decision_date="2026-05-25",
        market_regime="neutral",
        capital=100_000,
        policy=policy,
        recommendation_items=[
            _item("rec-a", "EQUITY:US:AAPL", confidence=0.95, score=0.9),
            _item("rec-b", "EQUITY:US:MSFT", confidence=0.90, score=0.85),
        ],
        current_positions=positions,
    )

    actions = {allocation.instrument_id: allocation.action for allocation in result.allocations}
    reasons = {allocation.instrument_id: json.loads(allocation.reason_json) for allocation in result.allocations}
    assert result.decision.action == "rebalance"
    assert actions == {
        "EQUITY:US:AAPL": "hold",
        "EQUITY:US:MSFT": "add",
        "EQUITY:US:OLD": "reduce",
    }
    assert reasons["EQUITY:US:AAPL"]["current_weight"] == 0.1
    assert reasons["EQUITY:US:MSFT"]["target_weight"] == 0.1
    assert result.decision.target_gross_exposure == 0.2


def test_portfolio_decision_sells_positions_when_market_regime_blocks_exposure():
    policy = build_default_policy()

    result = build_portfolio_decision(
        recommendation_run_id="rec-run-test",
        account_id="paper",
        decision_date="2026-05-25",
        market_regime="data_bad",
        capital=100_000,
        policy=policy,
        recommendation_items=[_item("rec-a", "EQUITY:US:AAPL", confidence=0.95, score=0.9)],
        current_positions=[PortfolioPosition("paper", "EQUITY:US:AAPL", 10, 100, 10_000)],
    )

    assert result.decision.action == "empty"
    assert result.decision.target_gross_exposure == 0.0
    assert result.allocations[0].action == "sell"
    assert result.allocations[0].target_weight == 0.0


def test_mysql_portfolio_storage_creates_and_upserts_records():
    factory = FakeConnectionFactory()
    storage = MySQLPortfolioStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
    )
    policy = build_default_policy()
    result = build_portfolio_decision(
        recommendation_run_id="rec-run-test",
        account_id="paper",
        decision_date="2026-05-25",
        market_regime="neutral",
        capital=100_000,
        policy=policy,
        recommendation_items=[_item("rec-a", "EQUITY:US:AAPL", confidence=0.9, score=0.8)],
    )

    storage.upsert_account(PortfolioAccount("paper", "USD", 100_000))
    storage.upsert_policy(policy)
    storage.upsert_positions([PortfolioPosition("paper", "EQUITY:US:AAPL", 10, 100, 1_000)])
    storage.upsert_decision(result.decision)
    storage.delete_target_allocations(result.decision.decision_id)
    storage.upsert_target_allocations(result.allocations)

    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS portfolio_accounts" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS portfolio_policies" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS portfolio_positions" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS portfolio_decisions" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS target_allocations" in executed_sql
    assert "DELETE FROM target_allocations WHERE decision_id = %s" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql


def test_mysql_portfolio_storage_loads_positions_by_account():
    factory = FakeConnectionFactory(
        rows=[
            {
                "account_id": "paper",
                "instrument_id": "EQUITY:US:AAPL",
                "quantity": 10,
                "cost_basis": 100,
                "market_value": 1200,
                "unrealized_return": 0.2,
                "opened_at": "2026-05-01",
            }
        ]
    )
    storage = MySQLPortfolioStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
        ensure_tables=False,
    )

    positions = storage.load_positions("paper")

    assert positions[0].instrument_id == "EQUITY:US:AAPL"
    assert positions[0].market_value == 1200.0
    assert "FROM portfolio_positions" in factory.executed_sql[-1]
    assert factory.executed_params[-1] == ["paper"]


def _item(
    recommendation_id,
    instrument_id,
    *,
    action="buy_candidate",
    confidence=0.8,
    score=0.7,
    expected_return=0.02,
):
    return RecommendationItem(
        recommendation_id=recommendation_id,
        run_id="rec-run-test",
        instrument_id=instrument_id,
        rank=1,
        action=action,
        source_screen_rank=1,
        source_screen_score=score,
        expected_return=expected_return,
        expected_risk=0.1,
        confidence=confidence,
        thesis_json="{}",
        confirmation_json="{}",
        invalidation_json="{}",
        risk_json=json.dumps({"flags": []}),
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
