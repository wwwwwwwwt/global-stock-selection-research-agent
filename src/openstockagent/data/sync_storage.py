"""MySQL storage for data synchronization plans and runs."""
from __future__ import annotations

from collections.abc import Callable
import json

from openstockagent.data.sync import DataSyncPlan, DataSyncRunResult
from openstockagent.database.mysql import MySQLConfig


DATA_SYNC_PLANS_DDL = """
CREATE TABLE IF NOT EXISTS data_sync_plans (
  plan_id VARCHAR(128) NOT NULL,
  universe_id VARCHAR(64) NOT NULL,
  market VARCHAR(32) NOT NULL,
  bar_interval VARCHAR(16) NOT NULL,
  provider VARCHAR(64) NOT NULL,
  adjustment VARCHAR(32) NOT NULL,
  mode VARCHAR(32) NOT NULL,
  lookback_years INTEGER NOT NULL,
  incremental_days INTEGER NOT NULL,
  config_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (plan_id),
  KEY idx_data_sync_plans_universe (universe_id, market, mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

DATA_SYNC_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS data_sync_runs (
  run_id VARCHAR(128) NOT NULL,
  plan_id VARCHAR(128) NOT NULL,
  universe_id VARCHAR(64) NOT NULL,
  market VARCHAR(32) NOT NULL,
  as_of DATE NOT NULL,
  mode VARCHAR(32) NOT NULL,
  bar_interval VARCHAR(16) NOT NULL,
  period VARCHAR(16) NOT NULL,
  members_seen INTEGER NOT NULL,
  instruments_fetched INTEGER NOT NULL,
  failed_instruments INTEGER NOT NULL,
  bars_written INTEGER NOT NULL,
  errors_json JSON NULL,
  started_at VARCHAR(64) NOT NULL,
  ended_at VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id),
  KEY idx_data_sync_runs_plan (plan_id, started_at),
  KEY idx_data_sync_runs_universe (universe_id, as_of, mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLDataSyncStorage:
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
                cursor.execute(DATA_SYNC_PLANS_DDL)
                cursor.execute(DATA_SYNC_RUNS_DDL)
            connection.commit()
        finally:
            connection.close()

    def upsert_plan(self, plan: DataSyncPlan) -> None:
        record = plan.to_record()
        record["bar_interval"] = record.pop("interval")
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO data_sync_plans (
                        plan_id, universe_id, market, bar_interval, provider, adjustment,
                        mode, lookback_years, incremental_days, config_json
                    ) VALUES (
                        %(plan_id)s, %(universe_id)s, %(market)s, %(bar_interval)s, %(provider)s, %(adjustment)s,
                        %(mode)s, %(lookback_years)s, %(incremental_days)s, %(config_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        universe_id = VALUES(universe_id),
                        market = VALUES(market),
                        bar_interval = VALUES(bar_interval),
                        provider = VALUES(provider),
                        adjustment = VALUES(adjustment),
                        mode = VALUES(mode),
                        lookback_years = VALUES(lookback_years),
                        incremental_days = VALUES(incremental_days),
                        config_json = VALUES(config_json)""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()

    def save_run(self, result: DataSyncRunResult) -> None:
        record = result.__dict__.copy()
        record["bar_interval"] = record.pop("interval")
        record["errors_json"] = json.dumps(record.pop("errors"), sort_keys=True)
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO data_sync_runs (
                        run_id, plan_id, universe_id, market, as_of, mode, bar_interval, period,
                        members_seen, instruments_fetched, failed_instruments, bars_written,
                        errors_json, started_at, ended_at, status
                    ) VALUES (
                        %(run_id)s, %(plan_id)s, %(universe_id)s, %(market)s, %(as_of)s, %(mode)s, %(bar_interval)s, %(period)s,
                        %(members_seen)s, %(instruments_fetched)s, %(failed_instruments)s, %(bars_written)s,
                        %(errors_json)s, %(started_at)s, %(ended_at)s, %(status)s
                    )""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)
