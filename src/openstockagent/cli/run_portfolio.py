"""Build portfolio decisions from recommendation runs."""
import click

from openstockagent.database.mysql import MySQLConfig
from openstockagent.entry.storage import MySQLEntryStorage
from openstockagent.portfolio.decision import build_default_policy, build_portfolio_decision
from openstockagent.portfolio.models import PortfolioAccount
from openstockagent.portfolio.storage import MySQLPortfolioStorage
from openstockagent.recommendations.storage import MySQLRecommendationStorage


@click.group()
def main():
    """Manage portfolio-level decisions."""


@main.command("decide")
@click.argument("recommendation_run_id")
@click.option("--account-id", default="paper", show_default=True)
@click.option("--capital", required=True, type=float)
@click.option("--base-currency", default="USD", show_default=True)
@click.option("--decision-date", required=True)
@click.option(
    "--market-regime",
    type=click.Choice(["risk_on", "neutral", "risk_off", "high_risk", "data_bad", "unknown"]),
    default="unknown",
    show_default=True,
)
@click.option("--policy-id", default="balanced_v1", show_default=True)
@click.option("--max-gross-exposure", default=0.8, show_default=True)
@click.option("--max-single-position-pct", default=0.1, show_default=True)
@click.option("--max-positions", default=10, show_default=True)
@click.option("--cash-floor-pct", default=0.1, show_default=True)
@click.option("--max-new-positions-per-day", default=5, show_default=True)
@click.option("--min-confidence", default=0.55, show_default=True)
@click.option("--min-expected-return", default=0.0, show_default=True)
@click.option("--allow-watch-allocation", is_flag=True, help="Allow watch items to receive target allocations")
@click.option("--entry-run-id", default=None, help="Only allocate recommendations with ready entry plans from this run")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def decide(
    recommendation_run_id: str,
    account_id: str,
    capital: float,
    base_currency: str,
    decision_date: str,
    market_regime: str,
    policy_id: str,
    max_gross_exposure: float,
    max_single_position_pct: float,
    max_positions: int,
    cash_floor_pct: float,
    max_new_positions_per_day: int,
    min_confidence: float,
    min_expected_return: float,
    allow_watch_allocation: bool,
    entry_run_id: str | None,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    recommendation_storage = MySQLRecommendationStorage(config=config)
    portfolio_storage = MySQLPortfolioStorage(config=config)
    policy = build_default_policy(
        policy_id=policy_id,
        max_gross_exposure=max_gross_exposure,
        max_single_position_pct=max_single_position_pct,
        max_positions=max_positions,
        cash_floor_pct=cash_floor_pct,
        max_new_positions_per_day=max_new_positions_per_day,
        min_recommendation_confidence=min_confidence,
        min_expected_return=min_expected_return,
        allow_watch_allocation=allow_watch_allocation,
    )
    account = PortfolioAccount(account_id=account_id, base_currency=base_currency, capital=capital)
    items = recommendation_storage.load_recommendation_items(recommendation_run_id, actionable_only=True)
    current_positions = portfolio_storage.load_positions(account_id)
    entry_plan_ids_by_recommendation_id = {}
    if entry_run_id is not None:
        entry_plans = MySQLEntryStorage(config=config).load_entry_plans(entry_run_id, ready_only=True)
        entry_plan_ids_by_recommendation_id = {
            plan.recommendation_id: plan.plan_id for plan in entry_plans
        }
        items = [item for item in items if item.recommendation_id in entry_plan_ids_by_recommendation_id]
    result = build_portfolio_decision(
        recommendation_run_id=recommendation_run_id,
        account_id=account_id,
        decision_date=decision_date,
        market_regime=market_regime,
        capital=capital,
        policy=policy,
        recommendation_items=items,
        current_positions=current_positions,
        entry_plan_ids_by_recommendation_id=entry_plan_ids_by_recommendation_id,
    )
    portfolio_storage.upsert_account(account)
    portfolio_storage.upsert_policy(policy)
    portfolio_storage.upsert_decision(result.decision)
    portfolio_storage.delete_target_allocations(result.decision.decision_id)
    portfolio_storage.upsert_target_allocations(result.allocations)
    click.echo(
        "Portfolio decision complete: "
        f"decision_id={result.decision.decision_id} "
        f"recommendation_run_id={recommendation_run_id} "
        f"account_id={account_id} "
        f"market_regime={market_regime} "
        f"action={result.decision.action} "
        f"target_gross_exposure={result.decision.target_gross_exposure:.6f} "
        f"cash_pct={result.decision.cash_pct:.6f} "
        f"positions={len(current_positions)} "
        f"allocations={len(result.allocations)}"
        + (f" entry_run_id={entry_run_id}" if entry_run_id is not None else "")
    )
    for allocation in result.allocations:
        click.echo(
            f"{allocation.instrument_id} "
            f"action={allocation.action} "
            f"target_weight={allocation.target_weight:.6f} "
            f"max_position_value={allocation.max_position_value:.2f}"
        )


if __name__ == "__main__":
    main()
