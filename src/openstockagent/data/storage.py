from pathlib import Path
import sqlite3

import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias, PredictionRun, TechnicalSignal, utc_now_iso


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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    exchange TEXT,
                    asset_type TEXT NOT NULL,
                    currency TEXT,
                    name TEXT,
                    timezone TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS instrument_aliases (
                    instrument_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_symbol TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(source, source_symbol)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bars (
                    instrument_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    local_date TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    source TEXT NOT NULL,
                    adjustment TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL,
                    amount REAL,
                    currency TEXT,
                    is_complete INTEGER NOT NULL DEFAULT 1,
                    provider_payload_hash TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(instrument_id, interval, timestamp, source, adjustment)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feed_runs (
                    run_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    requested_symbols_json TEXT,
                    requested_interval TEXT,
                    requested_start TEXT,
                    requested_end TEXT,
                    rows_fetched INTEGER DEFAULT 0,
                    rows_inserted INTEGER DEFAULT 0,
                    rows_updated INTEGER DEFAULT 0,
                    error_message TEXT,
                    metadata_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_quality_issues (
                    issue_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    instrument_id TEXT,
                    interval TEXT,
                    timestamp TEXT,
                    severity TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prediction_runs (
                    run_id TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    model_variant TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    lookback_start TEXT NOT NULL,
                    lookback_end TEXT NOT NULL,
                    horizon INTEGER NOT NULL,
                    source_selection_json TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS predicted_bars (
                    run_id TEXT NOT NULL,
                    forecast_timestamp TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL,
                    amount REAL,
                    confidence REAL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, forecast_timestamp)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS technical_features (
                    instrument_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    feature_name TEXT NOT NULL,
                    feature_value REAL,
                    window TEXT,
                    params_json TEXT,
                    input_range_start TEXT NOT NULL,
                    input_range_end TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(instrument_id, interval, timestamp, feature_name, params_json)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS technical_signals (
                    signal_id TEXT PRIMARY KEY,
                    instrument_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    strength REAL NOT NULL,
                    confidence REAL,
                    severity TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    input_range_start TEXT NOT NULL,
                    input_range_end TEXT NOT NULL,
                    created_at TEXT NOT NULL
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

        records = df[["symbol", "date", "open", "high", "low", "close", "volume"]].to_dict("records")

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO ohlcv (symbol, date, open, high, low, close, volume)
                   VALUES (:symbol, :date, :open, :high, :low, :close, :volume)""",
                records
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

    def upsert_instrument(self, instrument: Instrument) -> None:
        now = utc_now_iso()
        record = instrument.to_record() | {"created_at": now, "updated_at": now}
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO instruments (
                    instrument_id, symbol, market, exchange, asset_type, currency,
                    name, timezone, active, metadata_json, created_at, updated_at
                ) VALUES (
                    :instrument_id, :symbol, :market, :exchange, :asset_type, :currency,
                    :name, :timezone, :active, :metadata_json, :created_at, :updated_at
                )
                ON CONFLICT(instrument_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    market=excluded.market,
                    exchange=excluded.exchange,
                    asset_type=excluded.asset_type,
                    currency=excluded.currency,
                    name=excluded.name,
                    timezone=excluded.timezone,
                    active=excluded.active,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                record,
            )

    def upsert_instrument_alias(self, alias: InstrumentAlias) -> None:
        record = alias.to_record() | {"created_at": utc_now_iso()}
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO instrument_aliases (
                    instrument_id, source, source_symbol, priority, created_at
                ) VALUES (
                    :instrument_id, :source, :source_symbol, :priority, :created_at
                )""",
                record,
            )

    def resolve_alias(self, source: str, source_symbol: str) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT instrument_id FROM instrument_aliases
                   WHERE source = ? AND source_symbol = ?
                   ORDER BY priority ASC LIMIT 1""",
                (source, source_symbol),
            ).fetchone()
        return row[0] if row else None

    def upsert_bars(self, df: pd.DataFrame) -> int:
        records_df = df.copy()
        now = utc_now_iso()
        defaults = {
            "volume": None,
            "amount": None,
            "currency": None,
            "is_complete": 1,
            "provider_payload_hash": None,
            "created_at": now,
            "updated_at": now,
        }
        for column, value in defaults.items():
            if column not in records_df.columns:
                records_df[column] = value
        records_df["updated_at"] = now
        records = records_df.to_dict("records")
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """INSERT INTO bars (
                    instrument_id, timestamp, local_date, interval, source, adjustment,
                    open, high, low, close, volume, amount, currency, is_complete,
                    provider_payload_hash, created_at, updated_at
                ) VALUES (
                    :instrument_id, :timestamp, :local_date, :interval, :source, :adjustment,
                    :open, :high, :low, :close, :volume, :amount, :currency, :is_complete,
                    :provider_payload_hash, :created_at, :updated_at
                )
                ON CONFLICT(instrument_id, interval, timestamp, source, adjustment) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    amount=excluded.amount,
                    currency=excluded.currency,
                    is_complete=excluded.is_complete,
                    provider_payload_hash=excluded.provider_payload_hash,
                    updated_at=excluded.updated_at
                """,
                records,
            )
        return len(records)

    def load_bars(self, instrument_id: str, interval: str, start: str, end: str) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(
                """SELECT * FROM bars
                   WHERE instrument_id = ?
                     AND interval = ?
                     AND timestamp >= ?
                     AND timestamp <= ?
                   ORDER BY timestamp ASC""",
                conn,
                params=(instrument_id, interval, start, end),
            )

    def load_kronos_frame(
        self,
        instrument_id: str,
        interval: str,
        lookback: int = 512,
        adjustment: str = "split_adjusted",
    ) -> pd.DataFrame:
        columns = ["open", "high", "low", "close", "volume", "amount"]
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                """SELECT timestamp, open, high, low, close, volume, amount
                   FROM bars
                   WHERE instrument_id = ?
                     AND interval = ?
                     AND adjustment = ?
                     AND is_complete = 1
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                conn,
                params=(instrument_id, interval, adjustment, lookback),
            )
        if df.empty:
            return pd.DataFrame(columns=columns)
        df = df.sort_values("timestamp")
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        for column in columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        return df.set_index("timestamp")[columns]

    def save_prediction_run(self, run: PredictionRun, predicted_bars: pd.DataFrame) -> str:
        now = utc_now_iso()
        run_record = run.to_record() | {"created_at": now}
        predicted_df = predicted_bars.copy()
        predicted_df["run_id"] = run.run_id
        predicted_df["created_at"] = now
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO prediction_runs (
                    run_id, model_name, model_variant, instrument_id, interval,
                    lookback_start, lookback_end, horizon, source_selection_json,
                    metadata_json, created_at
                ) VALUES (
                    :run_id, :model_name, :model_variant, :instrument_id, :interval,
                    :lookback_start, :lookback_end, :horizon, :source_selection_json,
                    :metadata_json, :created_at
                )""",
                run_record,
            )
            conn.executemany(
                """INSERT OR REPLACE INTO predicted_bars (
                    run_id, forecast_timestamp, step, open, high, low, close,
                    volume, amount, confidence, created_at
                ) VALUES (
                    :run_id, :forecast_timestamp, :step, :open, :high, :low, :close,
                    :volume, :amount, :confidence, :created_at
                )""",
                predicted_df.to_dict("records"),
            )
        return run.run_id

    def load_latest_prediction_summary(self, instrument_id: str, interval: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            run = conn.execute(
                """SELECT run_id, model_name, model_variant, horizon, created_at
                   FROM prediction_runs
                   WHERE instrument_id = ? AND interval = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (instrument_id, interval),
            ).fetchone()
            if run is None:
                return None
            rows = conn.execute(
                """SELECT close FROM predicted_bars
                   WHERE run_id = ?
                   ORDER BY step ASC""",
                (run[0],),
            ).fetchall()
        closes = [row[0] for row in rows]
        return {
            "run_id": run[0],
            "model_name": run[1],
            "model_variant": run[2],
            "horizon": run[3],
            "forecast_close_min": min(closes) if closes else None,
            "forecast_close_max": max(closes) if closes else None,
            "created_at": run[4],
        }

    def save_technical_signals(self, signals: list[TechnicalSignal]) -> int:
        records = [signal.to_record() for signal in signals]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO technical_signals (
                    signal_id, instrument_id, timestamp, interval, signal_type,
                    direction, strength, confidence, severity, summary, evidence_json,
                    input_range_start, input_range_end, created_at
                ) VALUES (
                    :signal_id, :instrument_id, :timestamp, :interval, :signal_type,
                    :direction, :strength, :confidence, :severity, :summary, :evidence_json,
                    :input_range_start, :input_range_end, :created_at
                )""",
                records,
            )
        return len(records)

    def load_recent_technical_signals(self, instrument_id: str, interval: str, limit: int = 10) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = pd.read_sql_query(
                """SELECT * FROM technical_signals
                   WHERE instrument_id = ? AND interval = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                conn,
                params=(instrument_id, interval, limit),
            )
        return rows.to_dict("records")
