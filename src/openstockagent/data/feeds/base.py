from abc import ABC, abstractmethod
import pandas as pd


class BaseDataFeed(ABC):
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        """
        Fetch OHLCV data.

        Returns DataFrame with columns: [open, high, low, close, volume]
        Index: datetime (business days)
        """
        ...
