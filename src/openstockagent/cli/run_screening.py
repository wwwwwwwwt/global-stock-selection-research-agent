"""Run factor-based screening for a universe."""
import click

from openstockagent.database.mysql import MySQLConfig
from openstockagent.factors.storage import MySQLFactorStorage
from openstockagent.screening.runner import ScreeningRunResult, run_screening_pipeline
from openstockagent.screening.scoring import build_default_strategy
from openstockagent.screening.storage import MySQLScreeningStorage
from openstockagent.universe.storage import MySQLUniverseStorage


@click.command()
@click.argument("universe_id")
@click.option("--as-of", required=True, help="Trade date for screening, e.g. 2026-05-24")
@click.option("--interval", default="1d", help="Bar interval")
@click.option("--top-n", default=20, show_default=True, help="Number of selected candidates")
@click.option("--min-turnover", default=0.0, show_default=True, help="Minimum 20-day average amount")
@click.option("--min-bar-count", default=0, show_default=True, help="Minimum available bar count")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def main(
    universe_id: str,
    as_of: str,
    interval: str,
    top_n: int,
    min_turnover: float,
    min_bar_count: int,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    strategy = build_default_strategy(
        hard_filters={
            "min_turnover_amount_20d": min_turnover,
            "min_bar_count": min_bar_count,
        },
        max_candidates=top_n,
    )
    result = run_screening_pipeline(
        universe_id=universe_id,
        as_of=as_of,
        interval=interval,
        universe_storage=MySQLUniverseStorage(config=config),
        factor_storage=MySQLFactorStorage(config=config),
        screening_storage=MySQLScreeningStorage(config=config),
        strategy=strategy,
    )
    click.echo(
        "Screening run complete: "
        f"run_id={result.run_id} "
        f"universe_id={result.universe_id} "
        f"trade_date={result.trade_date} "
        f"candidates_seen={result.candidates_seen} "
        f"factor_values_seen={result.factor_values_seen} "
        f"ranked_count={result.ranked_count} "
        f"selected_count={result.selected_count} "
        f"filtered_count={result.filtered_count}"
    )
    if result.errors:
        click.echo("Errors:")
        for error in result.errors:
            click.echo(f"- {error}")
    selected_results = [screen_result for screen_result in result.results if screen_result.selected]
    if selected_results:
        click.echo("Selected candidates:")
        for screen_result in selected_results:
            click.echo(f"{screen_result.rank}. {screen_result.instrument_id} score={screen_result.total_score:.6f}")


if __name__ == "__main__":
    main()
