"""MySQL-backed research evaluation storage."""
from __future__ import annotations

from collections.abc import Callable

from openstockagent.database.mysql import MySQLConfig
from openstockagent.research.models import BacktestResult, BacktestRun, ResearchExperimentDay, ResearchExperimentRun


BACKTEST_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS backtest_runs (
  run_id VARCHAR(128) NOT NULL,
  source_type VARCHAR(32) NOT NULL,
  source_run_id VARCHAR(128) NOT NULL,
  universe_id VARCHAR(64) NULL,
  as_of DATE NOT NULL,
  horizon_days INTEGER NOT NULL,
  top_n INTEGER NOT NULL,
  benchmark_instrument_id VARCHAR(128) NULL,
  status VARCHAR(32) NOT NULL,
  summary_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id),
  KEY idx_backtest_runs_source (source_type, source_run_id),
  KEY idx_backtest_runs_lookup (universe_id, as_of, horizon_days)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

BACKTEST_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS backtest_results (
  run_id VARCHAR(128) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  rank_position INTEGER NOT NULL,
  source_score DOUBLE NOT NULL,
  entry_date DATE NOT NULL,
  exit_date DATE NOT NULL,
  entry_price DOUBLE NOT NULL,
  exit_price DOUBLE NOT NULL,
  forward_return DOUBLE NOT NULL,
  benchmark_return DOUBLE NULL,
  excess_return DOUBLE NULL,
  max_drawdown DOUBLE NULL,
  max_favorable_return DOUBLE NULL,
  hit TINYINT(1) NOT NULL,
  evidence_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id, instrument_id),
  KEY idx_backtest_results_rank (run_id, rank_position),
  KEY idx_backtest_results_return (run_id, forward_return)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

