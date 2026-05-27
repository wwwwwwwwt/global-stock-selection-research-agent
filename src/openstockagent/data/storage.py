"""MySQL-backed canonical market data storage."""
from __future__ import annotations

from collections.abc import Callable
import json

import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias, PredictionRun, TechnicalSignal, utc_now_iso
from openstockagent.database.mysql import MySQLConfig


INSTRUMENTS_DDL = """
CREATE TABLE IF NOT EXISTS instruments (
  instrument_id VARCHAR(128) NOT NULL,
  symbol VARCHAR(64) NOT NULL,
  market VARCHAR(32) NOT NULL,
  exchange VARCHAR(64) NULL,
  asset_type VARCHAR(32) NOT NULL,
  currency VARCHAR(16) NULL,
  name VARCHAR(255) NULL,
  timezone VARCHAR(64) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  metadata_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (instrument_id),
  KEY idx_instruments_market_asset (market, asset_type),
  KEY idx_instruments_symbol (symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

INSTRUMENT_ALIASES_DDL = """
CREATE TABLE IF NOT EXISTS instrument_aliases (
  instrument_id VARCHAR(128) NOT NULL,
  source VARCHAR(64) NOT NULL,
  source_symbol VARCHAR(128) NOT NULL,
  priority INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (source, source_symbol),
  KEY idx_instrument_aliases_instrument (instrument_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

BARS_DDL = """
CREATE TABLE IF NOT EXISTS bars (
  instrument_id VARCHAR(128) NOT NULL,
  bar_timestamp VARCHAR(64) NOT NULL,
  local_date DATE NOT NULL,
  bar_interval VARCHAR(16) NOT NULL,
  source VARCHAR(64) NOT NULL,
  adjustment VARCHAR(32) NOT NULL,
  open DOUBLE NOT NULL,
  high DOUBLE NOT NULL,
  low DOUBLE NOT NULL,
  close DOUBLE NOT NULL,
  volume DOUBLE NULL,
  amount DOUBLE NULL,
  currency VARCHAR(16) NULL,
  is_complete TINYINT(1) NOT NULL DEFAULT 1,
  provider_payload_hash VARCHAR(128) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (instrument_id, bar_interval, bar_timestamp, source, adjustment),
  KEY idx_bars_lookup (instrument_id, bar_interval, local_date),
  KEY idx_bars_timestamp (bar_timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

FEED_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS feed_runs (
  run_id VARCHAR(128) NOT NULL,
  source VARCHAR(64) NOT NULL,
  purpose VARCHAR(64) NOT NULL,
  started_at VARCHAR(64) NOT NULL,
  ended_at VARCHAR(64) NULL,
  status VARCHAR(32) NOT NULL,
  requested_symbols_json JSON NULL,
  requested_interval VARCHAR(16) NULL,
  requested_start VARCHAR(64) NULL,
  requested_end VARCHAR(64) NULL,
  rows_fetched INTEGER NOT NULL DEFAULT 0,
  rows_inserted INTEGER NOT NULL DEFAULT 0,
  rows_updated INTEGER NOT NULL DEFAULT 0,
  error_message TEXT NULL,
  metadata_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id),
  KEY idx_feed_runs_source_started (source, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

DATA_QUALITY_ISSUES_DDL = """
CREATE TABLE IF NOT EXISTS data_quality_issues (
  issue_id VARCHAR(128) NOT NULL,
  run_id VARCHAR(128) NULL,
  instrument_id VARCHAR(128) NULL,
  bar_interval VARCHAR(16) NULL,
  bar_timestamp VARCHAR(64) NULL,
  severity VARCHAR(32) NOT NULL,
  issue_type VARCHAR(64) NOT NULL,
  details_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (issue_id),
  KEY idx_data_quality_issues_lookup (instrument_id, bar_interval, bar_timestamp),
  KEY idx_data_quality_issues_run (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

PREDICTION_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS prediction_runs (
  run_id VARCHAR(128) NOT NULL,
  model_name VARCHAR(128) NOT NULL,
  model_variant VARCHAR(64) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  bar_interval VARCHAR(16) NOT NULL,
  lookback_start VARCHAR(64) NOT NULL,
  lookback_end VARCHAR(64) NOT NULL,
  horizon INTEGER NOT NULL,
  source_selection_json JSON NOT NULL,
  metadata_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id),
  KEY idx_prediction_runs_latest (instrument_id, bar_interval, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

PREDICTED_BARS_DDL = """
CREATE TABLE IF NOT EXISTS predicted_bars (
  run_id VARCHAR(128) NOT NULL,
  forecast_timestamp VARCHAR(64) NOT NULL,
  step INTEGER NOT NULL,
  open DOUBLE NOT NULL,
  high DOUBLE NOT NULL,
  low DOUBLE NOT NULL,
  close DOUBLE NOT NULL,
  volume DOUBLE NULL,
  amount DOUBLE NULL,
  confidence DOUBLE NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id, forecast_timestamp),
  KEY idx_predicted_bars_step (run_id, step)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

TECHNICAL_FEATURES_DDL = """
CREATE TABLE IF NOT EXISTS technical_features (
  instrument_id VARCHAR(128) NOT NULL,
  bar_timestamp VARCHAR(64) NOT NULL,
  bar_interval VARCHAR(16) NOT NULL,
  feature_name VARCHAR(128) NOT NULL,
  feature_value DOUBLE NULL,
  window_name VARCHAR(32) NULL,
  params_json JSON NULL,
  input_range_start VARCHAR(64) NOT NULL,
  input_range_end VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (instrument_id, bar_interval, bar_timestamp, feature_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

TECHNICAL_SIGNALS_DDL = """
CREATE TABLE IF NOT EXISTS technical_signals (
  signal_id VARCHAR(128) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  bar_timestamp VARCHAR(64) NOT NULL,
  bar_interval VARCHAR(16) NOT NULL,
  signal_type VARCHAR(64) NOT NULL,
  direction VARCHAR(32) NOT NULL,
  strength DOUBLE NOT NULL,
  confidence DOUBLE NULL,
  severity VARCHAR(32) NOT NULL,
  summary TEXT NOT NULL,
  evidence_json JSON NOT NULL,
  input_range_start VARCHAR(64) NOT NULL,
  input_range_end VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (signal_id),
  KEY idx_technical_signals_recent (instrument_id, bar_interval, bar_timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLMarketDataStorage:
    """Canonical stock market data storage backed by MySQL."""

    def __init__(
        self,
        config: MySQLConfig | None = None,
        connection_factory: Callable[[MySQLConfig], object] | None = None,
        ensure_tables: bool = True,
    ):
        self.config = config or MySQLConfig.from_env()
        self.connection_factory = connection_factory or _connect
        if ensure_tables:
            self.ensure_tables()

    def ensure_tables(self) -> None:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                for statement in [
                    INSTRUMENTS_DDL,
                    INSTRUMENT_ALIASES_DDL,
                    BARS_DDL,
                    FEED_RUNS_DDL,
                    DATA_QUALITY_ISSUES_DDL,
                    PREDICTION_RUNS_DDL,
                    PREDICTED_BARS_DDL,
                    TECHNICAL_FEATURES_DDL,
                    TECHNICAL_SIGNALS_DDL,
                ]:
                    cursor.execute(statement)
            connection.commit()
        finally:
            connection.close()

    def upsert_instrument(self, instrument: Instrument) -> None:
        record = instrument.to_record()
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO instruments (
                        instrument_id, symbol, market, exchange, asset_type, currency,
                        name, timezone, active, metadata_json
                    ) VALUES (
                        %(instrument_id)s, %(symbol)s, %(market)s, %(exchange)s, %(asset_type)s, %(currency)s,
                        %(name)s, %(timezone)s, %(active)s, %(metadata_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        symbol = VALUES(symbol),
                        market = VALUES(market),
                        exchange = VALUES(exchange),
                        asset_type = VALUES(asset_type),
                        currency = VALUES(currency),
                        name = VALUES(name),
                        timezone = VALUES(timezone),
                        active = VALUES(active),
                        metadata_json = VALUES(metadata_json)""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()

    def upsert_instruments(self, instruments: list[Instrument]) -> int:
        if not instruments:
            return 0
        records = [instrument.to_record() for instrument in instruments]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO instruments (
                        instrument_id, symbol, market, exchange, asset_type, currency,
                        name, timezone, active, metadata_json
                    ) VALUES (
                        %(instrument_id)s, %(symbol)s, %(market)s, %(exchange)s, %(asset_type)s, %(currency)s,
                        %(name)s, %(timezone)s, %(active)s, %(metadata_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        symbol = VALUES(symbol),
                        market = VALUES(market),
                        exchange = VALUES(exchange),
                        asset_type = VALUES(asset_type),
                        currency = VALUES(currency),
                        name = VALUES(name),
                        timezone = VALUES(timezone),
                        active = VALUES(active),
                        metadata_json = VALUES(metadata_json)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def upsert_instrument_alias(self, alias: InstrumentAlias) -> None:
        record = alias.to_record()
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO instrument_aliases (
                        instrument_id, source, source_symbol, priority
                    ) VALUES (
                        %(instrument_id)s, %(source)s, %(source_symbol)s, %(priority)s
                    )
                    ON DUPLICATE KEY UPDATE
                        instrument_id = VALUES(instrument_id),
                        priority = VALUES(priority)""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()

    def upsert_instrument_aliases(self, aliases: list[InstrumentAlias]) -> int:
        if not aliases:
            return 0
        records = [alias.to_record() for alias in aliases]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO instrument_aliases (
                        instrument_id, source, source_symbol, priority
                    ) VALUES (
                        %(instrument_id)s, %(source)s, %(source_symbol)s, %(priority)s
                    )
                    ON DUPLICATE KEY UPDATE
                        instrument_id = VALUES(instrument_id),
                        priority = VALUES(priority)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def resolve_alias(self, source: str, source_symbol: str) -> str | None:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT instrument_id FROM instrument_aliases
                       WHERE source = %s AND source_symbol = %s
                       ORDER BY priority ASC LIMIT 1""",
                    [source, source_symbol],
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return row["instrument_id"] if isinstance(row, dict) else row[0]

    def upsert_bars(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        records = _bar_records(df)
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO bars (
                        instrument_id, bar_timestamp, local_date, bar_interval, source, adjustment,
                        open, high, low, close, volume, amount, currency, is_complete,
                        provider_payload_hash
                    ) VALUES (
                        %(instrument_id)s, %(bar_timestamp)s, %(local_date)s, %(bar_interval)s, %(source)s, %(adjustment)s,
                        %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(amount)s, %(currency)s, %(is_complete)s,
                        %(provider_payload_hash)s
                    )
                    ON DUPLICATE KEY UPDATE
                        local_date = VALUES(local_date),
                        open = VALUES(open),
                        high = VALUES(high),
                        low = VALUES(low),
                        close = VALUES(close),
                        volume = VALUES(volume),
                        amount = VALUES(amount),
                        currency = VALUES(currency),
                        is_complete = VALUES(is_complete),
                        provider_payload_hash = VALUES(provider_payload_hash)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def load_bars(self, instrument_id: str, interval: str, start: str, end: str) -> pd.DataFrame:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT instrument_id, bar_timestamp AS `timestamp`, local_date,
                              bar_interval AS `interval`, source, adjustment,
                              open, high, low, close, volume, amount, currency,
                              is_complete, provider_payload_hash
                       FROM bars
                       WHERE instrument_id = %s
                         AND bar_interval = %s
                         AND bar_timestamp >= %s
                         AND bar_timestamp <= %s
                       ORDER BY bar_timestamp ASC""",
                    [instrument_id, interval, start, end],
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return pd.DataFrame(_rows_as_dicts(rows))

    def upsert_feed_run_records(self, records: list[dict]) -> int:
        if not records:
            return 0
        cleaned = _clean_records(records)
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO feed_runs (
                        run_id, source, purpose, started_at, ended_at, status,
                        requested_symbols_json, requested_interval, requested_start, requested_end,
                        rows_fetched, rows_inserted, rows_updated, error_message, metadata_json
                    ) VALUES (
                        %(run_id)s, %(source)s, %(purpose)s, %(started_at)s, %(ended_at)s, %(status)s,
                        %(requested_symbols_json)s, %(requested_interval)s, %(requested_start)s, %(requested_end)s,
                        %(rows_fetched)s, %(rows_inserted)s, %(rows_updated)s, %(error_message)s, %(metadata_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        source = VALUES(source),
                        purpose = VALUES(purpose),
                        started_at = VALUES(started_at),
                        ended_at = VALUES(ended_at),
                        status = VALUES(status),
                        requested_symbols_json = VALUES(requested_symbols_json),
                        requested_interval = VALUES(requested_interval),
                        requested_start = VALUES(requested_start),
                        requested_end = VALUES(requested_end),
                        rows_fetched = VALUES(rows_fetched),
                        rows_inserted = VALUES(rows_inserted),
                        rows_updated = VALUES(rows_updated),
                        error_message = VALUES(error_message),
                        metadata_json = VALUES(metadata_json)""",
                    cleaned,
                )
            connection.commit()
        finally:
            connection.close()
        return len(cleaned)

    def upsert_data_quality_issue_records(self, records: list[dict]) -> int:
        if not records:
            return 0
        normalized = []
        for record in records:
            row = dict(record)
            row["bar_interval"] = row.pop("interval", row.get("bar_interval"))
            row["bar_timestamp"] = row.pop("timestamp", row.get("bar_timestamp"))
            normalized.append(row)
        cleaned = _clean_records(normalized)
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO data_quality_issues (
                        issue_id, run_id, instrument_id, bar_interval, bar_timestamp,
                        severity, issue_type, details_json, created_at
                    ) VALUES (
                        %(issue_id)s, %(run_id)s, %(instrument_id)s, %(bar_interval)s, %(bar_timestamp)s,
                        %(severity)s, %(issue_type)s, %(details_json)s, %(created_at)s
                    )
                    ON DUPLICATE KEY UPDATE
                        run_id = VALUES(run_id),
                        instrument_id = VALUES(instrument_id),
                        bar_interval = VALUES(bar_interval),
                        bar_timestamp = VALUES(bar_timestamp),
                        severity = VALUES(severity),
                        issue_type = VALUES(issue_type),
                        details_json = VALUES(details_json)""",
                    cleaned,
                )
            connection.commit()
        finally:
            connection.close()
        return len(cleaned)

    def load_kronos_frame(
        self,
        instrument_id: str,
        interval: str,
        lookback: int = 512,
        adjustment: str = "split_adjusted",
    ) -> pd.DataFrame:
        columns = ["open", "high", "low", "close", "volume", "amount"]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT bar_timestamp AS `timestamp`, open, high, low, close, volume, amount
                       FROM bars
                       WHERE instrument_id = %s
                         AND bar_interval = %s
                         AND adjustment = %s
                         AND is_complete = 1
                       ORDER BY bar_timestamp DESC
                       LIMIT %s""",
                    [instrument_id, interval, adjustment, lookback],
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        df = pd.DataFrame(_rows_as_dicts(rows))
        if df.empty:
            return pd.DataFrame(columns=columns)
        df = df.sort_values("timestamp")
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        for column in columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        return df.set_index("timestamp")[columns]

    def save_prediction_run(self, run: PredictionRun, predicted_bars: pd.DataFrame) -> str:
        run_record = run.to_record()
        run_record["bar_interval"] = run_record.pop("interval")
        predicted_df = predicted_bars.copy()
        for column in ["volume", "amount", "confidence"]:
            if column not in predicted_df.columns:
                predicted_df[column] = None
        predicted_df["run_id"] = run.run_id
        records = _clean_records(predicted_df.to_dict("records"))
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO prediction_runs (
                        run_id, model_name, model_variant, instrument_id, bar_interval,
                        lookback_start, lookback_end, horizon, source_selection_json, metadata_json
                    ) VALUES (
                        %(run_id)s, %(model_name)s, %(model_variant)s, %(instrument_id)s, %(bar_interval)s,
                        %(lookback_start)s, %(lookback_end)s, %(horizon)s, %(source_selection_json)s, %(metadata_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        model_name = VALUES(model_name),
                        model_variant = VALUES(model_variant),
                        instrument_id = VALUES(instrument_id),
                        bar_interval = VALUES(bar_interval),
                        lookback_start = VALUES(lookback_start),
                        lookback_end = VALUES(lookback_end),
                        horizon = VALUES(horizon),
                        source_selection_json = VALUES(source_selection_json),
                        metadata_json = VALUES(metadata_json)""",
                    run_record,
                )
                cursor.executemany(
                    """INSERT INTO predicted_bars (
                        run_id, forecast_timestamp, step, open, high, low, close,
                        volume, amount, confidence
                    ) VALUES (
                        %(run_id)s, %(forecast_timestamp)s, %(step)s, %(open)s, %(high)s, %(low)s, %(close)s,
                        %(volume)s, %(amount)s, %(confidence)s
                    )
                    ON DUPLICATE KEY UPDATE
                        step = VALUES(step),
                        open = VALUES(open),
                        high = VALUES(high),
                        low = VALUES(low),
                        close = VALUES(close),
                        volume = VALUES(volume),
                        amount = VALUES(amount),
                        confidence = VALUES(confidence)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return run.run_id

    def load_latest_prediction_summary(self, instrument_id: str, interval: str) -> dict | None:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT run_id, model_name, model_variant, horizon, created_at
                       FROM prediction_runs
                       WHERE instrument_id = %s AND bar_interval = %s
                       ORDER BY created_at DESC LIMIT 1""",
                    [instrument_id, interval],
                )
                run = cursor.fetchone()
                if run is None:
                    return None
                run_values = run if isinstance(run, dict) else {
                    "run_id": run[0],
                    "model_name": run[1],
                    "model_variant": run[2],
                    "horizon": run[3],
                    "created_at": run[4],
                }
                cursor.execute(
                    """SELECT close FROM predicted_bars
                       WHERE run_id = %s
                       ORDER BY step ASC""",
                    [run_values["run_id"]],
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        closes = [row["close"] if isinstance(row, dict) else row[0] for row in rows]
        return {
            "run_id": run_values["run_id"],
            "model_name": run_values["model_name"],
            "model_variant": run_values["model_variant"],
            "horizon": run_values["horizon"],
            "forecast_close_min": min(closes) if closes else None,
            "forecast_close_max": max(closes) if closes else None,
            "created_at": str(run_values["created_at"]),
        }

    def save_technical_signals(self, signals: list[TechnicalSignal]) -> int:
        if not signals:
            return 0
        records = []
        for signal in signals:
            record = signal.to_record()
            record["bar_timestamp"] = record.pop("timestamp")
            record["bar_interval"] = record.pop("interval")
            records.append(record)
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO technical_signals (
                        signal_id, instrument_id, bar_timestamp, bar_interval, signal_type,
                        direction, strength, confidence, severity, summary, evidence_json,
                        input_range_start, input_range_end, created_at
                    ) VALUES (
                        %(signal_id)s, %(instrument_id)s, %(bar_timestamp)s, %(bar_interval)s, %(signal_type)s,
                        %(direction)s, %(strength)s, %(confidence)s, %(severity)s, %(summary)s, %(evidence_json)s,
                        %(input_range_start)s, %(input_range_end)s, %(created_at)s
                    )
                    ON DUPLICATE KEY UPDATE
                        bar_timestamp = VALUES(bar_timestamp),
                        bar_interval = VALUES(bar_interval),
                        signal_type = VALUES(signal_type),
                        direction = VALUES(direction),
                        strength = VALUES(strength),
                        confidence = VALUES(confidence),
                        severity = VALUES(severity),
                        summary = VALUES(summary),
                        evidence_json = VALUES(evidence_json),
                        input_range_start = VALUES(input_range_start),
                        input_range_end = VALUES(input_range_end)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def load_recent_technical_signals(self, instrument_id: str, interval: str, limit: int = 10) -> list[dict]:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT signal_id, instrument_id, bar_timestamp AS `timestamp`,
                              bar_interval AS `interval`, signal_type, direction, strength,
                              confidence, severity, summary, evidence_json,
                              input_range_start, input_range_end, created_at
                       FROM technical_signals
                       WHERE instrument_id = %s AND bar_interval = %s
                       ORDER BY bar_timestamp DESC LIMIT %s""",
                    [instrument_id, interval, limit],
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return _rows_as_dicts(rows)


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)


def _bar_records(df: pd.DataFrame) -> list[dict]:
    records_df = df.copy()
    defaults = {
        "volume": None,
        "amount": None,
        "currency": None,
        "is_complete": 1,
        "provider_payload_hash": None,
    }
    for column, value in defaults.items():
        if column not in records_df.columns:
            records_df[column] = value
    records_df["bar_timestamp"] = records_df["timestamp"]
    records_df["bar_interval"] = records_df["interval"]
    records_df["is_complete"] = records_df["is_complete"].map(lambda value: 1 if bool(value) else 0)
    columns = [
        "instrument_id",
        "bar_timestamp",
        "local_date",
        "bar_interval",
        "source",
        "adjustment",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "currency",
        "is_complete",
        "provider_payload_hash",
    ]
    return _clean_records(records_df[columns].to_dict("records"))


def _clean_records(records: list[dict]) -> list[dict]:
    cleaned = []
    for record in records:
        cleaned.append({key: _clean_value(value) for key, value in record.items()})
    return cleaned


def _clean_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if pd.isna(value):
        return None
    return value


def _rows_as_dicts(rows) -> list[dict]:
    if rows is None:
        return []
    result = []
    for row in rows:
        if isinstance(row, dict):
            result.append(row)
        else:
            result.append(dict(row))
    return result
