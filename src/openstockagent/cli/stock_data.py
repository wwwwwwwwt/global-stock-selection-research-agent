"""Market data synchronization commands."""
import os

import click

from openstockagent.data.feeds.akshare import AkShareAStockFeed
from openstockagent.data.feeds.polygon import PolygonStockFeed
from openstockagent.data.feeds.registry import FeedRegistry
from openstockagent.data.feeds.tushare import TUSHARE_TOKEN_ENV, TushareAStockFeed, TushareReferenceFeed
from openstockagent.data.storage import MySQLMarketDataStorage
from openstockagent.data.sync import build_sync_plan, run_data_sync_plan
from openstockagent.data.sync_storage import MySQLDataSyncStorage
from openstockagent.database.mysql import MySQLConfig
from openstockagent.factors.storage import MySQLFactorStorage
from openstockagent.market.storage import MySQLMarketRealityStorage
from openstockagent.pipelines.cn_daily_selection import run_cn_daily_selection_pipeline
from openstockagent.pipelines.tushare_daily_batch import run_tushare_daily_batch_sync
from openstockagent.pipelines.tushare_reference import run_tushare_reference_sync
from openstockagent.portfolio.storage import MySQLPortfolioStorage
from openstockagent.recommendations.storage import MySQLRecommendationStorage
from openstockagent.screening.storage import MySQLScreeningStorage
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
        feed = PolygonStockFeed()
        feed_registry.register("US", "equity", interval, feed)
    else:
        feed = _cn_feed_from_env()
        feed_registry.register("CN", "equity", interval, feed)
    plan = build_sync_plan(
        universe_id=universe_id,
        market=market,
        mode=mode,
        interval=interval,
        provider=feed.source,
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


@main.command("sync-cn-reference")
@click.option("--start", required=True, help="Reference sync start date, e.g. 2026-05-01")
@click.option("--end", required=True, help="Reference sync end date, e.g. 2026-05-28")
@click.option("--status-date", default=None, help="Status date for ST/suspend/limit/adj_factor; defaults to --end")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def sync_cn_reference(
    start: str,
    end: str,
    status_date: str | None,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    """Synchronize Tushare A-share reference and market-reality data."""
    token = os.getenv(TUSHARE_TOKEN_ENV)
    if not token:
        raise click.ClickException(f"{TUSHARE_TOKEN_ENV} is required for Tushare reference sync")
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    result = run_tushare_reference_sync(
        start=start,
        end=end,
        status_date=status_date or end,
        reference_feed=TushareReferenceFeed(token=token),
        market_data_storage=MySQLMarketDataStorage(config=config),
        market_reality_storage=MySQLMarketRealityStorage(config=config),
    )
    click.echo(
        "Tushare reference sync complete: "
        f"market={result.market} "
        f"period={result.start}..{result.end} "
        f"status_date={result.status_date} "
        f"instruments_written={result.instruments_written} "
        f"aliases_written={result.aliases_written} "
        f"calendar_days_written={result.calendar_days_written} "
        f"statuses_written={result.statuses_written} "
        f"corporate_actions_written={result.corporate_actions_written}"
    )


@main.command("sync-cn-daily")
@click.option("--universe", "universe_id", required=True, help="Universe id to filter full-market Tushare rows")
@click.option("--trade-date", required=True, help="A-share trade date, e.g. 2026-05-27")
@click.option("--max-symbols", type=int, default=None, help="Limit universe members for smoke tests")
@click.option("--skip-bars", is_flag=True, help="Skip daily OHLCV bar ingestion")
@click.option("--skip-daily-basic", is_flag=True, help="Skip daily_basic factor ingestion")
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def sync_cn_daily(
    universe_id: str,
    trade_date: str,
    max_symbols: int | None,
    skip_bars: bool,
    skip_daily_basic: bool,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    """Synchronize Tushare A-share trade-date batch bars and daily_basic factors."""
    token = os.getenv(TUSHARE_TOKEN_ENV)
    if not token:
        raise click.ClickException(f"{TUSHARE_TOKEN_ENV} is required for Tushare daily batch sync")
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    result = run_tushare_daily_batch_sync(
        universe_id=universe_id,
        trade_date=trade_date,
        reference_feed=TushareReferenceFeed(token=token),
        universe_storage=MySQLUniverseStorage(config=config),
        bar_storage=MySQLMarketDataStorage(config=config),
        factor_storage=MySQLFactorStorage(config=config),
        include_bars=not skip_bars,
        include_daily_basic=not skip_daily_basic,
        max_symbols=max_symbols,
    )
    click.echo(
        "Tushare daily batch sync complete: "
        f"universe_id={result.universe_id} "
        f"trade_date={result.trade_date} "
        f"members_seen={result.members_seen} "
        f"instruments_matched={result.instruments_matched} "
        f"daily_rows_seen={result.daily_rows_seen} "
        f"daily_basic_rows_seen={result.daily_basic_rows_seen} "
        f"bars_written={result.bars_written} "
        f"factor_values_written={result.factor_values_written}"
    )


@main.command("run-cn-selection")
@click.option("--universe", "universe_id", default="cn_core", show_default=True, help="Universe id to screen")
@click.option("--trade-date", required=True, help="A-share trade date, e.g. 2026-05-27")
@click.option("--reference-start", default=None, help="Reference sync start date; defaults to trade date")
@click.option("--horizon", type=click.Choice(["1d", "5d", "20d", "60d"]), default="5d", show_default=True)
@click.option(
    "--market-regime",
    type=click.Choice(["risk_on", "neutral", "risk_off", "high_risk", "data_bad", "unknown"]),
    default="neutral",
    show_default=True,
)
@click.option("--top-n", default=10, show_default=True, help="Selected screen and recommendation count")
@click.option("--max-symbols", type=int, default=None, help="Limit data sync members for smoke tests")
@click.option("--min-turnover", default=0.0, show_default=True, help="Minimum 20-day average amount")
@click.option("--min-bar-count", default=0, show_default=True, help="Minimum available bar count")
@click.option("--skip-reference", is_flag=True, help="Skip Tushare reference/status sync")
@click.option("--skip-daily-sync", is_flag=True, help="Skip Tushare daily/daily_basic sync")
@click.option("--skip-portfolio", is_flag=True, help="Skip portfolio decision creation")
@click.option("--account-id", default="paper-cn", show_default=True)
@click.option("--capital", default=100000.0, show_default=True, type=float)
@click.option("--base-currency", default="CNY", show_default=True)
@click.option("--mysql-url", default="jdbc:mysql://127.0.0.1:13306/openstockagent", help="MySQL JDBC URL")
@click.option("--mysql-user", default="root", help="MySQL username")
@click.option("--mysql-password", default="123456", help="MySQL password")
def run_cn_selection(
    universe_id: str,
    trade_date: str,
    reference_start: str | None,
    horizon: str,
    market_regime: str,
    top_n: int,
    max_symbols: int | None,
    min_turnover: float,
    min_bar_count: int,
    skip_reference: bool,
    skip_daily_sync: bool,
    skip_portfolio: bool,
    account_id: str,
    capital: float,
    base_currency: str,
    mysql_url: str,
    mysql_user: str,
    mysql_password: str,
):
    """Run the full CN daily data-to-portfolio stock-selection workflow."""
    token = os.getenv(TUSHARE_TOKEN_ENV)
    if not token and (not skip_reference or not skip_daily_sync):
        raise click.ClickException(f"{TUSHARE_TOKEN_ENV} is required for Tushare CN selection runs")
    config = MySQLConfig.from_jdbc_url(mysql_url, username=mysql_user, password=mysql_password)
    reference_feed = TushareReferenceFeed(token=token) if token else None
    result = run_cn_daily_selection_pipeline(
        universe_id=universe_id,
        trade_date=trade_date,
        reference_start=reference_start or trade_date,
        reference_feed=reference_feed,
        universe_storage=MySQLUniverseStorage(config=config),
        market_data_storage=MySQLMarketDataStorage(config=config),
        market_reality_storage=MySQLMarketRealityStorage(config=config),
        factor_storage=MySQLFactorStorage(config=config),
        screening_storage=MySQLScreeningStorage(config=config),
        recommendation_storage=MySQLRecommendationStorage(config=config),
        portfolio_storage=None if skip_portfolio else MySQLPortfolioStorage(config=config),
        horizon=horizon,
        market_regime=market_regime,
        top_n=top_n,
        min_turnover=min_turnover,
        min_bar_count=min_bar_count,
        max_symbols=max_symbols,
        run_reference=not skip_reference,
        run_daily_sync=not skip_daily_sync,
        run_portfolio=not skip_portfolio,
        account_id=account_id,
        capital=capital,
        base_currency=base_currency,
    )
    click.echo(
        "CN daily selection complete: "
        f"universe_id={result.universe_id} "
        f"trade_date={result.trade_date} "
        f"screen_run_id={result.screening.run_id} "
        f"recommendation_run_id={result.recommendation.run_id} "
        f"ranked_count={result.screening.ranked_count} "
        f"selected_count={result.screening.selected_count} "
        f"buy_candidate_count={result.recommendation.buy_candidate_count}"
    )
    if result.reference is not None:
        click.echo(
            "Reference: "
            f"instruments_written={result.reference.instruments_written} "
            f"calendar_days_written={result.reference.calendar_days_written} "
            f"statuses_written={result.reference.statuses_written}"
        )
    if result.daily is not None:
        click.echo(
            "Daily data: "
            f"daily_rows_seen={result.daily.daily_rows_seen} "
            f"daily_basic_rows_seen={result.daily.daily_basic_rows_seen} "
            f"bars_written={result.daily.bars_written} "
            f"factor_values_written={result.daily.factor_values_written}"
        )
    selected = [screen_result for screen_result in result.screening.results if screen_result.selected]
    if selected:
        click.echo("Selected candidates:")
        for screen_result in selected:
            click.echo(f"{screen_result.rank}. {screen_result.instrument_id} score={screen_result.total_score:.6f}")
    if result.portfolio is not None:
        click.echo(
            "Portfolio: "
            f"decision_id={result.portfolio.decision.decision_id} "
            f"action={result.portfolio.decision.action} "
            f"target_gross_exposure={result.portfolio.decision.target_gross_exposure:.6f} "
            f"cash_pct={result.portfolio.decision.cash_pct:.6f} "
            f"allocations={len(result.portfolio.allocations)}"
        )


def _cn_feed_from_env():
    token = os.getenv(TUSHARE_TOKEN_ENV)
    if token:
        return TushareAStockFeed(token=token)
    return AkShareAStockFeed()


if __name__ == "__main__":
    main()