RESEARCH_EXPERIMENT_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS research_experiment_runs (
  experiment_id VARCHAR(128) NOT NULL,
  universe_id VARCHAR(64) NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  rebalance_frequency VARCHAR(32) NOT NULL,
  horizon_days INTEGER NOT NULL,
  top_n INTEGER NOT NULL,
  strategy_name VARCHAR(128) NOT NULL,
  strategy_version VARCHAR(32) NOT NULL,
  benchmark_instrument_id VARCHAR(128) NULL,
  status VARCHAR(32) NOT NULL,
  summary_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (experiment_id),
  KEY idx_research_experiment_lookup (universe_id, start_date, end_date),
  KEY idx_research_experiment_strategy (strategy_name, strategy_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

RESEARCH_EXPERIMENT_DAYS_DDL = """
CREATE TABLE IF NOT EXISTS research_experiment_days (
  experiment_id VARCHAR(128) NOT NULL,
  as_of DATE NOT NULL,
  screen_run_id VARCHAR(128) NOT NULL,
  backtest_run_id VARCHAR(128) NOT NULL,
  market_context_snapshot_id VARCHAR(128) NULL,
  candidate_count INTEGER NOT NULL,
  evaluated_count INTEGER NOT NULL,
  mean_return DOUBLE NULL,
  mean_excess_return DOUBLE NULL,
  hit_rate DOUBLE NULL,
  summary_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (experiment_id, as_of),
  KEY idx_research_experiment_days_screen (screen_run_id),
  KEY idx_research_experiment_days_backtest (backtest_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLResearchStorage:
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
                cursor.execute(BACKTEST_RUNS_DDL)
                cursor.execute(BACKTEST_RESULTS_DDL)
                cursor.execute(RESEARCH_EXPERIMENT_RUNS_DDL)
                cursor.execute(RESEARCH_EXPERIMENT_DAYS_DDL)
            connection.commit()
        finally:
            connection.close()

    def upsert_backtest_run(self, run: BacktestRun) -> None:
        _execute_one(
            self,
            """INSERT INTO backtest_runs (
                run_id, source_type, source_run_id, universe_id, as_of, horizon_days,
                top_n, benchmark_instrument_id, status, summary_json
            ) VALUES (
                %(run_id)s, %(source_type)s, %(source_run_id)s, %(universe_id)s, %(as_of)s, %(horizon_days)s,
                %(top_n)s, %(benchmark_instrument_id)s, %(status)s, %(summary_json)s
            )
            ON DUPLICATE KEY UPDATE
                source_type = VALUES(source_type),
                source_run_id = VALUES(source_run_id),
                universe_id = VALUES(universe_id),
                as_of = VALUES(as_of),
                horizon_days = VALUES(horizon_days),
                top_n = VALUES(top_n),
                benchmark_instrument_id = VALUES(benchmark_instrument_id),
                status = VALUES(status),
                summary_json = VALUES(summary_json)""",
            run.to_record(),
        )

    def delete_backtest_results(self, run_id: str) -> int:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute("DELETE FROM backtest_results WHERE run_id = %s", [run_id])
            connection.commit()
        finally:
            connection.close()
        return int(affected or 0)

    def upsert_backtest_results(self, results: list[BacktestResult]) -> int:
        if not results:
            return 0
        records = [result.to_record() for result in results]
        _execute_many(
            self,
            """INSERT INTO backtest_results (
                run_id, instrument_id, rank_position, source_score, entry_date, exit_date,
                entry_price, exit_price, forward_return, benchmark_return, excess_return,
                max_drawdown, max_favorable_return, hit, evidence_json
            ) VALUES (
                %(run_id)s, %(instrument_id)s, %(rank_position)s, %(source_score)s, %(entry_date)s, %(exit_date)s,
                %(entry_price)s, %(exit_price)s, %(forward_return)s, %(benchmark_return)s, %(excess_return)s,
                %(max_drawdown)s, %(max_favorable_return)s, %(hit)s, %(evidence_json)s
            )
            ON DUPLICATE KEY UPDATE
                rank_position = VALUES(rank_position),
                source_score = VALUES(source_score),
                entry_date = VALUES(entry_date),
                exit_date = VALUES(exit_date),
                entry_price = VALUES(entry_price),
                exit_price = VALUES(exit_price),
                forward_return = VALUES(forward_return),
                benchmark_return = VALUES(benchmark_return),
                excess_return = VALUES(excess_return),
                max_drawdown = VALUES(max_drawdown),
                max_favorable_return = VALUES(max_favorable_return),
                hit = VALUES(hit),
                evidence_json = VALUES(evidence_json)""",
            records,
        )
        return len(records)

    def load_backtest_results(self, run_id: str) -> list[BacktestResult]:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT run_id, instrument_id, rank_position, source_score, entry_date, exit_date,
                              entry_price, exit_price, forward_return, benchmark_return, excess_return,
                              max_drawdown, max_favorable_return, hit, evidence_json
                       FROM backtest_results
                       WHERE run_id = %s
                       ORDER BY rank_position ASC""",
                    [run_id],
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_result_from_row(row) for row in rows]

    def upsert_research_experiment_run(self, run: ResearchExperimentRun) -> None:
        _execute_one(
            self,
            """INSERT INTO research_experiment_runs (
                experiment_id, universe_id, start_date, end_date, rebalance_frequency,
                horizon_days, top_n, strategy_name, strategy_version, benchmark_instrument_id,
                status, summary_json
            ) VALUES (
                %(experiment_id)s, %(universe_id)s, %(start_date)s, %(end_date)s, %(rebalance_frequency)s,
                %(horizon_days)s, %(top_n)s, %(strategy_name)s, %(strategy_version)s, %(benchmark_instrument_id)s,
                %(status)s, %(summary_json)s
            )
            ON DUPLICATE KEY UPDATE
                universe_id = VALUES(universe_id),
                start_date = VALUES(start_date),
                end_date = VALUES(end_date),
                rebalance_frequency = VALUES(rebalance_frequency),
                horizon_days = VALUES(horizon_days),
                top_n = VALUES(top_n),
                strategy_name = VALUES(strategy_name),
                strategy_version = VALUES(strategy_version),
                benchmark_instrument_id = VALUES(benchmark_instrument_id),
                status = VALUES(status),
                summary_json = VALUES(summary_json)""",
            run.to_record(),
        )

    def delete_research_experiment_days(self, experiment_id: str) -> int:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute(
                    "DELETE FROM research_experiment_days WHERE experiment_id = %s",
                    [experiment_id],
                )
            connection.commit()
        finally:
            connection.close()
        return int(affected or 0)

    def upsert_research_experiment_days(self, days: list[ResearchExperimentDay]) -> int:
        if not days:
            return 0
        records = [day.to_record() for day in days]
        _execute_many(
            self,
            """INSERT INTO research_experiment_days (
                experiment_id, as_of, screen_run_id, backtest_run_id, market_context_snapshot_id,
                candidate_count, evaluated_count, mean_return, mean_excess_return, hit_rate, summary_json
            ) VALUES (
                %(experiment_id)s, %(as_of)s, %(screen_run_id)s, %(backtest_run_id)s, %(market_context_snapshot_id)s,
                %(candidate_count)s, %(evaluated_count)s, %(mean_return)s, %(mean_excess_return)s, %(hit_rate)s,
                %(summary_json)s
            )
            ON DUPLICATE KEY UPDATE
                screen_run_id = VALUES(screen_run_id),
                backtest_run_id = VALUES(backtest_run_id),
                market_context_snapshot_id = VALUES(market_context_snapshot_id),
                candidate_count = VALUES(candidate_count),
                evaluated_count = VALUES(evaluated_count),
                mean_return = VALUES(mean_return),
                mean_excess_return = VALUES(mean_excess_return),
                hit_rate = VALUES(hit_rate),
                summary_json = VALUES(summary_json)""",
            records,
        )
        return len(records)


def _execute_one(storage: MySQLResearchStorage, sql: str, record: dict) -> None:
    connection = storage.connection_factory(storage.config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, record)
        connection.commit()
    finally:
        connection.close()


def _execute_many(storage: MySQLResearchStorage, sql: str, records: list[dict]) -> None:
    connection = storage.connection_factory(storage.config)
    try:
        with connection.cursor() as cursor:
            cursor.executemany(sql, records)
        connection.commit()
    finally:
        connection.close()


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)


