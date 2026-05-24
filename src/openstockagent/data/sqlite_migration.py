"""One-time migration from the legacy SQLite market database into MySQL."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias, PredictionRun, TechnicalSignal
from openstockagent.data.storage import MySQLMarketDataStorage


@dataclass(frozen=True)
class SQLiteMigrationResult:
    sqlite_path: str
    instruments: int = 0
    aliases: int = 0
    bars: int = 0
    feed_runs: int = 0
    data_quality_issues: int = 0
    prediction_runs: int = 0
    predicted_bars: int = 0
    technical_signals: int = 0
    legacy_ohlcv_rows_skipped: int = 0


def migrate_sqlite_market_data(
    sqlite_path: Path,
    target_storage: MySQLMarketDataStorage,
    chunk_size: int = 5000,
) -> SQLiteMigrationResult:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    counts = {
        "instruments": 0,
        "aliases": 0,
        "bars": 0,
        "feed_runs": 0,
        "data_quality_issues": 0,
        "prediction_runs": 0,
        "predicted_bars": 0,
        "technical_signals": 0,
        "legacy_ohlcv_rows_skipped": 0,
    }

    with sqlite3.connect(sqlite_path) as conn:
        if _table_exists(conn, "instruments"):
            for row in _rows(conn, "SELECT * FROM instruments ORDER BY instrument_id"):
                target_storage.upsert_instrument(
                    Instrument(
                        instrument_id=row["instrument_id"],
                        symbol=row["symbol"],
                        market=row["market"],
                        exchange=row["exchange"],
                        asset_type=row["asset_type"],
                        currency=row["currency"],
                        name=row["name"],
                        timezone=row["timezone"],
                        active=bool(row["active"]),
                        metadata_json=row["metadata_json"],
                    )
                )
                counts["instruments"] += 1

        if _table_exists(conn, "instrument_aliases"):
            for row in _rows(conn, "SELECT * FROM instrument_aliases ORDER BY source, source_symbol"):
                target_storage.upsert_instrument_alias(
                    InstrumentAlias(
                        instrument_id=row["instrument_id"],
                        source=row["source"],
                        source_symbol=row["source_symbol"],
                        priority=int(row["priority"]),
                    )
                )
                counts["aliases"] += 1

        if _table_exists(conn, "bars"):
            for chunk in pd.read_sql_query("SELECT * FROM bars ORDER BY instrument_id, interval, timestamp", conn, chunksize=chunk_size):
                counts["bars"] += target_storage.upsert_bars(chunk)

        if _table_exists(conn, "feed_runs"):
            records = _rows(conn, "SELECT * FROM feed_runs ORDER BY started_at, run_id")
            counts["feed_runs"] += target_storage.upsert_feed_run_records(records)

        if _table_exists(conn, "data_quality_issues"):
            records = _rows(conn, "SELECT * FROM data_quality_issues ORDER BY created_at, issue_id")
            counts["data_quality_issues"] += target_storage.upsert_data_quality_issue_records(records)

        if _table_exists(conn, "prediction_runs"):
            for row in _rows(conn, "SELECT * FROM prediction_runs ORDER BY created_at, run_id"):
                predicted = pd.read_sql_query(
                    """SELECT forecast_timestamp, step, open, high, low, close, volume, amount, confidence
                       FROM predicted_bars
                       WHERE run_id = ?
                       ORDER BY step ASC""",
                    conn,
                    params=[row["run_id"]],
                )
                target_storage.save_prediction_run(
                    PredictionRun(
                        run_id=row["run_id"],
                        model_name=row["model_name"],
                        model_variant=row["model_variant"],
                        instrument_id=row["instrument_id"],
                        interval=row["interval"],
                        lookback_start=row["lookback_start"],
                        lookback_end=row["lookback_end"],
                        horizon=int(row["horizon"]),
                        source_selection_json=row["source_selection_json"],
                        metadata_json=row["metadata_json"],
                    ),
                    predicted,
                )
                counts["prediction_runs"] += 1
                counts["predicted_bars"] += len(predicted)

        if _table_exists(conn, "technical_signals"):
            signals = []
            for row in _rows(conn, "SELECT * FROM technical_signals ORDER BY timestamp, signal_id"):
                signals.append(
                    TechnicalSignal(
                        signal_id=row["signal_id"],
                        instrument_id=row["instrument_id"],
                        timestamp=row["timestamp"],
                        interval=row["interval"],
                        signal_type=row["signal_type"],
                        direction=row["direction"],
                        strength=float(row["strength"]),
                        confidence=None if row["confidence"] is None else float(row["confidence"]),
                        severity=row["severity"],
                        summary=row["summary"],
                        evidence_json=row["evidence_json"],
                        input_range_start=row["input_range_start"],
                        input_range_end=row["input_range_end"],
                        created_at=row["created_at"],
                    )
                )
                if len(signals) >= chunk_size:
                    counts["technical_signals"] += target_storage.save_technical_signals(signals)
                    signals = []
            counts["technical_signals"] += target_storage.save_technical_signals(signals)

        if _table_exists(conn, "ohlcv"):
            row = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()
            counts["legacy_ohlcv_rows_skipped"] = int(row[0] or 0)

    return SQLiteMigrationResult(sqlite_path=str(sqlite_path), **counts)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        [table_name],
    ).fetchone()
    return row is not None


def _rows(conn: sqlite3.Connection, sql: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql).fetchall()]
