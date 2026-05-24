#!/usr/bin/env python3
"""Run real-data factor calculation for a universe."""
import click

from openstockagent.config import DB_PATH
from openstockagent.data.feeds.akshare import AkShareAStockFeed
from openstockagent.data.feeds.registry import FeedRegistry
from openstockagent.data.feeds.yahoo import YahooFinanceFeed
from openstockagent.data.storage import SQLiteStorage
from openstockagent.database.mysql import MySQLConfig
from openstockagent.factors.storage import MySQLFactorStorage
from openstockagent.pipelines.real_data_factors import RealDataFactorRunResult, run_real_data_factor_pipeline
from openstockagent.universe.storage import MySQLUniverseStorage


@click.command()
@click.argument("universe_id")
@click.option("--as-of", required=True, help="Trade date for factor calculation, e.g. 2026-05-24")
@click.option("--period", default="1y", help="Historical data period, e.g. 6mo or 1y")
@click.option("--interval", default="1d", help="Bar interval")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def main(
    universe_id: str,
    as_of: str,
    period: str,
    interval: str,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    feed_registry = FeedRegistry()
    feed_registry.register("US", "equity", interval, YahooFinanceFeed())
    feed_registry.register("CN", "equity", interval, AkShareAStockFeed())
    result = run_real_data_factor_pipeline(
        universe_id=universe_id,
        as_of=as_of,
        interval=interval,
        period=period,
        universe_storage=MySQLUniverseStorage(config=config),
        bar_storage=SQLiteStorage(DB_PATH),
        factor_storage=MySQLFactorStorage(config=config),
        feed_registry=feed_registry,
    )
    click.echo(
        "Real data factor run complete: "
        f"universe_id={result.universe_id} "
        f"trade_date={result.trade_date} "
        f"members_seen={result.members_seen} "
        f"instruments_fetched={result.instruments_fetched} "
        f"failed_instruments={result.failed_instruments} "
        f"bars_written={result.bars_written} "
        f"factor_values_written={result.factor_values_written}"
    )
    if result.errors:
        click.echo("Errors:")
        for error in result.errors:
            click.echo(f"- {error}")


if __name__ == "__main__":
    main()
