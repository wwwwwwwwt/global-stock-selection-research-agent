"""MySQL-backed entry timing storage."""
from __future__ import annotations

from collections.abc import Callable

from openstockagent.database.mysql import MySQLConfig
from openstockagent.entry.models import EntryPlan, EntryPlanReview, EntryPlanRun


ENTRY_PLAN_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS entry_plan_runs (
  run_id VARCHAR(128) NOT NULL,
  recommendation_run_id VARCHAR(128) NOT NULL,
  as_of DATE NOT NULL,
  horizon VARCHAR(16) NOT NULL,
  market_regime VARCHAR(64) NOT NULL,
  strategy_name VARCHAR(128) NOT NULL,
  strategy_version VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL,
  summary_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id),
  KEY idx_entry_plan_runs_recommendation (recommendation_run_id),
  KEY idx_entry_plan_runs_lookup (as_of, horizon, market_regime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

ENTRY_PLANS_DDL = """
CREATE TABLE IF NOT EXISTS entry_plans (
  plan_id VARCHAR(128) NOT NULL,
  run_id VARCHAR(128) NOT NULL,
  recommendation_id VARCHAR(128) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  rank_position INTEGER NOT NULL,
  entry_mode VARCHAR(32) NOT NULL,
  entry_status VARCHAR(32) NOT NULL,
  reference_price DOUBLE NULL,
  trigger_price DOUBLE NULL,
  pullback_price DOUBLE NULL,
  stop_loss DOUBLE NULL,
  take_profit DOUBLE NULL,
  time_limit_date DATE NOT NULL,
  confidence DOUBLE NOT NULL,
  reason_json JSON NOT NULL,
  confirmation_json JSON NOT NULL,
  invalidation_json JSON NOT NULL,
  risk_json JSON NOT NULL,
  evidence_refs_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (plan_id),
  UNIQUE KEY uq_entry_plans_run_recommendation (run_id, recommendation_id),
  KEY idx_entry_plans_run_status (run_id, entry_status, rank_position),
  KEY idx_entry_plans_instrument (instrument_id, time_limit_date),
  KEY idx_entry_plans_review_due (time_limit_date, entry_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

ENTRY_PLAN_REVIEWS_DDL = """
CREATE TABLE IF NOT EXISTS entry_plan_reviews (
  review_id VARCHAR(128) NOT NULL,
  plan_id VARCHAR(128) NOT NULL,
  review_date DATE NOT NULL,
  triggered TINYINT(1) NOT NULL,
  trigger_date DATE NULL,
  entry_price DOUBLE NULL,
  review_price DOUBLE NULL,
  realized_return DOUBLE NULL,
  max_drawdown DOUBLE NULL,
  max_favorable_return DOUBLE NULL,
  avoided_chase_loss DOUBLE NULL,
  missed_opportunity DOUBLE NULL,
  entry_quality_score DOUBLE NULL,
  review_notes_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (review_id),
  KEY idx_entry_plan_reviews_plan (plan_id, review_date),
  KEY idx_entry_plan_reviews_quality (review_date, entry_quality_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLEntryStorage:
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
                cursor.execute(ENTRY_PLAN_RUNS_DDL)
                cursor.execute(ENTRY_PLANS_DDL)
                cursor.execute(ENTRY_PLAN_REVIEWS_DDL)
            connection.commit()
        finally:
            connection.close()

    def upsert_entry_plan_run(self, run: EntryPlanRun) -> None:
        record = run.to_record()
        _execute_one(
            self,
            """INSERT INTO entry_plan_runs (
                run_id, recommendation_run_id, as_of, horizon, market_regime,
                strategy_name, strategy_version, status, summary_json
            ) VALUES (
                %(run_id)s, %(recommendation_run_id)s, %(as_of)s, %(horizon)s, %(market_regime)s,
                %(strategy_name)s, %(strategy_version)s, %(status)s, %(summary_json)s
            )
            ON DUPLICATE KEY UPDATE
                recommendation_run_id = VALUES(recommendation_run_id),
                as_of = VALUES(as_of),
                horizon = VALUES(horizon),
                market_regime = VALUES(market_regime),
                strategy_name = VALUES(strategy_name),
                strategy_version = VALUES(strategy_version),
                status = VALUES(status),
                summary_json = VALUES(summary_json)""",
            record,
        )

    def delete_entry_plans(self, run_id: str) -> int:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute("DELETE FROM entry_plans WHERE run_id = %s", [run_id])
            connection.commit()
        finally:
            connection.close()
        return int(affected or 0)

    def upsert_entry_plans(self, plans: list[EntryPlan]) -> int:
        if not plans:
            return 0
        records = [plan.to_record() for plan in plans]
        _execute_many(
            self,
            """INSERT INTO entry_plans (
                plan_id, run_id, recommendation_id, instrument_id, rank_position,
                entry_mode, entry_status, reference_price, trigger_price, pullback_price,
                stop_loss, take_profit, time_limit_date, confidence, reason_json,
                confirmation_json, invalidation_json, risk_json, evidence_refs_json
            ) VALUES (
                %(plan_id)s, %(run_id)s, %(recommendation_id)s, %(instrument_id)s, %(rank_position)s,
                %(entry_mode)s, %(entry_status)s, %(reference_price)s, %(trigger_price)s, %(pullback_price)s,
                %(stop_loss)s, %(take_profit)s, %(time_limit_date)s, %(confidence)s, %(reason_json)s,
                %(confirmation_json)s, %(invalidation_json)s, %(risk_json)s, %(evidence_refs_json)s
            )
            ON DUPLICATE KEY UPDATE
                rank_position = VALUES(rank_position),
                entry_mode = VALUES(entry_mode),
                entry_status = VALUES(entry_status),
                reference_price = VALUES(reference_price),
                trigger_price = VALUES(trigger_price),
                pullback_price = VALUES(pullback_price),
                stop_loss = VALUES(stop_loss),
                take_profit = VALUES(take_profit),
                time_limit_date = VALUES(time_limit_date),
                confidence = VALUES(confidence),
                reason_json = VALUES(reason_json),
                confirmation_json = VALUES(confirmation_json),
                invalidation_json = VALUES(invalidation_json),
                risk_json = VALUES(risk_json),
                evidence_refs_json = VALUES(evidence_refs_json)""",
            records,
        )
        return len(records)

    def load_entry_plans(self, run_id: str, ready_only: bool = False) -> list[EntryPlan]:
        sql = """SELECT plan_id, run_id, recommendation_id, instrument_id, rank_position AS `rank`,
                        entry_mode, entry_status, reference_price, trigger_price, pullback_price,
                        stop_loss, take_profit, time_limit_date, confidence, reason_json,
                        confirmation_json, invalidation_json, risk_json, evidence_refs_json
                 FROM entry_plans
                 WHERE run_id = %s"""
        params: list[object] = [run_id]
        if ready_only:
            sql += " AND entry_status = %s"
            params.append("ready")
        sql += " ORDER BY rank_position ASC"
        return [_plan_from_row(row) for row in _fetch_all(self, sql, params)]

    def load_entry_plans_for_recommendation_run(
        self,
        recommendation_run_id: str,
        ready_only: bool = False,
    ) -> list[EntryPlan]:
        sql = """SELECT p.plan_id, p.run_id, p.recommendation_id, p.instrument_id, p.rank_position AS `rank`,
                        p.entry_mode, p.entry_status, p.reference_price, p.trigger_price, p.pullback_price,
                        p.stop_loss, p.take_profit, p.time_limit_date, p.confidence, p.reason_json,
                        p.confirmation_json, p.invalidation_json, p.risk_json, p.evidence_refs_json
                 FROM entry_plans p
                 JOIN entry_plan_runs r ON p.run_id = r.run_id
                 WHERE r.recommendation_run_id = %s"""
        params: list[object] = [recommendation_run_id]
        if ready_only:
            sql += " AND p.entry_status = %s"
            params.append("ready")
        sql += " ORDER BY p.rank_position ASC"
        return [_plan_from_row(row) for row in _fetch_all(self, sql, params)]

    def load_due_entry_plans(self, as_of: str, limit: int | None = None) -> list[EntryPlan]:
        sql = """SELECT p.plan_id, p.run_id, p.recommendation_id, p.instrument_id, p.rank_position AS `rank`,
                        p.entry_mode, p.entry_status, p.reference_price, p.trigger_price, p.pullback_price,
                        p.stop_loss, p.take_profit, p.time_limit_date, p.confidence, p.reason_json,
                        p.confirmation_json, p.invalidation_json, p.risk_json, p.evidence_refs_json
                 FROM entry_plans p
                 LEFT JOIN entry_plan_reviews rv ON p.plan_id = rv.plan_id
                 WHERE p.time_limit_date <= %s
                   AND rv.review_id IS NULL
                 ORDER BY p.time_limit_date ASC, p.rank_position ASC"""
        params: list[object] = [as_of]
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        return [_plan_from_row(row) for row in _fetch_all(self, sql, params)]

    def upsert_entry_plan_review(self, review: EntryPlanReview) -> None:
        _execute_one(
            self,
            """INSERT INTO entry_plan_reviews (
                review_id, plan_id, review_date, triggered, trigger_date, entry_price,
                review_price, realized_return, max_drawdown, max_favorable_return,
                avoided_chase_loss, missed_opportunity, entry_quality_score, review_notes_json
            ) VALUES (
                %(review_id)s, %(plan_id)s, %(review_date)s, %(triggered)s, %(trigger_date)s, %(entry_price)s,
                %(review_price)s, %(realized_return)s, %(max_drawdown)s, %(max_favorable_return)s,
                %(avoided_chase_loss)s, %(missed_opportunity)s, %(entry_quality_score)s, %(review_notes_json)s
            )
            ON DUPLICATE KEY UPDATE
                review_date = VALUES(review_date),
                triggered = VALUES(triggered),
                trigger_date = VALUES(trigger_date),
                entry_price = VALUES(entry_price),
                review_price = VALUES(review_price),
                realized_return = VALUES(realized_return),
                max_drawdown = VALUES(max_drawdown),
                max_favorable_return = VALUES(max_favorable_return),
                avoided_chase_loss = VALUES(avoided_chase_loss),
                missed_opportunity = VALUES(missed_opportunity),
                entry_quality_score = VALUES(entry_quality_score),
                review_notes_json = VALUES(review_notes_json)""",
            review.to_record(),
        )


def _execute_one(storage: MySQLEntryStorage, sql: str, record: dict) -> None:
    connection = storage.connection_factory(storage.config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, record)
        connection.commit()
    finally:
        connection.close()


def _execute_many(storage: MySQLEntryStorage, sql: str, records: list[dict]) -> None:
    connection = storage.connection_factory(storage.config)
    try:
        with connection.cursor() as cursor:
            cursor.executemany(sql, records)
        connection.commit()
    finally:
        connection.close()


def _fetch_all(storage: MySQLEntryStorage, sql: str, params: list[object]) -> list:
    connection = storage.connection_factory(storage.config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        connection.close()
    return list(rows)


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)


def _plan_from_row(row) -> EntryPlan:
    values = _row_dict(
        row,
        [
            "plan_id",
            "run_id",
            "recommendation_id",
            "instrument_id",
            "rank",
            "entry_mode",
            "entry_status",
            "reference_price",
            "trigger_price",
            "pullback_price",
            "stop_loss",
            "take_profit",
            "time_limit_date",
            "confidence",
            "reason_json",
            "confirmation_json",
            "invalidation_json",
            "risk_json",
            "evidence_refs_json",
        ],
    )
    return EntryPlan(
        plan_id=values["plan_id"],
        run_id=values["run_id"],
        recommendation_id=values["recommendation_id"],
        instrument_id=values["instrument_id"],
        rank=int(values["rank"]),
        entry_mode=values["entry_mode"],
        entry_status=values["entry_status"],
        reference_price=_optional_float(values["reference_price"]),
        trigger_price=_optional_float(values["trigger_price"]),
        pullback_price=_optional_float(values["pullback_price"]),
        stop_loss=_optional_float(values["stop_loss"]),
        take_profit=_optional_float(values["take_profit"]),
        time_limit_date=str(values["time_limit_date"]),
        confidence=float(values["confidence"]),
        reason_json=values["reason_json"],
        confirmation_json=values["confirmation_json"],
        invalidation_json=values["invalidation_json"],
        risk_json=values["risk_json"],
        evidence_refs_json=values["evidence_refs_json"],
    )


def _row_dict(row, columns: list[str]) -> dict:
    if isinstance(row, dict):
        return row
    return dict(zip(columns, row, strict=False))


def _optional_float(value) -> float | None:
    return float(value) if value is not None else None
