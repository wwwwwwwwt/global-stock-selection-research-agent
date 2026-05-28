# Portfolio Rebalance MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make portfolio decisions aware of current holdings so the system can output buy/add/hold/reduce/sell instead of only new allocations.

**Architecture:** Extend `PortfolioPosition` storage with a loader, pass current positions into `build_portfolio_decision()`, and classify each target allocation relative to current weight. Keep this as a deterministic MVP: no order execution, no tax lots, no broker integration, and no intraday fills.

**Tech Stack:** Python 3.13, Click CLI, existing MySQL portfolio tables and existing recommendation/entry layers.

---

## File Structure

- Modify `src/openstockagent/portfolio/decision.py`: add current-position aware rebalance action classification.
- Modify `src/openstockagent/portfolio/storage.py`: add `load_positions(account_id)`.
- Modify `src/openstockagent/cli/run_portfolio.py`: load positions and pass them into decision builder.
- Modify `src/openstockagent/pipelines/cn_daily_selection.py`: load positions when portfolio storage supports it.
- Modify `tests/test_portfolio.py`: cover hold/add/reduce/sell and storage loading.
- Modify `tests/test_portfolio_cli.py`: cover CLI passes existing positions.
- Modify `tests/test_cn_daily_selection_pipeline.py`: cover pipeline passes existing positions.

## Task 1: Position-Aware Decision Logic

**Files:**
- Modify: `src/openstockagent/portfolio/decision.py`
- Test: `tests/test_portfolio.py`

- [ ] Add optional `current_positions: list[PortfolioPosition] | None = None`.
- [ ] Compute current weight from `position.market_value / capital`.
- [ ] For selected target names:
  - no current position -> `buy`
  - current weight less than target by tolerance -> `add`
  - current weight close to target -> `hold`
  - current weight greater than target by tolerance -> `reduce`
- [ ] For current positions not selected:
  - risk regime blocks exposure -> `sell`
  - otherwise -> `reduce`
- [ ] Include current weight and target weight in `reason_json`.

## Task 2: Storage Loader

**Files:**
- Modify: `src/openstockagent/portfolio/storage.py`
- Test: `tests/test_portfolio.py`

- [ ] Add `load_positions(account_id: str) -> list[PortfolioPosition]`.
- [ ] Return positions ordered by market value descending.

## Task 3: CLI and CN Pipeline

**Files:**
- Modify: `src/openstockagent/cli/run_portfolio.py`
- Modify: `src/openstockagent/pipelines/cn_daily_selection.py`
- Test: `tests/test_portfolio_cli.py`
- Test: `tests/test_cn_daily_selection_pipeline.py`

- [ ] `stock-portfolio decide` should load current positions for the account and pass them to decision builder.
- [ ] CN daily selection pipeline should do the same when portfolio storage has `load_positions`.

## Task 4: Verification

Run:

```bash
uv run pytest tests/test_portfolio.py tests/test_portfolio_cli.py tests/test_cn_daily_selection_pipeline.py
uv run pytest
git diff --check
```
