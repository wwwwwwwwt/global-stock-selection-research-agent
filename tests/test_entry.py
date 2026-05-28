import json

import pandas as pd

from openstockagent.entry.models import EntryPlanReview
from openstockagent.entry.rules import build_entry_plan, build_entry_plan_review
from openstockagent.entry.runner import run_entry_plan_pipeline
from openstockagent.market.models import InstrumentStatus
from openstockagent.recommendations.models import RecommendationItem


def test_entry_plan_model_maps_rank_and_review_bool_to_storage_record():
    review = EntryPlanReview(
        review_id="entry-review-test",
        plan_id="entry-plan-test",
        review_date="2026-06-03",
        triggered=True,
        trigger_date="2026-05-28",
        entry_price=10.5,
        review_price=11.0,
        realized_return=0.047619,
        max_drawdown=-0.02,
        max_favorable_return=0.08,
        avoided_chase_loss=None,
        missed_opportunity=None,
        entry_quality_score=0.7,
        review_notes_json="{}",
    )

    assert review.to_record()["triggered"] == 1


def test_entry_rules_mark_breakout_as_ready_with_trigger_and_risk_prices():
    item = _item("rec-a", "EQUITY:CN:000001", confidence=0.9)
    plan = build_entry_plan(
        run_id="entry-run-test",
        recommendation=item,
        bars=_trend_bars("EQUITY:CN:000001"),
        as_of="2026-05-27",
        horizon="5d",
        market_regime="neutral",
    )

    assert plan.entry_mode == "breakout_buy"
    assert plan.entry_status == "ready"
    assert plan.reference_price is not None
    assert plan.trigger_price is not None
    assert plan.stop_loss is not None
    assert plan.take_profit is not None
    assert json.loads(plan.reason_json)["reason"] == "strong_trend_near_breakout"


def test_entry_rules_block_st_and_suspended_statuses():
    item = _item("rec-a", "EQUITY:CN:000001", confidence=0.9)
    status = InstrumentStatus(
        instrument_id="EQUITY:CN:000001",
        status_date="2026-05-27",
        status="st",
        is_tradable=False,
        is_st=True,
        is_suspended=False,
    )

    plan = build_entry_plan(
        run_id="entry-run-test",
        recommendation=item,
        bars=_trend_bars("EQUITY:CN:000001"),
        as_of="2026-05-27",
        horizon="5d",
        market_regime="neutral",
        status=status,
    )

    assert plan.entry_mode == "no_entry"
    assert plan.entry_status == "invalid"
    assert json.loads(plan.reason_json)["reason"] == "instrument_status_blocks_entry"


def test_entry_review_calculates_triggered_return_and_excursion():
    plan = build_entry_plan(
        run_id="entry-run-test",
        recommendation=_item("rec-a", "EQUITY:CN:000001", confidence=0.9),
        bars=_trend_bars("EQUITY:CN:000001"),
        as_of="2026-05-27",
        horizon="5d",
        market_regime="neutral",
    )
    review_bars = pd.DataFrame(
        {
            "timestamp": ["2026-05-28", "2026-05-29", "2026-06-01"],
            "local_date": ["2026-05-28", "2026-05-29", "2026-06-01"],
            "open": [160.0, 161.0, 163.0],
            "high": [plan.trigger_price + 0.1, 164.0, 165.0],
            "low": [158.0, 160.0, 162.0],
            "close": [161.0, 163.0, 164.0],
        }
    )

    review = build_entry_plan_review(plan=plan, bars=review_bars, review_date="2026-06-03")

    assert review.triggered is True
    assert review.entry_price == plan.trigger_price
    assert review.realized_return is not None
    assert review.max_drawdown is not None
    assert review.max_favorable_return is not None
    assert review.entry_quality_score is not None


def test_entry_runner_persists_run_and_plans_from_recommendations():
    recommendation_storage = FakeRecommendationStorage([_item("rec-a", "EQUITY:CN:000001", confidence=0.9)])
    bar_storage = FakeBarStorage({"EQUITY:CN:000001": _trend_bars("EQUITY:CN:000001")})
    entry_storage = FakeEntryStorage()

    result = run_entry_plan_pipeline(
        recommendation_run_id="rec-run-test",
        as_of="2026-05-27",
        horizon="5d",
        market_regime="neutral",
        recommendation_storage=recommendation_storage,
        bar_storage=bar_storage,
        entry_storage=entry_storage,
        source="tushare",
        adjustment="split_adjusted",
    )

    assert result.run.recommendation_run_id == "rec-run-test"
    assert result.plans[0].entry_status == "ready"
    assert entry_storage.run == result.run
    assert entry_storage.plans == result.plans
    assert json.loads(result.run.summary_json)["ready_count"] == 1


def _item(recommendation_id, instrument_id, *, confidence=0.8, action="buy_candidate"):
    return RecommendationItem(
        recommendation_id=recommendation_id,
        run_id="rec-run-test",
        instrument_id=instrument_id,
        rank=1,
        action=action,
        source_screen_rank=1,
        source_screen_score=0.8,
        expected_return=0.03,
        expected_risk=0.1,
        confidence=confidence,
        thesis_json="{}",
        confirmation_json="{}",
        invalidation_json="{}",
        risk_json="{}",
        evidence_refs_json="{}",
    )


def _trend_bars(instrument_id):
    dates = pd.bdate_range("2026-03-05", periods=60)
    close = pd.Series([100.0 + index for index in range(60)])
    return pd.DataFrame(
        {
            "instrument_id": instrument_id,
            "timestamp": dates.strftime("%Y-%m-%d"),
            "local_date": dates.strftime("%Y-%m-%d"),
            "interval": "1d",
            "source": "tushare",
            "adjustment": "split_adjusted",
            "open": close - 0.5,
            "high": close + 0.2,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
            "amount": close * 1000.0,
        }
    )


class FakeRecommendationStorage:
    def __init__(self, items):
        self.items = items

    def load_recommendation_items(self, run_id, actionable_only=False):
        assert run_id == "rec-run-test"
        return self.items


class FakeBarStorage:
    def __init__(self, frames):
        self.frames = frames

    def load_bars(self, instrument_id, interval, start, end, source=None, adjustment=None):
        return self.frames[instrument_id].copy()


class FakeEntryStorage:
    def upsert_entry_plan_run(self, run):
        self.run = run

    def delete_entry_plans(self, run_id):
        self.deleted_run_id = run_id
        return 0

    def upsert_entry_plans(self, plans):
        self.plans = plans
        return len(plans)
