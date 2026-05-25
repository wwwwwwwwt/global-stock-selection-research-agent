"""MySQL-backed recommendation storage."""
from __future__ import annotations

from collections.abc import Callable

from openstockagent.database.mysql import MySQLConfig
from openstockagent.recommendations.models import RecommendationItem, RecommendationReview, RecommendationRun


RECOMMENDATION_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS recommendation_runs (
  run_id VARCHAR(128) NOT NULL,
  screen_run_id VARCHAR(128) NOT NULL,
  universe_id VARCHAR(64) NOT NULL,
  recommendation_date DATE NOT NULL,
  horizon VARCHAR(16) NOT NULL,
  review_due_date DATE NOT NULL,
  strategy_name VARCHAR(128) NOT NULL,
  strategy_version VARCHAR(32) NOT NULL,
  market_regime VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (run_id),
  KEY idx_recommendation_runs_screen (screen_run_id),
  KEY idx_recommendation_runs_lookup (universe_id, recommendation_date, horizon),
  KEY idx_recommendation_runs_review_due (review_due_date, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

RECOMMENDATION_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS recommendation_items (
  recommendation_id VARCHAR(128) NOT NULL,
  run_id VARCHAR(128) NOT NULL,
  instrument_id VARCHAR(128) NOT NULL,
  rank_position INTEGER NOT NULL,
  action VARCHAR(32) NOT NULL,
  source_screen_rank INTEGER NOT NULL,
  source_screen_score DOUBLE NOT NULL,
  expected_return DOUBLE NULL,
  expected_risk DOUBLE NULL,
  confidence DOUBLE NOT NULL,
  thesis_json JSON NOT NULL,
  confirmation_json JSON NOT NULL,
  invalidation_json JSON NOT NULL,
  risk_json JSON NOT NULL,
  evidence_refs_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (recommendation_id),
  UNIQUE KEY uq_recommendation_items_run_instrument (run_id, instrument_id),
  KEY idx_recommendation_items_rank (run_id, rank_position),
  KEY idx_recommendation_items_action (run_id, action, rank_position)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

RECOMMENDATION_REVIEWS_DDL = """
CREATE TABLE IF NOT EXISTS recommendation_reviews (
  review_id VARCHAR(128) NOT NULL,
  recommendation_id VARCHAR(128) NOT NULL,
  review_date DATE NOT NULL,
  entry_price DOUBLE NOT NULL,
  review_price DOUBLE NOT NULL,
  realized_return DOUBLE NOT NULL,
  benchmark_return DOUBLE NULL,
  excess_return DOUBLE NULL,
  max_drawdown DOUBLE NULL,
  max_favorable_return DOUBLE NULL,
  hit TINYINT(1) NOT NULL,
  thesis_status VARCHAR(32) NOT NULL,
  invalidation_triggered TINYINT(1) NOT NULL,
  factor_snapshot_json JSON NOT NULL,
  review_notes_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (review_id),
  KEY idx_recommendation_reviews_item (recommendation_id, review_date),
  KEY idx_recommendation_reviews_hit (hit, review_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class MySQLRecommendationStorage:
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
                cursor.execute(RECOMMENDATION_RUNS_DDL)
                cursor.execute(RECOMMENDATION_ITEMS_DDL)
                cursor.execute(RECOMMENDATION_REVIEWS_DDL)
            connection.commit()
        finally:
            connection.close()

    def upsert_recommendation_run(self, run: RecommendationRun) -> None:
        record = run.to_record()
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO recommendation_runs (
                        run_id, screen_run_id, universe_id, recommendation_date, horizon,
                        review_due_date, strategy_name, strategy_version, market_regime, status
                    ) VALUES (
                        %(run_id)s, %(screen_run_id)s, %(universe_id)s, %(recommendation_date)s, %(horizon)s,
                        %(review_due_date)s, %(strategy_name)s, %(strategy_version)s, %(market_regime)s, %(status)s
                    )
                    ON DUPLICATE KEY UPDATE
                        screen_run_id = VALUES(screen_run_id),
                        universe_id = VALUES(universe_id),
                        recommendation_date = VALUES(recommendation_date),
                        horizon = VALUES(horizon),
                        review_due_date = VALUES(review_due_date),
                        strategy_name = VALUES(strategy_name),
                        strategy_version = VALUES(strategy_version),
                        market_regime = VALUES(market_regime),
                        status = VALUES(status)""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()

    def delete_recommendation_items(self, run_id: str) -> int:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                affected = cursor.execute("DELETE FROM recommendation_items WHERE run_id = %s", [run_id])
            connection.commit()
        finally:
            connection.close()
        return int(affected or 0)

    def upsert_recommendation_items(self, items: list[RecommendationItem]) -> int:
        if not items:
            return 0
        records = [item.to_record() for item in items]
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO recommendation_items (
                        recommendation_id, run_id, instrument_id, rank_position, action,
                        source_screen_rank, source_screen_score, expected_return, expected_risk, confidence,
                        thesis_json, confirmation_json, invalidation_json, risk_json, evidence_refs_json
                    ) VALUES (
                        %(recommendation_id)s, %(run_id)s, %(instrument_id)s, %(rank_position)s, %(action)s,
                        %(source_screen_rank)s, %(source_screen_score)s, %(expected_return)s, %(expected_risk)s, %(confidence)s,
                        %(thesis_json)s, %(confirmation_json)s, %(invalidation_json)s, %(risk_json)s, %(evidence_refs_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        rank_position = VALUES(rank_position),
                        action = VALUES(action),
                        source_screen_rank = VALUES(source_screen_rank),
                        source_screen_score = VALUES(source_screen_score),
                        expected_return = VALUES(expected_return),
                        expected_risk = VALUES(expected_risk),
                        confidence = VALUES(confidence),
                        thesis_json = VALUES(thesis_json),
                        confirmation_json = VALUES(confirmation_json),
                        invalidation_json = VALUES(invalidation_json),
                        risk_json = VALUES(risk_json),
                        evidence_refs_json = VALUES(evidence_refs_json)""",
                    records,
                )
            connection.commit()
        finally:
            connection.close()
        return len(records)

    def load_recommendation_items(self, run_id: str, actionable_only: bool = False) -> list[RecommendationItem]:
        sql = """SELECT recommendation_id, run_id, instrument_id, rank_position AS `rank`, action,
                        source_screen_rank, source_screen_score, expected_return, expected_risk, confidence,
                        thesis_json, confirmation_json, invalidation_json, risk_json, evidence_refs_json
                 FROM recommendation_items
                 WHERE run_id = %s"""
        params: list[object] = [run_id]
        if actionable_only:
            sql += " AND action IN (%s, %s)"
            params.extend(["buy_candidate", "watch"])
        sql += " ORDER BY rank_position ASC"

        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_item_from_row(row) for row in rows]

    def load_due_recommendation_items(self, as_of: str, limit: int | None = None) -> list[dict]:
        sql = """SELECT i.recommendation_id, i.run_id, i.instrument_id, i.rank_position AS `rank`, i.action,
                        i.source_screen_rank, i.source_screen_score, i.expected_return, i.expected_risk, i.confidence,
                        i.thesis_json, i.confirmation_json, i.invalidation_json, i.risk_json, i.evidence_refs_json,
                        r.recommendation_date, r.review_due_date, r.horizon
                 FROM recommendation_items i
                 JOIN recommendation_runs r ON i.run_id = r.run_id
                 LEFT JOIN recommendation_reviews rv ON i.recommendation_id = rv.recommendation_id
                 WHERE r.review_due_date <= %s
                   AND i.action IN (%s, %s)
                   AND rv.review_id IS NULL
                 ORDER BY r.review_due_date ASC, i.rank_position ASC"""
        params: list[object] = [as_of, "buy_candidate", "watch"]
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)

        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        finally:
            connection.close()
        due = []
        for row in rows:
            values = _row_dict(
                row,
                [
                    "recommendation_id",
                    "run_id",
                    "instrument_id",
                    "rank",
                    "action",
                    "source_screen_rank",
                    "source_screen_score",
                    "expected_return",
                    "expected_risk",
                    "confidence",
                    "thesis_json",
                    "confirmation_json",
                    "invalidation_json",
                    "risk_json",
                    "evidence_refs_json",
                    "recommendation_date",
                    "review_due_date",
                    "horizon",
                ],
            )
            due.append(
                {
                    "item": _item_from_row(values),
                    "recommendation_date": values["recommendation_date"],
                    "review_due_date": values["review_due_date"],
                    "horizon": values["horizon"],
                }
            )
        return due

    def upsert_recommendation_review(self, review: RecommendationReview) -> None:
        record = review.to_record()
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO recommendation_reviews (
                        review_id, recommendation_id, review_date, entry_price, review_price,
                        realized_return, benchmark_return, excess_return, max_drawdown, max_favorable_return,
                        hit, thesis_status, invalidation_triggered, factor_snapshot_json, review_notes_json
                    ) VALUES (
                        %(review_id)s, %(recommendation_id)s, %(review_date)s, %(entry_price)s, %(review_price)s,
                        %(realized_return)s, %(benchmark_return)s, %(excess_return)s, %(max_drawdown)s, %(max_favorable_return)s,
                        %(hit)s, %(thesis_status)s, %(invalidation_triggered)s, %(factor_snapshot_json)s, %(review_notes_json)s
                    )
                    ON DUPLICATE KEY UPDATE
                        review_date = VALUES(review_date),
                        entry_price = VALUES(entry_price),
                        review_price = VALUES(review_price),
                        realized_return = VALUES(realized_return),
                        benchmark_return = VALUES(benchmark_return),
                        excess_return = VALUES(excess_return),
                        max_drawdown = VALUES(max_drawdown),
                        max_favorable_return = VALUES(max_favorable_return),
                        hit = VALUES(hit),
                        thesis_status = VALUES(thesis_status),
                        invalidation_triggered = VALUES(invalidation_triggered),
                        factor_snapshot_json = VALUES(factor_snapshot_json),
                        review_notes_json = VALUES(review_notes_json)""",
                    record,
                )
            connection.commit()
        finally:
            connection.close()

    def load_recommendation_reviews(self, recommendation_id: str) -> list[RecommendationReview]:
        connection = self.connection_factory(self.config)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT review_id, recommendation_id, review_date, entry_price, review_price,
                              realized_return, benchmark_return, excess_return, max_drawdown, max_favorable_return,
                              hit, thesis_status, invalidation_triggered, factor_snapshot_json, review_notes_json
                       FROM recommendation_reviews
                       WHERE recommendation_id = %s
                       ORDER BY review_date ASC""",
                    [recommendation_id],
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_review_from_row(row) for row in rows]


