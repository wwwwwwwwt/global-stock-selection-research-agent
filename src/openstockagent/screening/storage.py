"""MySQL-backed screening storage."""
from __future__ import annotations

from collections.abc import Callable

from openstockagent.database.mysql import MySQLConfig
from openstockagent.screening.models import ScreenResult, ScreenRun, ScreenStrategy


SCREEN_STRATEGIES_DDL = """
CREATE TABLE IF NOT EXISTS screen_strategies (
  strategy_name VARCHAR(128) NOT NULL,
  version VARCHAR(32) NOT NULL,
  config_json JSON NOT NULL,
  description TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (strategy_name, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

SCREEN_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS screen_runs (
  run_id VARCHAR(128) NOT NULL,
  universe_id VARCHAR(64) NOT NULL,
  trade_date DATE NOT NULL,
  bar_interval VARCHAR(16) NOT NULL,
  strategy_name VARCHAR(128) NOT NULL,
  version VARCHAR(32) NOT NULL,
  market_context_snapshot_id VARCHAR(128) NULL,
  status VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id),
  KEY idx_screen_runs_lookup (universe_id, trade_date, bar_interval),
  KEY idx_screen_runs_strategy (strategy_name, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

SCREEN_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS screen_results (
  run_id VARCHAR(128) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  rank_position INTEGER NOT NULL,
  selected TINYINT(1) NOT NULL,
  total_score DOUBLE NOT NULL,
  score_breakdown_json JSON NOT NULL,
  reason_json JSON NOT NULL,
  risk_json JSON NOT NULL,
  evidence_refs_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id, instrument_id),
  KEY idx_screen_results_rank (run_id, rank_position),
  KEY idx_screen_results_selected (run_id, selected, rank_position)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLScreeningStorage:
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
                cursor.execute(SCREEN_STRATEGIES_DDL)
                cursor.execute(SCREEN_RUNS_DDL)
                cursor.execute(SCREEN_RESULTS_DDL)
            connection.commit()
        finally:
            connection.close()

    def upsert_strategy(self, strategy: ScreenStrategy) -> None:
        record = strategy.to_record()
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO screen_strategies (
                        strategy_name, version, config_json, description
                    ) VALUES (
                        %(strategy_name)s, %(version)s, %(config_json)s, %(description)s
                    )
                    ON DUPLICATE KEY UPDATE
                        config_json = VALUES(config_json),
                        description = VALUES(description)""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()

    def upsert_screen_run(self, run: ScreenRun) -> None:
        record = run.to_record()
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO screen_runs (
                        run_id, universe_id, trade_date, bar_interval, strategy_name, version,
                        market_context_snapshot_id, status
                    ) VALUES (
                        %(run_id)s, %(universe_id)s, %(trade_date)s, %(bar_interval)s, %(strategy_name)s, %(version)s,
                        %(market_context_snapshot_id)s, %(status)s
                    )
                    ON DUPLICATE KEY UPDATE
                        universe_id = VALUES(universe_id),
                        trade_date = VALUES(trade_date),
                        bar_interval = VALUES(bar_interval),
                        strategy_name = VALUES(strategy_name),
                        version = VALUES(version),
                        market_context_snapshot_id = VALUES(market_context_snapshot_id),
                        status = VALUES(status)""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()

    def upsert_screen_results(self, results: list[ScreenResult]) -> int:
        if not results:
            return 0
        records = [result.to_record() for result in results]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO screen_results (
                        run_id, instrument_id, rank_position, selected, total_score, score_breakdown_json,
                        reason_json, risk_json, evidence_refs_json
                    ) VALUES (
                        %(run_id)s, %(instrument_id)s, %(rank_position)s, %(selected)s, %(total_score)s, %(score_breakdown_json)s,
                        %(reason_json)s, %(risk_json)s, %(evidence_refs_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        rank_position = VALUES(rank_position),
                        selected = VALUES(selected),
                        total_score = VALUES(total_score),
                        score_breakdown_json = VALUES(score_breakdown_json),
                        reason_json = VALUES(reason_json),
                        risk_json = VALUES(risk_json),
                        evidence_refs_json = VALUES(evidence_refs_json)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def delete_screen_results(self, run_id: str) -> int:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute("DELETE FROM screen_results WHERE run_id = %s", [run_id])
            connection.commit()
        finally:
            connection.close()
        return int(affected or 0)

    def load_screen_results(self, run_id: str, selected_only: bool = False) -> list[ScreenResult]:
        sql = """SELECT run_id, instrument_id, rank_position AS `rank`, selected, total_score,
                        score_breakdown_json, reason_json, risk_json, evidence_refs_json
                 FROM screen_results
                 WHERE run_id = %s"""
        params: list[object] = [run_id]
        if selected_only:
            sql += " AND selected = %s"
            params.append(1)
        sql += " ORDER BY rank_position ASC"

        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_result_from_row(row) for row in rows]


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)


def _result_from_row(row) -> ScreenResult:
    if isinstance(row, dict):
        values = row
    else:
        values = {
            "run_id": row[0],
            "instrument_id": row[1],
            "rank": row[2],
            "selected": row[3],
            "total_score": row[4],
            "score_breakdown_json": row[5],
            "reason_json": row[6],
            "risk_json": row[7],
            "evidence_refs_json": row[8],
        }
    return ScreenResult(
        run_id=values["run_id"],
        instrument_id=values["instrument_id"],
        rank=int(values["rank"]),
        selected=bool(values["selected"]),
        total_score=float(values["total_score"]),
        score_breakdown_json=values["score_breakdown_json"],
        reason_json=values["reason_json"],
        risk_json=values["risk_json"],
        evidence_refs_json=values["evidence_refs_json"],
    )
