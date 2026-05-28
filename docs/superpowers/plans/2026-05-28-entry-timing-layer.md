# Entry Timing Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete Entry Timing layer that turns horizon-aware recommendations into buy/wait/avoid entry plans before portfolio allocation.

**Architecture:** Add a new `openstockagent.entry` package between `recommendations` and `portfolio`. The layer consumes recommendation items plus canonical bars, factor values, market reality status, and market regime; it persists entry plan runs, per-stock entry plans, and entry reviews; portfolio can then allocate only from `entry_status=ready` plans. This plan intentionally focuses on functional architecture and end-to-end workflow, not performance caching or advanced intraday execution.

**Tech Stack:** Python 3.13, Click CLI, pandas, PyMySQL-backed MySQL storages, existing `RecommendationItem`, `PortfolioDecision`, `FactorValue`, and canonical `bars`.

---

## File Structure

- Create `src/openstockagent/entry/__init__.py`: package marker.
- Create `src/openstockagent/entry/models.py`: immutable dataclasses for entry plan runs, plans, reviews, and runner results.
- Create `src/openstockagent/entry/rules.py`: deterministic v1 entry mode rules using recommendation action, bars, factor values, risk flags, and market regime.
- Create `src/openstockagent/entry/storage.py`: MySQL DDL and persistence/load methods for entry plan runs, plans, and reviews.
- Create `src/openstockagent/entry/runner.py`: orchestration from recommendation run to entry plan run, and due review generation.
- Create `src/openstockagent/cli/run_entry.py`: `stock-entry from-recommendation` and `stock-entry review-due`.
- Modify `src/openstockagent/portfolio/decision.py`: allow portfolio decisions to consume entry-ready items instead of raw recommendations.
- Modify `src/openstockagent/portfolio/models.py`: add optional `source_entry_plan_id` to `TargetAllocation`.
- Modify `src/openstockagent/portfolio/storage.py`: add nullable `source_entry_plan_id` column to target allocations.
- Modify `src/openstockagent/cli/run_portfolio.py`: add `--entry-run-id` option and load ready entry plans when provided.
- Modify `src/openstockagent/pipelines/cn_daily_selection.py`: run entry plans between recommendation and portfolio decisions.
- Modify `src/openstockagent/cli/stock_data.py`: expose entry-plan summary in `stock-data run-cn-selection`.
- Modify `pyproject.toml`: add `stock-entry = "openstockagent.cli.run_entry:main"`.
- Test `tests/test_entry.py`: models, rules, runner, review calculations.
- Test `tests/test_entry_storage.py`: MySQL DDL/upsert/load SQL behavior.
- Test `tests/test_entry_cli.py`: CLI wiring.
- Modify `tests/test_portfolio.py`: portfolio allocation respects entry readiness.
- Modify `tests/test_portfolio_cli.py`: `stock-portfolio decide --entry-run-id` loads entry-ready plans.
- Modify `tests/test_cn_daily_selection_pipeline.py`: CN daily pipeline includes entry plan before portfolio.

## Design Rules

Entry modes:

```text
breakout_buy
pullback_buy
range_buy
reversal_buy
wait_confirm
avoid_chase
no_entry
```

Entry statuses:

```text
ready
wait
avoid
invalid
expired
```

Functional v1 rule order:

```text
1. Recommendation action skip -> no_entry / invalid.
2. Market regime data_bad or high_risk -> no_entry / invalid.
3. Status ST, suspended, not tradable -> no_entry / invalid.
4. Latest bar missing or close <= 0 -> no_entry / invalid.
5. Short-term extension too high -> avoid_chase / avoid or pullback_buy / wait.
6. Strong trend with breakout -> breakout_buy / ready.
7. Strong trend without breakout -> pullback_buy / wait.
8. Weak but improving trend -> wait_confirm / wait.
9. Otherwise -> no_entry / avoid.
```

The first version uses daily bars. It computes:

```text
reference_price = latest close
recent_high_20d = max high over available 20 daily bars
recent_low_20d = min low over available 20 daily bars
ma5 = 5-day close mean
ma20 = 20-day close mean
extension_from_ma20 = close / ma20 - 1
trigger_price = breakout threshold or confirmation threshold
pullback_price = ma5 or ma20-based pullback level
stop_loss = reference or planned entry minus risk buffer
take_profit = reference plus expected reward buffer
time_limit_date = recommendation review due date or horizon-derived date
```

## Task 1: Entry Data Models

**Files:**
- Create: `src/openstockagent/entry/__init__.py`
- Create: `src/openstockagent/entry/models.py`
- Test: `tests/test_entry.py`

- [ ] Create the package marker:

```python
"""Entry timing and execution-readiness planning."""
```

