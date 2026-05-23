import sqlite3
import pandas as pd
from pathlib import Path


class SQLiteStorage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    PRIMARY KEY (symbol, date)
                )
            """)

    def save_ohlcv(self, symbol: str, df: pd.DataFrame):
        df = df.copy()
        df["symbol"] = symbol
        df = df.reset_index()
        if "date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "date"})
        # Convert datetime to string for SQLite
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        with sqlite3.connect(self.db_path) as conn:
            # Use REPLACE to avoid duplicates
            df[["symbol", "date", "open", "high", "low", "close", "volume"]].to_sql(
                "ohlcv", conn, if_exists="append", index=False
            )

    def load_ohlcv(self, symbol: str) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                "SELECT date, open, high, low, close, volume FROM ohlcv WHERE symbol = ? ORDER BY date",
                conn, params=(symbol,), parse_dates=["date"]
            )
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return df.set_index("date")
