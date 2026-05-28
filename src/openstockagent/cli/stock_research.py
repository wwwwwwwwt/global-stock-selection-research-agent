"""Research evaluation commands."""
import json

import click

from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.database.mysql import MySQLConfig
from openstockagent.research.evaluation import evaluate_screen_run
from openstockagent.research.storage import MySQLResearchStorage
from openstockagent.screening.storage import MySQLScreeningStorage


@click.group()
def main():
    """Evaluate and backtest stock-selection research outputs."""


@main.command("evaluate-screen")
@click.option("--screen-run-id", required=True, help="Screen run id to evaluate")
@click.option("--as-of", required=True, help="Selection date, e.g. 2026-05-28")
@click.option("--horizon-days", default=5, show_default=True, help="Forward trading bars to evaluate")
@click.option("--top-n", default=20, show_default=True, help="Top ranked selected candidates to evaluate")
@click.option("--universe", "universe_id", default=None, help="Optional universe id for result metadata")
@click.option("--interval", default="1d", show_default=True, help="Stored bar interval")
@click.option("--source", default=None, help="Optional bar source filter")
@click.option("--adjustment", default="split_adjusted", show_default=True, help="Bar adjustment filter")
@click.option("--benchmark-instrument-id", default=None, help="Optional benchmark instrument id for excess return")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def evaluate_screen(
    screen_run_id: str,
    as_of: str,
    horizon_days: int,
    top_n: int,
    universe_id: str | None,
    interval: str,
    source: str | None,
    adjustment: str,
    benchmark_instrument_id: str | None,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    result = evaluate_screen_run(
        screen_run_id=screen_run_id,
        as_of=as_of,
        horizon_days=horizon_days,
        top_n=top_n,
        universe_id=universe_id,
        interval=interval,
        source=source,
        adjustment=adjustment,
        benchmark_instrument_id=benchmark_instrument_id,
        screening_storage=MySQLScreeningStorage(config=config),
        bar_storage=MySQLMarketDataStorage(config=config),
        evaluation_storage=MySQLResearchStorage(config=config),
    )
    summary = json.loads(result.run.summary_json)
    click.echo(
        "Screen evaluation complete: "
        f"run_id={result.run.run_id} "
        f"screen_run_id={screen_run_id} "
        f"as_of={as_of} "
        f"horizon_days={horizon_days} "
        f"top_n={top_n} "
        f"evaluated_count={summary['evaluated_count']} "
        f"skipped_count={summary['skipped_count']} "
        f"hit_rate={_fmt(summary['hit_rate'])} "
        f"mean_return={_fmt(summary['mean_return'])} "
        f"median_return={_fmt(summary['median_return'])} "
        f"mean_excess_return={_fmt(summary.get('mean_excess_return'))}"
    )
    for item in result.results[:top_n]:
        click.echo(
            f"{item.rank}. {item.instrument_id} "
            f"return={item.forward_return:.6f} "
            f"excess={_fmt(item.excess_return)} "
            f"max_drawdown={_fmt(item.max_drawdown)} "
            f"entry={item.entry_date}:{item.entry_price:.4f} "
            f"exit={item.exit_date}:{item.exit_price:.4f}"
        )
    if result.errors:
        click.echo("Skipped:")
        for error in result.errors[:20]:
            click.echo(f"- {error}")


def _fmt(value) -> str:
    return "n/a" if value is None else f"{float(value):.6f}"


if __name__ == "__main__":
    main()