- [ ] Add dataclasses in `models.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class EntryPlanRun:
    run_id: str
    recommendation_run_id: str
    as_of: str
    horizon: str
    market_regime: str
    strategy_name: str
    strategy_version: str
    status: str
    summary_json: str

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EntryPlan:
    plan_id: str
    run_id: str
    recommendation_id: str
    instrument_id: str
    rank: int
    entry_mode: str
    entry_status: str
    reference_price: float | None
    trigger_price: float | None
    pullback_price: float | None
    stop_loss: float | None
    take_profit: float | None
    time_limit_date: str
    confidence: float
    reason_json: str
    confirmation_json: str
    invalidation_json: str
    risk_json: str
    evidence_refs_json: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["rank_position"] = record.pop("rank")
        return record


@dataclass(frozen=True)
class EntryPlanReview:
    review_id: str
    plan_id: str
    review_date: str
    triggered: bool
    trigger_date: str | None
    entry_price: float | None
    review_price: float | None
    realized_return: float | None
    max_drawdown: float | None
    max_favorable_return: float | None
    avoided_chase_loss: float | None
    missed_opportunity: float | None
    entry_quality_score: float | None
    review_notes_json: str

    def to_record(self) -> dict:
        record = asdict(self)
        record["triggered"] = int(self.triggered)
        return record


@dataclass(frozen=True)
class EntryPlanRunResult:
    run: EntryPlanRun
    plans: list[EntryPlan] = field(default_factory=list)
    ready_count: int = 0
    wait_count: int = 0
    avoid_count: int = 0
    invalid_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EntryReviewRunResult:
    as_of: str
    due_plans_seen: int
    reviews_written: int
    skipped_count: int
    errors: list[str] = field(default_factory=list)
    reviews: list[EntryPlanReview] = field(default_factory=list)
```

- [ ] Add a green test asserting `EntryPlan.to_record()` renames `rank` to `rank_position` and `EntryPlanReview.to_record()` stores `triggered` as `1` or `0`.

Run: `/opt/homebrew/bin/uv run pytest tests/test_entry.py`

## Task 2: Entry Rule Engine

**Files:**
- Create: `src/openstockagent/entry/rules.py`
- Test: `tests/test_entry.py`

- [ ] Implement `build_entry_plan()` with this signature:

```python
def build_entry_plan(
    *,
    run_id: str,
    recommendation_item,
    as_of: str,
    horizon: str,
    market_regime: str,
    bars,
    status=None,
    review_due_date: str | None = None,
    plan_id: str | None = None,
) -> EntryPlan:
```

- [ ] Implement deterministic price metrics:

```python
def price_metrics(bars) -> dict:
    frame = bars.copy().sort_values("timestamp")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["high"] = pd.to_numeric(frame.get("high", frame["close"]), errors="coerce")
    frame["low"] = pd.to_numeric(frame.get("low", frame["close"]), errors="coerce")
    frame = frame.dropna(subset=["close"])
    if frame.empty:
        return {"has_data": False}
    closes = frame["close"]
    latest_close = float(closes.iloc[-1])
    ma5 = float(closes.tail(min(5, len(closes))).mean())
    ma20 = float(closes.tail(min(20, len(closes))).mean())
    recent_high_20d = float(frame["high"].tail(min(20, len(frame))).max())
    recent_low_20d = float(frame["low"].tail(min(20, len(frame))).min())
    return {
        "has_data": True,
        "latest_close": latest_close,
        "ma5": ma5,
        "ma20": ma20,
        "recent_high_20d": recent_high_20d,
        "recent_low_20d": recent_low_20d,
        "extension_from_ma20": latest_close / ma20 - 1.0 if ma20 > 0 else None,
        "trend_strength": 1.0 if latest_close > ma5 > ma20 else 0.5 if latest_close > ma20 else 0.0,
    }
```

- [ ] Implement v1 rule thresholds:

```python
ENTRY_RULE_CONFIG = {
    "extension_avoid_threshold": 0.12,
    "extension_pullback_threshold": 0.06,
    "breakout_buffer": 0.005,
    "pullback_buffer": 0.01,
    "stop_loss_pct": 0.07,
    "take_profit_pct": 0.12,
}
```

- [ ] Green-test at least these cases:

```text
buy_candidate + strong trend + close near 20d high -> breakout_buy / ready
buy_candidate + strong trend + extension > 12% -> avoid_chase / avoid
buy_candidate + strong trend + extension between 6% and 12% -> pullback_buy / wait
watch + neutral trend -> wait_confirm / wait
market_regime=data_bad -> no_entry / invalid
suspended status -> no_entry / invalid
```

Run: `/opt/homebrew/bin/uv run pytest tests/test_entry.py`

