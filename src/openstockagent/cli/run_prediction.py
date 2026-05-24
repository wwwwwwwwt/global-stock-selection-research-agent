"""CLI to fetch data and run Kronos prediction for a single stock."""
import click

from openstockagent.config import KRONOS_PRED_LEN
from openstockagent.data.feeds.yahoo import YahooFinanceFeed
from openstockagent.predictors.kronos_adapter import KronosStockPredictor


@click.command()
@click.argument("symbol")
@click.option("--period", default="6mo", help="Historical data period (e.g. 3mo, 1y)")
@click.option("--horizon", default=KRONOS_PRED_LEN, help="Prediction horizon (candles)")
@click.option("--model", default="small", help="Kronos variant: mini/small/base")
def main(symbol: str, period: str, horizon: int, model: str):
    click.echo(f"Fetching {period} data for {symbol}...")
    feed = YahooFinanceFeed()
    df = feed.fetch_ohlcv(symbol, period=period)
    click.echo(f"Loaded {len(df)} rows from {df.index[0].date()} to {df.index[-1].date()}")

    click.echo(f"Loading Kronos ({model})...")
    predictor = KronosStockPredictor(variant=model, device="cpu")

    click.echo(f"Predicting next {horizon} candles...")
    result = predictor.predict(symbol, df, horizon=horizon)

    click.echo("\n--- Prediction Result ---")
    click.echo(f"Model: {result.model_name}")
    click.echo(f"Confidence: {result.confidence:.4f}")
    click.echo(f"\nForecast:\n{result.forecast.to_string()}")


if __name__ == "__main__":
    main()
