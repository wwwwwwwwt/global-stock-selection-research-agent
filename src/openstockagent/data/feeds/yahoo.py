import yfinance as yf
import pandas as pd
from .base import BaseDataFeed


class YahooFinanceFeed(BaseDataFeed):
    def fetch_ohlcv(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df.empty:
            raise ValueError(f"No data returned for {symbol}")

        # Standardize columns
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })
        df = df[["open", "high", "low", "close", "volume"]]
        df.index = df.index.tz_localize(None)  # Remove timezone for simplicity
        return df
