# Entry Timing Research Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a research evaluation loop that measures whether entry timing plans improve realized selection quality.

**Architecture:** Reuse the existing research `backtest_runs` table for entry evaluation run metadata with `source_type="entry"`, and persist per-plan realized metrics in existing `entry_plan_reviews`. Add a research evaluator that loads one `entry_plan_run`, reviews all plans against forward bars, stores reviews, and summarizes performance by entry status and mode.

**Tech Stack:** Python 3.13, pandas, Click CLI, existing MySQL storages, existing `EntryPlan` and `EntryPlanReview` models.

---

## File Structure

- Modify `src/openstockagent/entry/storage.py`: add `load_entry_plan_run(run_id)` so research can recover `as_of`, horizon, and market regime for an entry run.
- Modify `src/openstockagent/research/evaluation.py`: add `EntryPlanBacktestEvaluation` and `evaluate_entry_plan_run()`.
- Modify `src/openstockagent/cli/stock_research.py`: add `stock-research evaluate-entry`.
- Modify `tests/test_entry_storage.py`: cover `load_entry_plan_run()`.
- Modify `tests/test_research_evaluation.py`: cover entry plan evaluation summary and persistence.
- Modify `tests/test_research_cli.py`: cover CLI wiring.

## Task 1: Entry Run Loader

**Files:**
- Modify: `src/openstockagent/entry/storage.py`
- Test: `tests/test_entry_storage.py`

- [ ] Add `load_entry_plan_run(run_id: str) -> EntryPlanRun | None`.
- [ ] Add `_run_from_row(row) -> EntryPlanRun`.
- [ ] Green-test that the loader selects from `entry_plan_runs` and returns an `EntryPlanRun`.

## Task 2: Research Evaluator

**Files:**
- Modify: `src/openstockagent/research/evaluation.py`
- Test: `tests/test_research_evaluation.py`

- [ ] Add `EntryPlanBacktestEvaluation(run, reviews, errors)`.
- [ ] Add `evaluate_entry_plan_run(entry_run_id, entry_storage, bar_storage, research_storage=None, review_date=None, ...)`.
- [ ] Load the entry run and plans.
- [ ] Build `EntryPlanReview` for each plan using forward bars.
- [ ] Persist reviews through `entry_storage.upsert_entry_plan_review`.
- [ ] Persist `BacktestRun(source_type="entry", source_run_id=entry_run_id, ...)`.
- [ ] Summarize `triggered_rate`, `mean_realized_return`, `mean_entry_quality_score`, `mean_missed_opportunity`, `mean_avoided_chase_loss`, plus grouped stats by entry status and mode.

## Task 3: CLI

**Files:**
- Modify: `src/openstockagent/cli/stock_research.py`
- Test: `tests/test_research_cli.py`

- [ ] Add command `stock-research evaluate-entry --entry-run-id ENTRY_RUN_ID`.
- [ ] Accept `--review-date`, `--source`, `--adjustment`, `--interval`.
- [ ] Print run id, counts, triggered rate, realized return, quality score, missed opportunity, avoided chase loss, and per-review rows.

## Task 4: Verification

**Files:**
- Existing test suite.

- [ ] Run targeted tests:

```bash
uv run pytest tests/test_entry_storage.py tests/test_research_evaluation.py tests/test_research_cli.py
```

- [ ] Run full suite:

```bash
uv run pytest
```

- [ ] Run diff whitespace check:

```bash
git diff --check
```
