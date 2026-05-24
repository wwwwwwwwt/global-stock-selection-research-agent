"""MySQL-backed universe storage."""
from __future__ import annotations

from collections.abc import Callable

from openstockagent.database.mysql import MySQLConfig
from openstockagent.universe.models import Universe, UniverseMember


UNIVERSES_DDL = """
CREATE TABLE IF NOT EXISTS universes (
  universe_id VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  market VARCHAR(32) NOT NULL,
  asset_type VARCHAR(32) NOT NULL,
  description TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (universe_id),
  KEY idx_universes_market_asset (market, asset_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

UNIVERSE_MEMBERS_DDL = """
CREATE TABLE IF NOT EXISTS universe_members (
  universe_id VARCHAR(64) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NULL,
  reason VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (universe_id, instrument_id, start_date),
  KEY idx_universe_members_instrument (instrument_id),
  KEY idx_universe_members_active_window (universe_id, start_date, end_date),
  CONSTRAINT fk_universe_members_universe
    FOREIGN KEY (universe_id)
    REFERENCES universes (universe_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLUniverseStorage:
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
                cursor.execute(UNIVERSES_DDL)
                cursor.execute(UNIVERSE_MEMBERS_DDL)
            connection.commit()
        finally:
            connection.close()

    def upsert_universe(self, universe: Universe) -> None:
        record = universe.to_record()
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO universes (
                        universe_id, name, market, asset_type, description
                    ) VALUES (
                        %(universe_id)s, %(name)s, %(market)s, %(asset_type)s, %(description)s
                    )
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        market = VALUES(market),
                        asset_type = VALUES(asset_type),
                        description = VALUES(description)""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()

    def upsert_universe_members(self, members: list[UniverseMember]) -> int:
        if not members:
            return 0
        records = [member.to_record() for member in members]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO universe_members (
                        universe_id, instrument_id, start_date, end_date, reason
                    ) VALUES (
                        %(universe_id)s, %(instrument_id)s, %(start_date)s, %(end_date)s, %(reason)s
                    )
                    ON DUPLICATE KEY UPDATE
                        end_date = VALUES(end_date),
                        reason = VALUES(reason)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def load_universe_members(self, universe_id: str, as_of: str | None = None) -> list[UniverseMember]:
        sql = """SELECT universe_id, instrument_id, start_date, end_date, reason
                 FROM universe_members
                 WHERE universe_id = %s"""
        params: list[str] = [universe_id]
        if as_of is not None:
            sql += " AND start_date <= %s AND (end_date IS NULL OR end_date >= %s)"
            params.extend([as_of, as_of])
        sql += " ORDER BY instrument_id ASC, start_date ASC"

        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_member_from_row(row) for row in rows]


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)


def _member_from_row(row) -> UniverseMember:
    if isinstance(row, dict):
        values = row
    else:
        values = {
            "universe_id": row[0],
            "instrument_id": row[1],
            "start_date": row[2],
            "end_date": row[3],
            "reason": row[4],
        }
    return UniverseMember(
        universe_id=values["universe_id"],
        instrument_id=values["instrument_id"],
        start_date=str(values["start_date"]),
        end_date=str(values["end_date"]) if values["end_date"] is not None else None,
        reason=values["reason"],
    )
