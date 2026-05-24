from abc import ABC, abstractmethod

import pandas as pd


class BaseMarketDataFeed(ABC):
    source: str

    @abstractmethod
    def fetch_bars(
        self,
        source_symbol: str,
        interval: str,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        ...


class BaseDataFeed(ABC):
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        """
        Backward-compatible interface for existing Week 1 code.
        New code should use BaseMarketDataFeed.fetch_bars.
        """
        ...
