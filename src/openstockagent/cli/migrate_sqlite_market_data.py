"""Migrate the legacy SQLite market database into MySQL."""
from pathlib import Path

import click

from openstockagent.config import LEGACY_SQLITE_MARKET_DB_PATH
from openstockagent.data.sqlite_migration import migrate_sqlite_market_data
from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.database.mysql import MySQLConfig


@click.command()
@click.option(
    "--sqlite-path",
    default=str(LEGACY_SQLITE_MARKET_DB_PATH),
    show_default=True,
    help="Legacy SQLite market database path.",
)
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
@click.option("--chunk-size", default=5000, show_default=True, help="Rows per migration chunk")
def main(sqlite_path: str, mysql_url: str, mysql_user: str, mysql_password: str, chunk_size: int):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    result = migrate_sqlite_market_data(
        Path(sqlite_path),
        target_storage=MySQLMarketDataStorage(config=config),
        chunk_size=chunk_size,
    )
    click.echo(
        "SQLite migration complete: "
        f"sqlite_path={result.sqlite_path} "
        f"instruments={result.instruments} "
        f"aliases={result.aliases} "
        f"bars={result.bars} "
        f"feed_runs={result.feed_runs} "
        f"data_quality_issues={result.data_quality_issues} "
        f"prediction_runs={result.prediction_runs} "
        f"predicted_bars={result.predicted_bars} "
        f"technical_signals={result.technical_signals} "
        f"legacy_ohlcv_rows_skipped={result.legacy_ohlcv_rows_skipped}"
    )


if __name__ == "__main__":
    main()
