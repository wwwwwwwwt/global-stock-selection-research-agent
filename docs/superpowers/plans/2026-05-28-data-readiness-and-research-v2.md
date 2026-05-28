# Data Readiness And Research V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden A-share daily data readiness and prepare the research layer for rolling historical evaluation.

**Architecture:** Add a small readiness gate ahead of recommendation/portfolio generation, make Tushare empty daily responses return structured no-data results, and expose an explicit research storage initialization command. Keep the first implementation slice narrow; rolling experiments come after the data-readiness foundation is green.

**Tech Stack:** Python 3.13, Click CLI, pandas, PyMySQL-backed MySQL storages, pytest.

---

## File Structure

- Modify `src/openstockagent/pipelines/tushare_daily_batch.py`: return stable results when Tushare daily/daily_basic responses are empty or missing `ts_code`.
- Create `src/openstockagent/data/readiness.py`: compute data readiness from universe, bars, factor dates, trading calendar, and optional quality issue counts.
- Modify `src/openstockagent/data/storage.py`: add lightweight latest-bar and quality issue query helpers used by readiness.
- Modify `src/openstockagent/factors/storage.py`: add latest factor date helper.
- Modify `src/openstockagent/market/storage.py`: add calendar-day lookup helper.
- Modify `src/openstockagent/pipelines/cn_daily_selection.py`: run readiness check before recommendations and portfolio decisions; mark high-risk stale data as `data_bad`.
- Modify `src/openstockagent/cli/stock_research.py`: add `init-db` and rolling historical screen evaluation.
- Create `src/openstockagent/research/rolling.py`: run factor calculation, screening, and screen evaluation over a historical rebalance schedule.
- Modify `src/openstockagent/research/models.py`: add research experiment run/day models.
- Modify `src/openstockagent/research/storage.py`: persist research experiment summaries and per-date links.
- Test `tests/test_tushare_daily_batch.py`: empty provider frames do not crash.
- Test `tests/test_cn_daily_selection_pipeline.py`: stale data readiness gates recommendation/portfolio behavior.
- Test `tests/test_research_cli.py`: `stock-research init-db` initializes research tables.

## Task 1: Tushare Empty Daily Responses

**Files:**
- Modify: `src/openstockagent/pipelines/tushare_daily_batch.py`
- Test: `tests/test_tushare_daily_batch.py`

- [x] Add a test where `fetch_daily` and `fetch_daily_basic` return empty DataFrames. Assert result has zero rows, zero writes, and no exception.
- [x] Implement `_filter_source_symbols` so empty frames preserve expected source columns or downstream code never accesses missing columns.
- [x] Run `/opt/homebrew/bin/uv run pytest tests/test_tushare_daily_batch.py`.

## Task 2: Explicit Research DB Initialization

**Files:**
- Modify: `src/openstockagent/cli/stock_research.py`
- Test: `tests/test_research_cli.py`

- [x] Add CLI test for `stock-research init-db` that monkeypatches `MySQLResearchStorage` and asserts construction occurs.
- [x] Add `init-db` command that builds `MySQLResearchStorage(config=config)` and prints `Research storage initialized`.
- [x] Run `/opt/homebrew/bin/uv run pytest tests/test_research_cli.py`.

## Task 3: Data Readiness MVP

**Files:**
- Create: `src/openstockagent/data/readiness.py`
- Modify: `src/openstockagent/data/storage.py`
- Modify: `src/openstockagent/factors/storage.py`
- Modify: `src/openstockagent/market/storage.py`
- Test: `tests/test_cn_daily_selection_pipeline.py`

- [x] Add readiness model with status values `ready`, `stale`, `market_not_ready`, and `data_bad`.
- [x] Add storage helpers for latest universe bar date, latest factor date, and trading calendar day.
- [x] Add readiness tests using existing fake storages.
- [x] Keep default behavior permissive for tests where helper methods are not present; missing helpers should create warning flags rather than crash.

## Task 4: Gate CN Daily Selection

**Files:**
- Modify: `src/openstockagent/pipelines/cn_daily_selection.py`
- Test: `tests/test_cn_daily_selection_pipeline.py`

- [x] Run readiness after daily sync and technical factor calculation, before market context/recommendation/portfolio.
- [x] If readiness is `data_bad` or `market_not_ready`, use `effective_market_regime = "data_bad"` so recommendation becomes `skip` and portfolio stays cash.
- [x] Add readiness summary to `CNDailySelectionResult.messages`.
- [x] Run `/opt/homebrew/bin/uv run pytest tests/test_cn_daily_selection_pipeline.py`.

## Task 5: Green Verification And Commit

**Files:**
- All files above.

- [x] Run `/opt/homebrew/bin/uv run pytest tests/test_tushare_daily_batch.py tests/test_cn_daily_selection_pipeline.py tests/test_research_cli.py`.
- [x] Run `/opt/homebrew/bin/uv run pytest`.
- [x] Commit with `feat: add data readiness gate`.

## Task 6: Rolling Screen Research Evaluation

**Files:**
- Create: `src/openstockagent/research/rolling.py`
- Modify: `src/openstockagent/research/models.py`
- Modify: `src/openstockagent/research/storage.py`
- Modify: `src/openstockagent/cli/stock_research.py`
- Test: `tests/test_research_rolling.py`
- Test: `tests/test_research_evaluation.py`
- Test: `tests/test_research_cli.py`

- [x] Add experiment-level models for rolling research runs and per-rebalance-day summaries.
- [x] Add MySQL DDL and upsert/delete helpers for `research_experiment_runs` and `research_experiment_days`.
- [x] Add `run_rolling_screen_evaluation` to compute factors, run screening, evaluate forward returns, and persist a historical experiment.
- [x] Add `stock-research rolling-screen` CLI.
- [x] Add focused tests for rebalance dates, rolling persistence, storage DDL/upserts, and CLI wiring.
- [x] Run `/opt/homebrew/bin/uv run pytest tests/test_research_rolling.py tests/test_research_evaluation.py tests/test_research_cli.py`.
- [x] Run `/opt/homebrew/bin/uv run pytest`.
- [x] Commit with `feat: add rolling screen evaluation`.
