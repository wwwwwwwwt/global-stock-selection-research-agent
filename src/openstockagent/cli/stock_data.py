"""Market data synchronization commands."""
import click

from openstockagent.data.feeds.akshare import AkShareAStockFeed
from openstockagent.data.feeds.polygon import PolygonStockFeed
from openstockagent.data.feeds.registry import FeedRegistry
from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.data.sync import build_sync_plan, run_data_sync_plan
from openstockagent.data.sync_storage import MySQLDataSyncStorage
from openstockagent.database.mysql import MySQLConfig
from openstockagent.universe.storage import MySQLUniverseStorage


@click.group()
def main():
    """Synchronize canonical market data."""


@main.command("sync")
@click.option("--universe", "universe_id", required=True, help="Universe id to synchronize")
@click.option("--market", type=click.Choice(["CN", "US"]), required=True, help="Market to synchronize")
@click.option("--as-of", required=True, help="Sync end date, e.g. 2026-05-25")
@click.option("--mode", type=click.Choice(["backfill", "incremental"]), default="incremental", show_default=True)
@click.option("--lookback-years", default=3, show_default=True, help="Backfill history length")
@click.option("--incremental-days", default=10, show_default=True, help="Daily incremental repair window")
@click.option("--interval", default="1d", show_default=True, help="Bar interval")
@click.option("--max-symbols", type=int, default=None, help="Limit symbols for smoke tests or batches")
@click.option("--max-attempts", default=3, show_default=True, help="Retry attempts per symbol")
@click.option("--retry-sleep-seconds", default=0.5, show_default=True, help="Sleep between retry attempts")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def sync(
    universe_id: str,
    market: str,
    as_of: str,
    mode: str,
    lookback_years: int,
    incremental_days: int,
    interval: str,
    max_symbols: int | None,
    max_attempts: int,
    retry_sleep_seconds: float,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    feed_registry = FeedRegistry()
    if market == "US":
        feed_registry.register("US", "equity", interval, PolygonStockFeed())
    else:
        feed_registry.register("CN", "equity", interval, AkShareAStockFeed())
    plan = build_sync_plan(
        universe_id=universe_id,
        market=market,
        mode=mode,
        interval=interval,
        provider="polygon" if market == "US" else "akshare",
        lookback_years=lookback_years,
        incremental_days=incremental_days,
    )
    result = run_data_sync_plan(
        plan,
        as_of=as_of,
        universe_storage=MySQLUniverseStorage(config=config),
        bar_storage=MySQLMarketDataStorage(config=config),
        feed_registry=feed_registry,
        sync_storage=MySQLDataSyncStorage(config=config),
        max_symbols=max_symbols,
        max_attempts=max_attempts,
        retry_sleep_seconds=retry_sleep_seconds,
    )
    click.echo(
        "Data sync complete: "
        f"run_id={result.run_id} "
        f"plan_id={result.plan_id} "
        f"universe_id={result.universe_id} "
        f"market={result.market} "
        f"mode={result.mode} "
        f"period={result.period} "
        f"members_seen={result.members_seen} "
        f"instruments_fetched={result.instruments_fetched} "
        f"failed_instruments={result.failed_instruments} "
        f"bars_written={result.bars_written} "
        f"status={result.status}"
    )
    if result.errors:
        click.echo("Errors:")
        for error in result.errors:
            click.echo(f"- {error}")


if __name__ == "__main__":
    main()
