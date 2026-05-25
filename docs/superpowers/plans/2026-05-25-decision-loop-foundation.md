# Decision Loop Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land phases 1-4 of the stock-selection decision loop: market reality data, automatic recommendation reviews, horizon-specific strategy versions, and portfolio-level empty-position decisions.

**Architecture:** Add a `market` package for trading calendars, instrument status, and corporate actions. Extend recommendations with automated due-review processing and horizon presets. Add a `portfolio` package that converts actionable recommendations into portfolio decisions with gross exposure, cash, per-name weights, and skip/empty states.

**Tech Stack:** Python 3.13, dataclasses, pandas, Click, PyMySQL, pytest, existing MySQL storage patterns.

---

## Tasks

### Task 1: Market Reality Layer

**Files:**
- Create `src/openstockagent/market/models.py`
- Create `src/openstockagent/market/storage.py`
- Create `src/openstockagent/market/calendar.py`
- Create `tests/test_market_reality.py`

- [ ] Add `TradingCalendarDay`, `InstrumentStatus`, and `CorporateAction`.
- [ ] Add MySQL tables `trading_calendar`, `instrument_status`, and `corporate_actions`.
- [ ] Add calendar helpers that can use stored trading days and fall back to business days.

### Task 2: Automatic Recommendation Reviews

**Files:**
- Modify `src/openstockagent/recommendations/storage.py`
- Modify `src/openstockagent/recommendations/runner.py`
- Modify `src/openstockagent/cli/run_recommendations.py`
- Modify `tests/test_recommendations.py`
- Modify `tests/test_recommendations_cli.py`

- [ ] Add loaders for due recommendation items and existing review checks.
- [ ] Add `run_due_recommendation_reviews()` to compute entry/review prices from canonical bars.
- [ ] Add `stock-recommend review-due --as-of ...`.

### Task 3: Horizon Strategy Presets

**Files:**
- Modify `src/openstockagent/recommendations/runner.py`
- Modify `src/openstockagent/cli/run_recommendations.py`
- Modify `tests/test_recommendations.py`

- [ ] Add horizon presets for `1d`, `5d`, `20d`, and `60d`.
- [ ] Default strategy name/version from horizon.
- [ ] Keep user thresholds overridable from CLI.

### Task 4: Portfolio Decision Layer

**Files:**
- Create `src/openstockagent/portfolio/models.py`
- Create `src/openstockagent/portfolio/storage.py`
- Create `src/openstockagent/portfolio/decision.py`
- Create `src/openstockagent/cli/run_portfolio.py`
- Create `tests/test_portfolio.py`
- Create `tests/test_portfolio_cli.py`
- Modify `pyproject.toml`

- [ ] Add portfolio account, policy, position, decision, and target allocation models.
- [ ] Add MySQL tables and storage.
- [ ] Build decisions from recommendation items with market-regime exposure caps and no-signal/data-bad empty states.
- [ ] Add `stock-portfolio decide`.

### Task 5: Docs, Verification, Commit

**Files:**
- Modify `README.md`

- [ ] Document the new layers and commands.
- [ ] Run `uv run pytest tests`.
- [ ] Run `uv run python -m compileall -q src/openstockagent scripts tests`.
- [ ] Run `git diff --check`.
- [ ] Commit and push with a normal message.