## Task 3: Entry Storage

**Files:**
- Create: `src/openstockagent/entry/storage.py`
- Test: `tests/test_entry_storage.py`

- [ ] Add DDL constants:

```text
ENTRY_PLAN_RUNS_DDL
ENTRY_PLANS_DDL
ENTRY_PLAN_REVIEWS_DDL
```

Required MySQL tables:

```sql
entry_plan_runs(run_id, recommendation_run_id, as_of, horizon, market_regime, strategy_name, strategy_version, status, summary_json)
entry_plans(plan_id, run_id, recommendation_id, instrument_id, rank_position, entry_mode, entry_status, reference_price, trigger_price, pullback_price, stop_loss, take_profit, time_limit_date, confidence, reason_json, confirmation_json, invalidation_json, risk_json, evidence_refs_json)
entry_plan_reviews(review_id, plan_id, review_date, triggered, trigger_date, entry_price, review_price, realized_return, max_drawdown, max_favorable_return, avoided_chase_loss, missed_opportunity, entry_quality_score, review_notes_json)
```

- [ ] Implement `MySQLEntryStorage` methods:

```python
ensure_tables()
upsert_entry_plan_run(run: EntryPlanRun) -> None
delete_entry_plans(run_id: str) -> int
upsert_entry_plans(plans: list[EntryPlan]) -> int
load_entry_plans(run_id: str, ready_only: bool = False) -> list[EntryPlan]
load_due_entry_plans(as_of: str, limit: int | None = None) -> list[EntryPlan]
upsert_entry_plan_review(review: EntryPlanReview) -> None
```

- [ ] Green-test that storage creates all three tables, upserts run/plans/review, deletes plans by run id, and `ready_only=True` adds `entry_status = %s`.

Run: `/opt/homebrew/bin/uv run pytest tests/test_entry_storage.py`

## Task 4: Entry Runner

**Files:**
- Create: `src/openstockagent/entry/runner.py`
- Test: `tests/test_entry.py`

- [ ] Implement `run_entry_plan_pipeline()`:

```python
def run_entry_plan_pipeline(
    *,
    recommendation_run_id: str,
    as_of: str,
    horizon: str,
    market_regime: str,
    recommendation_storage,
    bar_storage,
    entry_storage,
    market_reality_storage=None,
    interval: str = "1d",
    source: str | None = None,
    adjustment: str | None = "split_adjusted",
    lookback_days: int = 80,
    review_due_date: str | None = None,
    strategy_name: str = "entry_timing_v1",
    strategy_version: str = "v1",
    run_id: str | None = None,
) -> EntryPlanRunResult:
```

- [ ] Runner behavior:

```text
load recommendation items with actionable_only=True
load each instrument's bars from as_of-lookback_days to as_of
load latest instrument status if market_reality_storage is present
build one EntryPlan per recommendation item
persist EntryPlanRun
delete then upsert EntryPlans for run_id
return counts by entry_status
```

- [ ] Implement stable ids:

```text
entry-run-{sha256(recommendation_run_id|as_of|horizon|strategy_name|strategy_version)[:16]}
entry-plan-{sha256(run_id|recommendation_id|instrument_id)[:16]}
entry-review-{sha256(plan_id|review_date)[:16]}
```

- [ ] Implement `run_due_entry_plan_reviews()`:

```text
load due entry plans where time_limit_date <= as_of and no review exists
load bars from as_of window
detect whether trigger_price was touched
compute triggered return, drawdown, missed opportunity, avoided chase loss
persist EntryPlanReview
```

- [ ] Green-test runner creates ready/wait/avoid/invalid counts and persists run/plans.

Run: `/opt/homebrew/bin/uv run pytest tests/test_entry.py`

## Task 5: Entry CLI

**Files:**
- Create: `src/openstockagent/cli/run_entry.py`
- Modify: `pyproject.toml`
- Test: `tests/test_entry_cli.py`

- [ ] Add `stock-entry` script:

```toml
stock-entry = "openstockagent.cli.run_entry:main"
```

- [ ] Add command:

```bash
stock-entry from-recommendation RECOMMENDATION_RUN_ID \
  --as-of 2026-05-28 \
  --horizon 5d \
  --market-regime neutral
```

- [ ] Add command:

```bash
stock-entry review-due --as-of 2026-06-05
```

- [ ] CLI output for `from-recommendation` must include:

```text
Entry plan run complete:
run_id=
recommendation_run_id=
ready_count=
wait_count=
avoid_count=
invalid_count=
```

- [ ] Green-test CLI monkeypatches MySQL storages and runner, then asserts command arguments are passed correctly.

Run: `/opt/homebrew/bin/uv run pytest tests/test_entry_cli.py`

## Task 6: Portfolio Integration

