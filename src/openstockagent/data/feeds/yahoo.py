import pandas as pd
import yfinance as yf

from .base import BaseDataFeed, BaseMarketDataFeed


class YahooFinanceFeed(BaseDataFeed, BaseMarketDataFeed):
    source = "yahoo"

    def __init__(self, ticker_factory=None, timeout: int = 10, repair: bool = True):
        self.ticker_factory = ticker_factory or yf.Ticker
        self.timeout = timeout
        self.repair = repair

    def fetch_bars(
        self,
        source_symbol: str,
        interval: str,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        if period is None and (start is None or end is None):
            raise ValueError("YahooFinanceFeed requires period or both start and end")

        ticker = self.ticker_factory(source_symbol)
        kwargs = {
            "interval": interval,
            "auto_adjust": adjusted,
            "repair": self.repair,
            "timeout": self.timeout,
            "raise_errors": True,
        }
        if period:
            kwargs["period"] = period
        else:
            kwargs["start"] = start
            kwargs["end"] = end
        df = ticker.history(**kwargs)
        if df.empty:
            raise ValueError(f"No data returned for {source_symbol}")

        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.reset_index().rename(columns={df.index.name or "Date": "timestamp"})
        if "timestamp" not in df.columns:
            df = df.rename(columns={df.columns[0]: "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
        return df[["timestamp", "open", "high", "low", "close", "volume", "amount"]]

    def fetch_ohlcv(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        df = self.fetch_bars(symbol, interval="1d", period=period)
        df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        return df.set_index("date")[["open", "high", "low", "close", "volume"]]
