"""MySQL-backed factor storage."""
from __future__ import annotations

from collections.abc import Callable

from openstockagent.database.mysql import MySQLConfig
from openstockagent.factors.models import FactorDefinition, FactorValue


FACTOR_DEFINITIONS_DDL = """
CREATE TABLE IF NOT EXISTS factor_definitions (
  factor_name VARCHAR(128) NOT NULL,
  category VARCHAR(64) NOT NULL,
  direction VARCHAR(32) NOT NULL,
  description TEXT NOT NULL,
  version VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (factor_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

FACTOR_VALUES_DDL = """
CREATE TABLE IF NOT EXISTS factor_values (
  instrument_id VARCHAR(128) NOT NULL,
  trade_date DATE NOT NULL,
  bar_interval VARCHAR(16) NOT NULL,
  factor_name VARCHAR(128) NOT NULL,
  factor_value DOUBLE NULL,
  percentile DOUBLE NULL,
  zscore DOUBLE NULL,
  version VARCHAR(32) NOT NULL,
  evidence_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (instrument_id, trade_date, bar_interval, factor_name, version),
  KEY idx_factor_values_lookup (trade_date, bar_interval, factor_name),
  KEY idx_factor_values_instrument (instrument_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLFactorStorage:
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
                cursor.execute(FACTOR_DEFINITIONS_DDL)
                cursor.execute(FACTOR_VALUES_DDL)
            connection.commit()
        finally:
            connection.close()

    def upsert_factor_definitions(self, definitions: list[FactorDefinition]) -> int:
        if not definitions:
            return 0
        records = [definition.to_record() for definition in definitions]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO factor_definitions (
                        factor_name, category, direction, description, version
                    ) VALUES (
                        %(factor_name)s, %(category)s, %(direction)s, %(description)s, %(version)s
                    )
                    ON DUPLICATE KEY UPDATE
                        category = VALUES(category),
                        direction = VALUES(direction),
                        description = VALUES(description),
                        version = VALUES(version)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def upsert_factor_values(self, values: list[FactorValue]) -> int:
        if not values:
            return 0
        records = [value.to_record() for value in values]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO factor_values (
                        instrument_id, trade_date, bar_interval, factor_name, factor_value,
                        percentile, zscore, version, evidence_json
                    ) VALUES (
                        %(instrument_id)s, %(trade_date)s, %(interval)s, %(factor_name)s, %(factor_value)s,
                        %(percentile)s, %(zscore)s, %(version)s, %(evidence_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        factor_value = VALUES(factor_value),
                        percentile = VALUES(percentile),
                        zscore = VALUES(zscore),
                        evidence_json = VALUES(evidence_json)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def load_factor_values(self, trade_date: str, interval: str, factor_name: str | None = None) -> list[FactorValue]:
        sql = """SELECT instrument_id, trade_date, bar_interval AS `interval`, factor_name, factor_value,
                        percentile, zscore, version, evidence_json
                 FROM factor_values
                 WHERE trade_date = %s AND bar_interval = %s"""
        params: list[str] = [trade_date, interval]
        if factor_name is not None:
            sql += " AND factor_name = %s"
            params.append(factor_name)
        sql += " ORDER BY factor_name ASC, instrument_id ASC"

        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_factor_value_from_row(row) for row in rows]


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)


def _factor_value_from_row(row) -> FactorValue:
    if isinstance(row, dict):
        values = row
    else:
        values = {
            "instrument_id": row[0],
            "trade_date": row[1],
            "interval": row[2],
            "factor_name": row[3],
            "factor_value": row[4],
            "percentile": row[5],
            "zscore": row[6],
            "version": row[7],
            "evidence_json": row[8],
        }
    return FactorValue(
        instrument_id=values["instrument_id"],
        trade_date=str(values["trade_date"]),
        interval=values["interval"],
        factor_name=values["factor_name"],
        factor_value=None if values["factor_value"] is None else float(values["factor_value"]),
        percentile=None if values["percentile"] is None else float(values["percentile"]),
        zscore=None if values["zscore"] is None else float(values["zscore"]),
        version=values["version"],
        evidence_json=values["evidence_json"],
    )