**Files:**
- Modify: `src/openstockagent/portfolio/models.py`
- Modify: `src/openstockagent/portfolio/storage.py`
- Modify: `src/openstockagent/portfolio/decision.py`
- Modify: `src/openstockagent/cli/run_portfolio.py`
- Test: `tests/test_portfolio.py`
- Test: `tests/test_portfolio_cli.py`

- [ ] Add `source_entry_plan_id: str | None = None` to `TargetAllocation`.

- [ ] Add `source_entry_plan_id VARCHAR(128) NULL` to `target_allocations`.

- [ ] Add an adapter in `portfolio/decision.py`:

```python
def recommendation_items_from_ready_entry_plans(entry_plans: list[EntryPlan], recommendation_items: list[RecommendationItem]) -> list[RecommendationItem]:
    by_id = {item.recommendation_id: item for item in recommendation_items}
    ready_ids = {plan.recommendation_id for plan in entry_plans if plan.entry_status == "ready"}
    return [item for item in recommendation_items if item.recommendation_id in ready_ids]
```

- [ ] When portfolio allocates from entry plans, set allocation `source_entry_plan_id` to the matching ready plan id.

- [ ] Add `stock-portfolio decide --entry-run-id ENTRY_RUN_ID`. If passed:

```text
load recommendation items from recommendation run
load ready entry plans from entry run
filter recommendation items to ready plans
allocate only filtered items
```

- [ ] Green-test:

```text
ready plan gets allocation
wait plan receives no allocation
avoid plan receives no allocation
allocation stores source_entry_plan_id
```

Run: `/opt/homebrew/bin/uv run pytest tests/test_portfolio.py tests/test_portfolio_cli.py`

## Task 7: CN Daily Pipeline Integration

**Files:**
- Modify: `src/openstockagent/pipelines/cn_daily_selection.py`
- Modify: `src/openstockagent/cli/stock_data.py`
- Test: `tests/test_cn_daily_selection_pipeline.py`

- [ ] Add optional `entry_storage` argument to `run_cn_daily_selection_pipeline`.

- [ ] After recommendation generation, run:

```python
entry_result = run_entry_plan_pipeline(
    recommendation_run_id=recommendation.run_id,
    as_of=trade_date,
    horizon=horizon,
    market_regime=effective_market_regime,
    recommendation_storage=recommendation_storage,
    bar_storage=market_data_storage,
    entry_storage=entry_storage,
    market_reality_storage=market_reality_storage,
    source="tushare",
)
```

- [ ] Portfolio should consume entry-ready plans if `entry_result` is present.

- [ ] Add CLI output:

```text
Entry plans:
run_id=...
ready=...
wait=...
avoid=...
invalid=...
```

- [ ] Green-test CN daily pipeline returns entry result and portfolio allocates only ready entry plans.

Run: `/opt/homebrew/bin/uv run pytest tests/test_cn_daily_selection_pipeline.py`

## Task 8: Green Verification And Commit

**Files:**
- All files above.

- [ ] Run focused green tests:

```bash
/opt/homebrew/bin/uv run pytest \
  tests/test_entry.py \
  tests/test_entry_storage.py \
  tests/test_entry_cli.py \
  tests/test_portfolio.py \
  tests/test_portfolio_cli.py \
  tests/test_cn_daily_selection_pipeline.py
```

- [ ] Run full suite:

```bash
/opt/homebrew/bin/uv run pytest
```

- [ ] Initialize local MySQL entry tables:

```bash
/opt/homebrew/bin/uv run stock-entry from-recommendation --help
```

- [ ] Commit:

```bash
git add src/openstockagent/entry src/openstockagent/cli/run_entry.py src/openstockagent/portfolio src/openstockagent/pipelines/cn_daily_selection.py src/openstockagent/cli/stock_data.py tests/test_entry.py tests/test_entry_storage.py tests/test_entry_cli.py tests/test_portfolio.py tests/test_portfolio_cli.py tests/test_cn_daily_selection_pipeline.py pyproject.toml docs/superpowers/plans/2026-05-28-entry-timing-layer.md
git commit -m "feat: add entry timing layer"
git push origin main
```

## Self-Review

- Spec coverage: The plan covers entry data models, deterministic entry rules, persistence, CLI, portfolio gating, CN daily pipeline integration, review loop, green tests, and commit.
- Scope: The plan does not include news, Chan theory, LLM reasoning, intraday triggers, broker execution, or performance caching. Those are intentionally separate later functional layers.
- Type consistency: The plan uses `EntryPlanRun`, `EntryPlan`, `EntryPlanReview`, `EntryPlanRunResult`, and `EntryReviewRunResult` consistently across models, storage, runner, CLI, and portfolio integration.
