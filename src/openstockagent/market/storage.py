"""MySQL-backed market reality storage."""
from __future__ import annotations

from collections.abc import Callable

from openstockagent.database.mysql import MySQLConfig
from openstockagent.market.models import CorporateAction, InstrumentStatus, MarketContextSnapshot, TradingCalendarDay


TRADING_CALENDAR_DDL = """
CREATE TABLE IF NOT EXISTS trading_calendar (
  market VARCHAR(32) NOT NULL,
  calendar_date DATE NOT NULL,
  is_trading_day TINYINT(1) NOT NULL,
  session_type VARCHAR(32) NOT NULL,
  open_time VARCHAR(16) NULL,
  close_time VARCHAR(16) NULL,
  source VARCHAR(64) NOT NULL,
  notes_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (market, calendar_date),
  KEY idx_trading_calendar_next (market, is_trading_day, calendar_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

INSTRUMENT_STATUS_DDL = """
CREATE TABLE IF NOT EXISTS instrument_status (
  instrument_id VARCHAR(128) NOT NULL,
  status_date DATE NOT NULL,
  status VARCHAR(32) NOT NULL,
  is_tradable TINYINT(1) NOT NULL,
  is_st TINYINT(1) NOT NULL,
  is_suspended TINYINT(1) NOT NULL,
  limit_up DOUBLE NULL,
  limit_down DOUBLE NULL,
  reason_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (instrument_id, status_date),
  KEY idx_instrument_status_date (status_date, is_tradable, is_suspended, is_st)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

CORPORATE_ACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS corporate_actions (
  action_id VARCHAR(128) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  action_date DATE NOT NULL,
  ex_date DATE NULL,
  action_type VARCHAR(64) NOT NULL,
  adjustment_factor DOUBLE NULL,
  cash_amount DOUBLE NULL,
  split_ratio DOUBLE NULL,
  source VARCHAR(64) NOT NULL,
  payload_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (action_id),
  KEY idx_corporate_actions_instrument (instrument_id, action_date),
  KEY idx_corporate_actions_ex_date (ex_date, action_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

MARKET_CONTEXT_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS market_context_snapshots (
  snapshot_id VARCHAR(128) NOT NULL,
  as_of DATE NOT NULL,
  market VARCHAR(32) NOT NULL,
  universe_id VARCHAR(64) NULL,
  risk_regime VARCHAR(64) NOT NULL,
  regime_score DOUBLE NULL,
  coverage DOUBLE NULL,
  breadth_score DOUBLE NULL,
  trend_score DOUBLE NULL,
  volatility_score DOUBLE NULL,
  liquidity_score DOUBLE NULL,
  summary_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (snapshot_id),
  KEY idx_market_context_lookup (market, as_of, universe_id),
  KEY idx_market_context_regime (as_of, risk_regime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLMarketRealityStorage:
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
                cursor.execute(TRADING_CALENDAR_DDL)
                cursor.execute(INSTRUMENT_STATUS_DDL)
                cursor.execute(CORPORATE_ACTIONS_DDL)
                cursor.execute(MARKET_CONTEXT_SNAPSHOTS_DDL)
            connection.commit()
        finally:
            connection.close()

    def upsert_trading_calendar_days(self, days: list[TradingCalendarDay]) -> int:
        if not days:
            return 0
        records = [day.to_record() for day in days]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO trading_calendar (
                        market, calendar_date, is_trading_day, session_type, open_time,
                        close_time, source, notes_json
                    ) VALUES (
                        %(market)s, %(calendar_date)s, %(is_trading_day)s, %(session_type)s, %(open_time)s,
                        %(close_time)s, %(source)s, %(notes_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        is_trading_day = VALUES(is_trading_day),
                        session_type = VALUES(session_type),
                        open_time = VALUES(open_time),
                        close_time = VALUES(close_time),
                        source = VALUES(source),
                        notes_json = VALUES(notes_json)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def upsert_instrument_statuses(self, statuses: list[InstrumentStatus]) -> int:
        if not statuses:
            return 0
        records = [status.to_record() for status in statuses]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO instrument_status (
                        instrument_id, status_date, status, is_tradable, is_st,
                        is_suspended, limit_up, limit_down, reason_json
                    ) VALUES (
                        %(instrument_id)s, %(status_date)s, %(status)s, %(is_tradable)s, %(is_st)s,
                        %(is_suspended)s, %(limit_up)s, %(limit_down)s, %(reason_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        is_tradable = VALUES(is_tradable),
                        is_st = VALUES(is_st),
                        is_suspended = VALUES(is_suspended),
                        limit_up = VALUES(limit_up),
                        limit_down = VALUES(limit_down),
                        reason_json = VALUES(reason_json)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def upsert_corporate_actions(self, actions: list[CorporateAction]) -> int:
        if not actions:
            return 0
        records = [action.to_record() for action in actions]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO corporate_actions (
                        action_id, instrument_id, action_date, ex_date, action_type,
                        adjustment_factor, cash_amount, split_ratio, source, payload_json
                    ) VALUES (
                        %(action_id)s, %(instrument_id)s, %(action_date)s, %(ex_date)s, %(action_type)s,
                        %(adjustment_factor)s, %(cash_amount)s, %(split_ratio)s, %(source)s, %(payload_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        instrument_id = VALUES(instrument_id),
                        action_date = VALUES(action_date),
                        ex_date = VALUES(ex_date),
                        action_type = VALUES(action_type),
                        adjustment_factor = VALUES(adjustment_factor),
                        cash_amount = VALUES(cash_amount),
                        split_ratio = VALUES(split_ratio),
                        source = VALUES(source),
                        payload_json = VALUES(payload_json)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def upsert_market_context_snapshot(self, snapshot: MarketContextSnapshot) -> None:
        record = snapshot.to_record()
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO market_context_snapshots (
                        snapshot_id, as_of, market, universe_id, risk_regime, regime_score,
                        coverage, breadth_score, trend_score, volatility_score, liquidity_score, summary_json
                    ) VALUES (
                        %(snapshot_id)s, %(as_of)s, %(market)s, %(universe_id)s, %(risk_regime)s, %(regime_score)s,
                        %(coverage)s, %(breadth_score)s, %(trend_score)s, %(volatility_score)s, %(liquidity_score)s,
                        %(summary_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        as_of = VALUES(as_of),
                        market = VALUES(market),
                        universe_id = VALUES(universe_id),
                        risk_regime = VALUES(risk_regime),
                        regime_score = VALUES(regime_score),
                        coverage = VALUES(coverage),
                        breadth_score = VALUES(breadth_score),
                        trend_score = VALUES(trend_score),
                        volatility_score = VALUES(volatility_score),
                        liquidity_score = VALUES(liquidity_score),
                        summary_json = VALUES(summary_json)""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()

    def load_market_context_snapshot(self, snapshot_id: str) -> MarketContextSnapshot | None:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT snapshot_id, as_of, market, universe_id, risk_regime, regime_score,
                              coverage, breadth_score, trend_score, volatility_score, liquidity_score,
                              summary_json
                       FROM market_context_snapshots
                       WHERE snapshot_id = %s""",
                    [snapshot_id],
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        return _snapshot_from_row(row) if row is not None else None

    def load_instrument_status(self, instrument_id: str, as_of: str) -> InstrumentStatus | None:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT instrument_id, status_date, status, is_tradable, is_st,
                              is_suspended, limit_up, limit_down, reason_json
                       FROM instrument_status
                       WHERE instrument_id = %s AND status_date <= %s
                       ORDER BY status_date DESC LIMIT 1""",
                    [instrument_id, as_of],
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        return _status_from_row(row) if row is not None else None

    def load_trading_calendar_day(self, market: str, calendar_date: str) -> TradingCalendarDay | None:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT market, calendar_date, is_trading_day, session_type,
                              open_time, close_time, source, notes_json
                       FROM trading_calendar
                       WHERE market = %s AND calendar_date = %s""",
                    [market.upper(), calendar_date],
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        return _calendar_day_from_row(row) if row is not None else None

    def next_trading_date(self, market: str, start_date: str, offset: int = 1) -> str | None:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT calendar_date
                       FROM trading_calendar
                       WHERE market = %s AND calendar_date > %s AND is_trading_day = 1
                       ORDER BY calendar_date ASC
                       LIMIT %s""",
                    [market.upper(), start_date, offset],
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        if len(rows) < offset:
            return None
        row = rows[-1]
        value = row["calendar_date"] if isinstance(row, dict) else row[0]
        return str(value)

    def previous_trading_date(self, market: str, as_of: str) -> str | None:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT calendar_date
                       FROM trading_calendar
                       WHERE market = %s AND calendar_date < %s AND is_trading_day = 1
                       ORDER BY calendar_date DESC
                       LIMIT 1""",
                    [market.upper(), as_of],
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        value = row["calendar_date"] if isinstance(row, dict) else row[0]
        return str(value)


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)


def _calendar_day_from_row(row) -> TradingCalendarDay:
    values = row if isinstance(row, dict) else {
        "market": row[0],
        "calendar_date": row[1],
        "is_trading_day": row[2],
        "session_type": row[3],
        "open_time": row[4],
        "close_time": row[5],
        "source": row[6],
        "notes_json": row[7],
    }
    return TradingCalendarDay(
        market=values["market"],
        calendar_date=str(values["calendar_date"]),
        is_trading_day=bool(values["is_trading_day"]),
        session_type=values["session_type"],
        open_time=values["open_time"],
        close_time=values["close_time"],
        source=values["source"],
        notes_json=values["notes_json"],
    )


def _status_from_row(row) -> InstrumentStatus:
    values = row if isinstance(row, dict) else {
        "instrument_id": row[0],
        "status_date": row[1],
        "status": row[2],
        "is_tradable": row[3],
        "is_st": row[4],
        "is_suspended": row[5],
        "limit_up": row[6],
        "limit_down": row[7],
        "reason_json": row[8],
    }
    return InstrumentStatus(
        instrument_id=values["instrument_id"],
        status_date=str(values["status_date"]),
        status=values["status"],
        is_tradable=bool(values["is_tradable"]),
        is_st=bool(values["is_st"]),
        is_suspended=bool(values["is_suspended"]),
        limit_up=float(values["limit_up"]) if values["limit_up"] is not None else None,
        limit_down=float(values["limit_down"]) if values["limit_down"] is not None else None,
        reason_json=values["reason_json"],
    )


def _snapshot_from_row(row) -> MarketContextSnapshot:
    values = row if isinstance(row, dict) else {
        "snapshot_id": row[0],
        "as_of": row[1],
        "market": row[2],
        "universe_id": row[3],
        "risk_regime": row[4],
        "regime_score": row[5],
        "coverage": row[6],
        "breadth_score": row[7],
        "trend_score": row[8],
        "volatility_score": row[9],
        "liquidity_score": row[10],
        "summary_json": row[11],
    }
    return MarketContextSnapshot(
        snapshot_id=values["snapshot_id"],
        as_of=str(values["as_of"]),
        market=values["market"],
        universe_id=values["universe_id"],
        risk_regime=values["risk_regime"],
        regime_score=None if values["regime_score"] is None else float(values["regime_score"]),
        coverage=None if values["coverage"] is None else float(values["coverage"]),
        breadth_score=None if values["breadth_score"] is None else float(values["breadth_score"]),
        trend_score=None if values["trend_score"] is None else float(values["trend_score"]),
        volatility_score=None if values["volatility_score"] is None else float(values["volatility_score"]),
        liquidity_score=None if values["liquidity_score"] is None else float(values["liquidity_score"]),
        summary_json=values["summary_json"],
    )