def _connect(config: MySQLConfig):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(**config.to_connection_kwargs(), cursorclass=DictCursor)


def _item_from_row(row) -> RecommendationItem:
    values = _row_dict(
        row,
        [
            "recommendation_id",
            "run_id",
            "instrument_id",
            "rank",
            "action",
            "source_screen_rank",
            "source_screen_score",
            "expected_return",
            "expected_risk",
            "confidence",
            "thesis_json",
            "confirmation_json",
            "invalidation_json",
            "risk_json",
            "evidence_refs_json",
        ],
    )
    return RecommendationItem(
        recommendation_id=values["recommendation_id"],
        run_id=values["run_id"],
        instrument_id=values["instrument_id"],
        rank=int(values["rank"]),
        action=values["action"],
        source_screen_rank=int(values["source_screen_rank"]),
        source_screen_score=float(values["source_screen_score"]),
        expected_return=float(values["expected_return"]) if values["expected_return"] is not None else None,
        expected_risk=float(values["expected_risk"]) if values["expected_risk"] is not None else None,
        confidence=float(values["confidence"]),
        thesis_json=values["thesis_json"],
        confirmation_json=values["confirmation_json"],
        invalidation_json=values["invalidation_json"],
        risk_json=values["risk_json"],
        evidence_refs_json=values["evidence_refs_json"],
    )


