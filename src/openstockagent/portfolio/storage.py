"""MySQL-backed portfolio storage."""
from __future__ import annotations

from collections.abc import Callable

from openstockagent.database.mysql import MySQLConfig
from openstockagent.portfolio.models import (
    PortfolioAccount,
    PortfolioDecision,
    PortfolioPolicy,
    PortfolioPosition,
    TargetAllocation,
)


PORTFOLIO_ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS portfolio_accounts (
  account_id VARCHAR(128) NOT NULL,
  base_currency VARCHAR(16) NOT NULL,
  capital DOUBLE NOT NULL,
  risk_profile VARCHAR(32) NOT NULL,
  metadata_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

PORTFOLIO_POLICIES_DDL = """
CREATE TABLE IF NOT EXISTS portfolio_policies (
  policy_id VARCHAR(128) NOT NULL,
  max_gross_exposure DOUBLE NOT NULL,
  max_single_position_pct DOUBLE NOT NULL,
  max_positions INTEGER NOT NULL,
  cash_floor_pct DOUBLE NOT NULL,
  max_new_positions_per_day INTEGER NOT NULL,
  min_recommendation_confidence DOUBLE NOT NULL,
  min_expected_return DOUBLE NOT NULL,
  market_regime_exposure_json JSON NOT NULL,
  description TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (policy_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

PORTFOLIO_POSITIONS_DDL = """
CREATE TABLE IF NOT EXISTS portfolio_positions (
  account_id VARCHAR(128) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  quantity DOUBLE NOT NULL,
  cost_basis DOUBLE NOT NULL,
  market_value DOUBLE NOT NULL,
  unrealized_return DOUBLE NULL,
  opened_at VARCHAR(64) NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (account_id, instrument_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

PORTFOLIO_DECISIONS_DDL = """
CREATE TABLE IF NOT EXISTS portfolio_decisions (
  decision_id VARCHAR(128) NOT NULL,
  recommendation_run_id VARCHAR(128) NOT NULL,
  account_id VARCHAR(128) NOT NULL,
  decision_date DATE NOT NULL,
  policy_id VARCHAR(128) NOT NULL,
  market_regime VARCHAR(64) NOT NULL,
  target_gross_exposure DOUBLE NOT NULL,
  cash_pct DOUBLE NOT NULL,
  action VARCHAR(32) NOT NULL,
  reason_json JSON NOT NULL,
  risk_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (decision_id),
  KEY idx_portfolio_decisions_account (account_id, decision_date),
  KEY idx_portfolio_decisions_recommendation (recommendation_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

TARGET_ALLOCATIONS_DDL = """
CREATE TABLE IF NOT EXISTS target_allocations (
  decision_id VARCHAR(128) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  action VARCHAR(32) NOT NULL,
  target_weight DOUBLE NOT NULL,
  max_position_value DOUBLE NOT NULL,
  source_recommendation_id VARCHAR(128) NULL,
  source_entry_plan_id VARCHAR(128) NULL,
  reason_json JSON NOT NULL,
  risk_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (decision_id, instrument_id),
  KEY idx_target_allocations_action (decision_id, action),
  KEY idx_target_allocations_entry_plan (source_entry_plan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLPortfolioStorage:
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
                cursor.execute(PORTFOLIO_ACCOUNTS_DDL)
                cursor.execute(PORTFOLIO_POLICIES_DDL)
                cursor.execute(PORTFOLIO_POSITIONS_DDL)
                cursor.execute(PORTFOLIO_DECISIONS_DDL)
                cursor.execute(TARGET_ALLOCATIONS_DDL)
                _ensure_target_allocations_entry_plan_column(cursor)
            connection.commit()
        finally:
            connection.close()

    def upsert_account(self, account: PortfolioAccount) -> None:
        _execute_one(
            self,
            """INSERT INTO portfolio_accounts (
                account_id, base_currency, capital, risk_profile, metadata_json
            ) VALUES (
                %(account_id)s, %(base_currency)s, %(capital)s, %(risk_profile)s, %(metadata_json)s
            )
            ON DUPLICATE KEY UPDATE
                base_currency = VALUES(base_currency),
                capital = VALUES(capital),
                risk_profile = VALUES(risk_profile),
                metadata_json = VALUES(metadata_json)""",
            account.to_record(),
        )

    def upsert_policy(self, policy: PortfolioPolicy) -> None:
        _execute_one(
            self,
            """INSERT INTO portfolio_policies (
                policy_id, max_gross_exposure, max_single_position_pct, max_positions,
                cash_floor_pct, max_new_positions_per_day, min_recommendation_confidence,
                min_expected_return, market_regime_exposure_json, description
            ) VALUES (
                %(policy_id)s, %(max_gross_exposure)s, %(max_single_position_pct)s, %(max_positions)s,
                %(cash_floor_pct)s, %(max_new_positions_per_day)s, %(min_recommendation_confidence)s,
                %(min_expected_return)s, %(market_regime_exposure_json)s, %(description)s
            )
            ON DUPLICATE KEY UPDATE
                max_gross_exposure = VALUES(max_gross_exposure),
                max_single_position_pct = VALUES(max_single_position_pct),
                max_positions = VALUES(max_positions),
                cash_floor_pct = VALUES(cash_floor_pct),
                max_new_positions_per_day = VALUES(max_new_positions_per_day),
                min_recommendation_confidence = VALUES(min_recommendation_confidence),
                min_expected_return = VALUES(min_expected_return),
                market_regime_exposure_json = VALUES(market_regime_exposure_json),
                description = VALUES(description)""",
            policy.to_record(),
        )

    def upsert_positions(self, positions: list[PortfolioPosition]) -> int:
        if not positions:
            return 0
        records = [position.to_record() for position in positions]
        _execute_many(
            self,
            """INSERT INTO portfolio_positions (
                account_id, instrument_id, quantity, cost_basis, market_value, unrealized_return, opened_at
            ) VALUES (
                %(account_id)s, %(instrument_id)s, %(quantity)s, %(cost_basis)s, %(market_value)s,
                %(unrealized_return)s, %(opened_at)s
            )
            ON DUPLICATE KEY UPDATE
                quantity = VALUES(quantity),
                cost_basis = VALUES(cost_basis),
                market_value = VALUES(market_value),
                unrealized_return = VALUES(unrealized_return),
                opened_at = VALUES(opened_at)""",
            records,
        )
        return len(records)

    def upsert_decision(self, decision: PortfolioDecision) -> None:
        _execute_one(
            self,
            """INSERT INTO portfolio_decisions (
                decision_id, recommendation_run_id, account_id, decision_date, policy_id,
                market_regime, target_gross_exposure, cash_pct, action, reason_json, risk_json
            ) VALUES (
                %(decision_id)s, %(recommendation_run_id)s, %(account_id)s, %(decision_date)s, %(policy_id)s,
                %(market_regime)s, %(target_gross_exposure)s, %(cash_pct)s, %(action)s, %(reason_json)s, %(risk_json)s
            )
            ON DUPLICATE KEY UPDATE
                recommendation_run_id = VALUES(recommendation_run_id),
                account_id = VALUES(account_id),
                decision_date = VALUES(decision_date),
                policy_id = VALUES(policy_id),
                market_regime = VALUES(market_regime),
                target_gross_exposure = VALUES(target_gross_exposure),
                cash_pct = VALUES(cash_pct),
                action = VALUES(action),
                reason_json = VALUES(reason_json),
                risk_json = VALUES(risk_json)""",
            decision.to_record(),
        )

    def delete_target_allocations(self, decision_id: str) -> int:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute("DELETE FROM target_allocations WHERE decision_id = %s", [decision_id])
            connection.commit()
        finally:
            connection.close()
        return int(affected or 0)

    def upsert_target_allocations(self, allocations: list[TargetAllocation]) -> int:
        if not allocations:
            return 0
        records = [allocation.to_record() for allocation in allocations]
        _execute_many(
            self,
            """INSERT INTO target_allocations (
                decision_id, instrument_id, action, target_weight, max_position_value,
                source_recommendation_id, source_entry_plan_id, reason_json, risk_json
            ) VALUES (
                %(decision_id)s, %(instrument_id)s, %(action)s, %(target_weight)s, %(max_position_value)s,
                %(source_recommendation_id)s, %(source_entry_plan_id)s, %(reason_json)s, %(risk_json)s
            )
            ON DUPLICATE KEY UPDATE
                action = VALUES(action),
                target_weight = VALUES(target_weight),
                max_position_value = VALUES(max_position_value),
                source_recommendation_id = VALUES(source_recommendation_id),
                source_entry_plan_id = VALUES(source_entry_plan_id),
                reason_json = VALUES(reason_json),
                risk_json = VALUES(risk_json)""",
            records,
        )
        return len(records)


def _execute_one(storage: MySQLPortfolioStorage, sql: str, record: dict) -> None:
    connection = storage.connection_factory(storage.config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, record)
        connection.commit()
    finally:
        connection.close()


def _execute_many(storage: MySQLPortfolioStorage, sql: str, records: list[dict]) -> None:
    connection = storage.connection_factory(storage.config)
    try:
        with connection.cursor() as cursor:
            cursor.executemany(sql, records)
        connection.commit()
    finally:
        connection.close()


def _ensure_target_allocations_entry_plan_column(cursor) -> None:
    try:
        cursor.execute("ALTER TABLE target_allocations ADD COLUMN source_entry_plan_id VARCHAR(128) NULL")
        cursor.execute("ALTER TABLE target_allocations ADD KEY idx_target_allocations_entry_plan (source_entry_plan_id)")
    except Exception as exc:
        message = str(exc).lower()
        if "duplicate column" not in message and "duplicate key" not in message:
            raise


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)
