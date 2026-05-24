"""Universe management commands."""
from pathlib import Path

import click

from openstockagent.config import PROJECT_ROOT
from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.database.mysql import MySQLConfig
from openstockagent.universe.core import build_cn_core_universe, build_us_core_universe, persist_core_universe
from openstockagent.universe.storage import MySQLUniverseStorage


DEFAULT_CUSTOM_UNIVERSES = {
    "CN": PROJECT_ROOT / "resources" / "universes" / "cn_industry_leaders.csv",
    "US": PROJECT_ROOT / "resources" / "universes" / "us_theme_watchlist.csv",
}


@click.group()
def main():
    """Build and manage stock universes."""


@main.command("build-core")
@click.option("--market", type=click.Choice(["CN", "US"]), required=True, help="Market to build")
@click.option("--as-of", required=True, help="Universe effective date, e.g. 2026-05-25")
@click.option("--universe-id", default=None, help="Override target universe id")
@click.option("--custom-csv", multiple=True, type=click.Path(path_type=Path), help="Additional custom universe CSV")
@click.option("--include-default-custom/--no-include-default-custom", default=True, show_default=True)
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def build_core(
    market: str,
    as_of: str,
    universe_id: str | None,
    custom_csv: tuple[Path, ...],
    include_default_custom: bool,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    custom_paths = list(custom_csv)
    if include_default_custom and DEFAULT_CUSTOM_UNIVERSES[market].exists():
        custom_paths.append(DEFAULT_CUSTOM_UNIVERSES[market])
    if market == "CN":
        result = build_cn_core_universe(as_of=as_of, universe_id=universe_id or "cn_core", custom_csv_paths=custom_paths)
    else:
        result = build_us_core_universe(as_of=as_of, universe_id=universe_id or "us_core", custom_csv_paths=custom_paths)
    members_written = persist_core_universe(
        result,
        universe_storage=MySQLUniverseStorage(config=config),
        market_data_storage=MySQLMarketDataStorage(config=config),
    )
    click.echo(
        "Core universe build complete: "
        f"universe_id={result.universe.universe_id} "
        f"market={market} "
        f"members={len(result.members)} "
        f"instruments={len(result.instruments)} "
        f"aliases={len(result.aliases)} "
        f"members_written={members_written}"
    )


if __name__ == "__main__":
    main()
