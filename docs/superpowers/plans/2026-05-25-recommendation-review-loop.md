# Recommendation Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a recommendation and review layer after screening so OpenStockAgent can produce horizon-aware candidates and record later review outcomes.

**Architecture:** Keep `screen_results` immutable and treat them as research evidence. Add a separate `recommendations` package with models, MySQL storage, a runner that converts selected screen results into recommendation items, and a CLI for creating recommendation runs and manual review records. Portfolio sizing remains a later layer.

**Tech Stack:** Python 3.13, dataclasses, pandas business-day offsets, Click, PyMySQL, pytest.

---

## File Map

- Create `src/openstockagent/recommendations/models.py`: dataclasses for recommendation runs, items, and reviews.
- Create `src/openstockagent/recommendations/storage.py`: MySQL DDL and persistence methods.
- Create `src/openstockagent/recommendations/runner.py`: policy logic that converts screen results to horizon recommendations.
- Create `src/openstockagent/cli/run_recommendations.py`: `stock-recommend from-screen` and `stock-recommend add-review`.
- Modify `pyproject.toml`: expose `stock-recommend`.
- Modify `README.md`: document recommendation commands.
- Create `tests/test_recommendations.py`: model, runner, storage, and review calculations.
- Create `tests/test_recommendations_cli.py`: CLI wiring.

## Tasks

### Task 1: Recommendation Models

**Files:**
- Create: `src/openstockagent/recommendations/__init__.py`
- Create: `src/openstockagent/recommendations/models.py`
- Test: `tests/test_recommendations.py`

- [ ] Add frozen dataclasses `RecommendationRun`, `RecommendationItem`, and `RecommendationReview`.
- [ ] Implement `to_record()` methods that map Python field names to SQL field names only where needed.
- [ ] Verify JSON fields stay strings so storage does not silently mutate historical recommendation evidence.

### Task 2: MySQL Storage

**Files:**
- Create: `src/openstockagent/recommendations/storage.py`
- Test: `tests/test_recommendations.py`

- [ ] Add DDL for `recommendation_runs`, `recommendation_items`, and `recommendation_reviews`.
- [ ] Add `MySQLRecommendationStorage.ensure_tables()`.
- [ ] Add upsert/load methods for runs, items, and reviews.
- [ ] Keep recommendation items immutable by default at the workflow level: runner deletes/replaces only within the same `recommendation_run_id`.

### Task 3: Runner

**Files:**
- Create: `src/openstockagent/recommendations/runner.py`
- Test: `tests/test_recommendations.py`

- [ ] Add horizon parsing for `1d`, `5d`, `20d`, and `60d`.
- [ ] Compute `review_due_date` with business-day offsets until a real trading calendar exists.
- [ ] Convert selected screen results into actions:
  - `buy_candidate` when score >= buy threshold.
  - `watch` when score >= watch threshold.
  - `skip` otherwise.
- [ ] Create structured thesis, confirmation, invalidation, risk, and evidence JSON from screen result JSON.
- [ ] Add review metric calculation for manual review records.

### Task 4: CLI

**Files:**
- Create: `src/openstockagent/cli/run_recommendations.py`
- Modify: `pyproject.toml`
- Test: `tests/test_recommendations_cli.py`

- [ ] Add `stock-recommend from-screen SCREEN_RUN_ID --universe-id ... --as-of ... --horizon 5d`.
- [ ] Add `stock-recommend add-review RECOMMENDATION_ID --review-date ...`.
- [ ] Print run status, item counts, and selected actions.

### Task 5: Docs And Verification

**Files:**
- Modify: `README.md`

- [ ] Document the new recommendation commands.
- [ ] Run `uv run pytest tests`.
- [ ] Run `uv run python -m compileall -q src/openstockagent scripts tests`.
- [ ] Run `git diff --check`.
- [ ] Commit with a normal human-authored message.

