"""Create recommendation runs and review records."""
import click

from openstockagent.database.mysql import MySQLConfig
from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.recommendations.runner import (
    build_recommendation_review,
    run_due_recommendation_reviews,
    run_recommendation_pipeline,
)
from openstockagent.recommendations.storage import MySQLRecommendationStorage
from openstockagent.screening.storage import MySQLScreeningStorage


@click.group()
def main():
    """Manage horizon-aware recommendations and reviews."""


@main.command("from-screen")
@click.argument("screen_run_id")
@click.option("--universe-id", required=True, help="Universe id associated with the screen run")
@click.option("--as-of", "recommendation_date", required=True, help="Recommendation date, e.g. 2026-05-25")
@click.option("--horizon", type=click.Choice(["1d", "5d", "20d", "60d"]), default="5d", show_default=True)
@click.option("--strategy-name", default=None, help="Override horizon strategy name")
@click.option("--strategy-version", default=None, help="Override horizon strategy version")
@click.option("--market-regime", default="unknown", show_default=True)
@click.option("--top-n", default=None, type=int, help="Override maximum recommendation items")
@click.option("--buy-threshold", default=None, type=float, help="Override buy threshold")
@click.option("--watch-threshold", default=None, type=float, help="Override watch threshold")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def from_screen(
    screen_run_id: str,
    universe_id: str,
    recommendation_date: str,
    horizon: str,
    strategy_name: str,
    strategy_version: str,
    market_regime: str,
    top_n: int,
    buy_threshold: float,
    watch_threshold: float,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    db_config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    recommendation_config = {}
    if top_n is not None:
        recommendation_config["max_items"] = top_n
    if buy_threshold is not None:
        recommendation_config["buy_threshold"] = buy_threshold
    if watch_threshold is not None:
        recommendation_config["watch_threshold"] = watch_threshold
    result = run_recommendation_pipeline(
        screen_run_id=screen_run_id,
        universe_id=universe_id,
        recommendation_date=recommendation_date,
        horizon=horizon,
        screening_storage=MySQLScreeningStorage(config=db_config),
        recommendation_storage=MySQLRecommendationStorage(config=db_config),
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        market_regime=market_regime,
        config=recommendation_config,
    )
    click.echo(
        "Recommendation run complete: "
        f"run_id={result.run_id} "
        f"screen_run_id={result.screen_run_id} "
        f"universe_id={result.universe_id} "
        f"horizon={result.horizon} "
        f"review_due_date={result.review_due_date} "
        f"status={result.status} "
        f"items_seen={result.items_seen} "
        f"buy_candidate_count={result.buy_candidate_count} "
        f"watch_count={result.watch_count} "
        f"skip_count={result.skip_count}"
    )
    for item in result.items:
        if item.action != "skip":
            click.echo(
                f"{item.rank}. {item.instrument_id} "
                f"action={item.action} "
                f"score={item.source_screen_score:.6f} "
                f"confidence={item.confidence:.6f}"
            )


@main.command("review-due")
@click.option("--as-of", required=True, help="Review all due recommendations on or before this date")
@click.option("--benchmark-return", type=float, default=None)
@click.option("--max-items", type=int, default=None, help="Limit due items for smoke tests or batches")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def review_due(
    as_of: str,
    benchmark_return: float | None,
    max_items: int | None,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    result = run_due_recommendation_reviews(
        as_of=as_of,
        recommendation_storage=MySQLRecommendationStorage(config=config),
        bar_storage=MySQLMarketDataStorage(config=config),
        benchmark_return=benchmark_return,
        max_items=max_items,
    )
    click.echo(
        "Due recommendation reviews complete: "
        f"as_of={result.as_of} "
        f"due_items_seen={result.due_items_seen} "
        f"reviews_written={result.reviews_written} "
        f"skipped_count={result.skipped_count} "
        f"errors={len(result.errors)}"
    )
    for review in result.reviews:
        click.echo(
            f"{review.recommendation_id} "
            f"review_id={review.review_id} "
            f"realized_return={review.realized_return:.6f} "
            f"hit={review.hit}"
        )
    for error in result.errors:
        click.echo(f"- {error}")


@main.command("add-review")
@click.argument("recommendation_id")
@click.option("--review-date", required=True, help="Review date, e.g. 2026-06-01")
@click.option("--entry-price", required=True, type=float)
@click.option("--review-price", required=True, type=float)
@click.option("--benchmark-return", type=float, default=None)
@click.option("--max-drawdown", type=float, default=None)
@click.option("--max-favorable-return", type=float, default=None)
@click.option(
    "--thesis-status",
    type=click.Choice(["confirmed", "invalidated", "mixed", "unknown"]),
    default="unknown",
    show_default=True,
)
@click.option("--invalidation-triggered/--no-invalidation-triggered", default=False, show_default=True)
@click.option("--factor-snapshot-json", default="{}", show_default=True)
@click.option("--review-notes-json", default="{}", show_default=True)
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def add_review(
    recommendation_id: str,
    review_date: str,
    entry_price: float,
    review_price: float,
    benchmark_return: float | None,
    max_drawdown: float | None,
    max_favorable_return: float | None,
    thesis_status: str,
    invalidation_triggered: bool,
    factor_snapshot_json: str,
    review_notes_json: str,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    review = build_recommendation_review(
        recommendation_id=recommendation_id,
        review_date=review_date,
        entry_price=entry_price,
        review_price=review_price,
        benchmark_return=benchmark_return,
        max_drawdown=max_drawdown,
        max_favorable_return=max_favorable_return,
        thesis_status=thesis_status,
        invalidation_triggered=invalidation_triggered,
        factor_snapshot_json=factor_snapshot_json,
        review_notes_json=review_notes_json,
    )
    MySQLRecommendationStorage(config=config).upsert_recommendation_review(review)
    click.echo(
        "Recommendation review saved: "
        f"review_id={review.review_id} "
        f"recommendation_id={review.recommendation_id} "
        f"review_date={review.review_date} "
        f"realized_return={review.realized_return:.6f} "
        f"excess_return={review.excess_return if review.excess_return is not None else 'NA'} "
        f"hit={review.hit}"
    )


if __name__ == "__main__":
    main()
