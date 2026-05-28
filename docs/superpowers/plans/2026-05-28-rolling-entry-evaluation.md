# Rolling Entry Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a rolling research loop that repeatedly generates recommendations, entry plans, and entry evaluations across rebalance dates.

**Architecture:** Extend `openstockagent.research.rolling` with a `run_rolling_entry_evaluation()` orchestrator. It reuses existing factor, screening, recommendation, entry, and entry-evaluation runners, persists experiment metadata in `research_experiment_runs/days`, and stores detailed per-plan review metrics through the existing entry and research tables.

**Tech Stack:** Python 3.13, pandas, Click CLI, existing MySQL storages, existing research/entry/recommendation runners.

---

## File Structure

- Modify `src/openstockagent/research/rolling.py`: add `RollingEntryEvaluationResult` and `run_rolling_entry_evaluation()`.
- Modify `src/openstockagent/cli/stock_research.py`: add `stock-research rolling-entry`.
- Modify `tests/test_research_rolling.py`: cover rolling entry orchestration, summaries, and persisted experiment days.
- Modify `tests/test_research_cli.py`: cover CLI wiring.

## Task 1: Rolling Entry Orchestrator

**Files:**
- Modify: `src/openstockagent/research/rolling.py`
- Test: `tests/test_research_rolling.py`

- [ ] Add `RollingEntryEvaluationResult`.
- [ ] Add `run_rolling_entry_evaluation()` with dependencies injected like the existing rolling screen runner.
- [ ] For each rebalance date run:

```text
factor_runner -> screening_runner -> recommendation_runner -> entry_runner -> entry_evaluator
```

- [ ] Build `ResearchExperimentDay` where `backtest_run_id` is the entry evaluation run id and `summary_json` includes `recommendation_run_id` and `entry_run_id`.
- [ ] Aggregate summary metrics across all entry evaluations.

## Task 2: CLI

**Files:**
- Modify: `src/openstockagent/cli/stock_research.py`
- Test: `tests/test_research_cli.py`

- [ ] Add `stock-research rolling-entry`.
- [ ] Options: universe, start/end date, horizon, rebalance frequency, market, top-n, lookback days, interval, source, adjustment, market-regime, max-dates, mysql config.
- [ ] Print experiment id, dates seen, generated run counts, reviewed count, triggered rate, realized return, quality score, missed opportunity, and avoided chase loss.

## Task 3: Verification

**Files:**
- Existing test suite.

- [ ] Run targeted tests:

```bash
uv run pytest tests/test_research_rolling.py tests/test_research_cli.py
```

- [ ] Run full suite:

```bash
uv run pytest
```

- [ ] Run diff whitespace check:

```bash
git diff --check
```
