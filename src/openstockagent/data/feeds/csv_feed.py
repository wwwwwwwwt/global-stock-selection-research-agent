from pathlib import Path

import pandas as pd


class CsvFeed:
    source = "csv"

    def __init__(self, path: Path):
        self.path = path

    def fetch_bars(
        self,
        source_symbol: str,
        interval: str,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        df = pd.read_csv(self.path)
        expected = ["timestamp", "open", "high", "low", "close", "volume"]
        missing = [column for column in expected if column not in df.columns]
        if missing:
            raise ValueError(f"CSV feed missing required columns: {missing}")
        if "amount" not in df.columns:
            df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
        return df[["timestamp", "open", "high", "low", "close", "volume", "amount"]]