def _review_from_row(row) -> RecommendationReview:
    values = _row_dict(
        row,
        [
            "review_id",
            "recommendation_id",
            "review_date",
            "entry_price",
            "review_price",
            "realized_return",
            "benchmark_return",
            "excess_return",
            "max_drawdown",
            "max_favorable_return",
            "hit",
            "thesis_status",
            "invalidation_triggered",
            "factor_snapshot_json",
            "review_notes_json",
        ],
    )
    return RecommendationReview(
        review_id=values["review_id"],
        recommendation_id=values["recommendation_id"],
        review_date=str(values["review_date"]),
        entry_price=float(values["entry_price"]),
        review_price=float(values["review_price"]),
        realized_return=float(values["realized_return"]),
        benchmark_return=float(values["benchmark_return"]) if values["benchmark_return"] is not None else None,
        excess_return=float(values["excess_return"]) if values["excess_return"] is not None else None,
        max_drawdown=float(values["max_drawdown"]) if values["max_drawdown"] is not None else None,
        max_favorable_return=float(values["max_favorable_return"]) if values["max_favorable_return"] is not None else None,
        hit=bool(values["hit"]),
        thesis_status=values["thesis_status"],
        invalidation_triggered=bool(values["invalidation_triggered"]),
        factor_snapshot_json=values["factor_snapshot_json"],
        review_notes_json=values["review_notes_json"],
    )


def _row_dict(row, columns: list[str]) -> dict:
    if isinstance(row, dict):
        return row
    return dict(zip(columns, row, strict=True))
