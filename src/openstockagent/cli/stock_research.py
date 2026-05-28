"""Research evaluation commands."""
import json

import click

from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.database.mysql import MySQLConfig
from openstockagent.factors.storage import MySQLFactorStorage
from openstockagent.market.storage import MySQLMarketRealityStorage
from openstockagent.research.evaluation import evaluate_screen_run
from openstockagent.research.rolling import run_rolling_screen_evaluation
from openstockagent.research.storage import MySQLResearchStorage
from openstockagent.screening.storage import MySQLScreeningStorage
from openstockagent.universe.storage import MySQLUniverseStorage


@click.group()
def main():
    """Evaluate and backtest stock-selection research outputs."""


@main.command("init-db")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def init_db(mysql_url: str, mysql_user: str, mysql_password: str):
    """Create research evaluation tables if they do not exist."""
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    MySQLResearchStorage(config=config)
    click.echo("Research storage initialized")


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


@main.command("rolling-screen")
@click.option("--universe", "universe_id", required=True, help="Universe id to evaluate")
@click.option("--start-date", required=True, help="First rebalance date boundary")
@click.option("--end-date", required=True, help="Last rebalance date boundary")
@click.option("--horizon-days", default=5, show_default=True, help="Forward trading bars to evaluate")
@click.option(
    "--rebalance",
    "rebalance_frequency",
    type=click.Choice(["daily", "weekly", "monthly"]),
    default="weekly",
    show_default=True,
)
@click.option("--market", default=None, help="Market calendar to use for rebalance dates, e.g. CN or US")
@click.option("--top-n", default=20, show_default=True, help="Top selected candidates per rebalance date")
@click.option("--lookback-days", default=365, show_default=True, help="Stored bar lookback for factor calculation")
@click.option("--interval", default="1d", show_default=True, help="Stored bar interval")
@click.option("--source", default=None, help="Optional bar source filter")
@click.option("--adjustment", default="split_adjusted", show_default=True, help="Bar adjustment filter")
@click.option("--benchmark-instrument-id", default=None, help="Optional benchmark instrument id for excess return")
@click.option("--max-dates", type=int, default=None, help="Limit rebalance dates for smoke tests")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def rolling_screen(
    universe_id: str,
    start_date: str,
    end_date: str,
    horizon_days: int,
    rebalance_frequency: str,
    market: str | None,
    top_n: int,
    lookback_days: int,
    interval: str,
    source: str | None,
    adjustment: str,
    benchmark_instrument_id: str | None,
    max_dates: int | None,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    market_reality_storage = MySQLMarketRealityStorage(config=config)
    result = run_rolling_screen_evaluation(
        universe_id=universe_id,
        start_date=start_date,
        end_date=end_date,
        horizon_days=horizon_days,
        rebalance_frequency=rebalance_frequency,
        market=market,
        top_n=top_n,
        lookback_days=lookback_days,
        interval=interval,
        source=source,
        adjustment=adjustment,
        benchmark_instrument_id=benchmark_instrument_id,
        max_dates=max_dates,
        universe_storage=MySQLUniverseStorage(config=config),
        bar_storage=MySQLMarketDataStorage(config=config),
        factor_storage=MySQLFactorStorage(config=config),
        screening_storage=MySQLScreeningStorage(config=config),
        research_storage=MySQLResearchStorage(config=config),
        market_reality_storage=market_reality_storage,
        calendar_storage=market_reality_storage,
    )
    summary = json.loads(result.experiment.summary_json)
    click.echo(
        "Rolling screen evaluation complete: "
        f"experiment_id={result.experiment.experiment_id} "
        f"universe_id={universe_id} "
        f"period={start_date}..{end_date} "
        f"rebalance={rebalance_frequency} "
        f"horizon_days={horizon_days} "
        f"top_n={top_n} "
        f"dates_seen={summary['dates_seen']} "
        f"screen_runs_created={summary['screen_runs_created']} "
        f"backtest_runs_created={summary['backtest_runs_created']} "
        f"evaluated_count={summary['evaluated_count']} "
        f"skipped_count={summary['skipped_count']} "
        f"hit_rate={_fmt(summary['hit_rate'])} "
        f"mean_return={_fmt(summary['mean_return'])} "
        f"mean_excess_return={_fmt(summary['mean_excess_return'])} "
        f"mean_max_drawdown={_fmt(summary['mean_max_drawdown'])}"
    )
    if result.errors:
        click.echo("Errors:")
        for error in result.errors[:20]:
            click.echo(f"- {error}")


def _fmt(value) -> str:
    return "n/a" if value is None else f"{float(value):.6f}"


if __name__ == "__main__":
    main()
