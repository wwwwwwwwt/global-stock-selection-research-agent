"""Create and review entry timing plans."""
import json

import click

from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.database.mysql import MySQLConfig
from openstockagent.entry.runner import run_due_entry_plan_reviews, run_entry_plan_pipeline
from openstockagent.entry.storage import MySQLEntryStorage
from openstockagent.market.storage import MySQLMarketRealityStorage
from openstockagent.recommendations.storage import MySQLRecommendationStorage


@click.group()
def main():
    """Manage entry timing plans and reviews."""


@main.command("from-recommendation")
@click.argument("recommendation_run_id")
@click.option("--as-of", required=True, help="Entry planning date, e.g. 2026-05-27")
@click.option("--horizon", type=click.Choice(["1d", "5d", "20d", "60d"]), default="5d", show_default=True)
@click.option(
    "--market-regime",
    type=click.Choice(["risk_on", "neutral", "risk_off", "high_risk", "data_bad", "unknown"]),
    default="unknown",
    show_default=True,
)
@click.option("--source", default="tushare", show_default=True, help="Canonical bars source")
@click.option("--adjustment", default="split_adjusted", show_default=True, help="Canonical bars adjustment")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def from_recommendation(
    recommendation_run_id: str,
    as_of: str,
    horizon: str,
    market_regime: str,
    source: str,
    adjustment: str,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    result = run_entry_plan_pipeline(
        recommendation_run_id=recommendation_run_id,
        as_of=as_of,
        horizon=horizon,
        market_regime=market_regime,
        recommendation_storage=MySQLRecommendationStorage(config=config),
        bar_storage=MySQLMarketDataStorage(config=config),
        entry_storage=MySQLEntryStorage(config=config),
        market_reality_storage=MySQLMarketRealityStorage(config=config),
        source=source,
        adjustment=adjustment,
    )
    summary = json.loads(result.run.summary_json)
    click.echo(
        "Entry plan run complete: "
        f"run_id={result.run.run_id} "
        f"recommendation_run_id={recommendation_run_id} "
        f"as_of={as_of} "
        f"horizon={horizon} "
        f"ready_count={summary['ready_count']} "
        f"wait_count={summary['wait_count']} "
        f"avoid_count={summary['avoid_count']} "
        f"invalid_count={summary['invalid_count']}"
    )
    for plan in result.plans:
        click.echo(
            f"{plan.rank}. {plan.instrument_id} "
            f"mode={plan.entry_mode} "
            f"status={plan.entry_status} "
            f"reference={_format_optional_float(plan.reference_price)} "
            f"trigger={_format_optional_float(plan.trigger_price)} "
            f"pullback={_format_optional_float(plan.pullback_price)}"
        )


@main.command("review-due")
@click.option("--as-of", required=True, help="Review all due entry plans on or before this date")
@click.option("--max-items", type=int, default=None, help="Limit due plans for smoke tests or batches")
@click.option("--source", default="tushare", show_default=True, help="Canonical bars source")
@click.option("--adjustment", default="split_adjusted", show_default=True, help="Canonical bars adjustment")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def review_due(
    as_of: str,
    max_items: int | None,
    source: str,
    adjustment: str,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    reviews = run_due_entry_plan_reviews(
        as_of=as_of,
        entry_storage=MySQLEntryStorage(config=config),
        bar_storage=MySQLMarketDataStorage(config=config),
        limit=max_items,
        source=source,
        adjustment=adjustment,
    )
    click.echo(f"Due entry plan reviews complete: as_of={as_of} reviews_written={len(reviews)}")
    for review in reviews:
        click.echo(
            f"{review.plan_id} "
            f"review_id={review.review_id} "
            f"triggered={review.triggered} "
            f"realized_return={_format_optional_float(review.realized_return)} "
            f"quality={_format_optional_float(review.entry_quality_score)}"
        )


def _format_optional_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6f}"


if __name__ == "__main__":
    main()