def _result_from_row(row) -> BacktestResult:
    values = _row_dict(
        row,
        [
            "run_id",
            "instrument_id",
            "rank_position",
            "source_score",
            "entry_date",
            "exit_date",
            "entry_price",
            "exit_price",
            "forward_return",
            "benchmark_return",
            "excess_return",
            "max_drawdown",
            "max_favorable_return",
            "hit",
            "evidence_json",
        ],
    )
    return BacktestResult(
        run_id=values["run_id"],
        instrument_id=values["instrument_id"],
        rank=int(values["rank_position"]),
        source_score=float(values["source_score"]),
        entry_date=str(values["entry_date"]),
        exit_date=str(values["exit_date"]),
        entry_price=float(values["entry_price"]),
        exit_price=float(values["exit_price"]),
        forward_return=float(values["forward_return"]),
        benchmark_return=float(values["benchmark_return"]) if values["benchmark_return"] is not None else None,
        excess_return=float(values["excess_return"]) if values["excess_return"] is not None else None,
        max_drawdown=float(values["max_drawdown"]) if values["max_drawdown"] is not None else None,
        max_favorable_return=float(values["max_favorable_return"]) if values["max_favorable_return"] is not None else None,
        hit=bool(values["hit"]),
        evidence_json=values["evidence_json"],
    )


def _row_dict(row, columns: list[str]) -> dict:
    if isinstance(row, dict):
        return row
    return dict(zip(columns, row, strict=True))
