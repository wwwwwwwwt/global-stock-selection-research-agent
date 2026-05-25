# OpenStockAgent

Global-aware quantitative stock selection research agent.

OpenStockAgent is being built as a local-first research system for selecting stock candidates from a universe, not as a one-symbol forecasting utility. It combines canonical market data, factor scoring, classic technical theory structures, global market context, international news events, and evidence-grounded LLM explanations.

## Product Flow

```text
Market Reality -> Universe -> Data -> Factors -> Screening -> Recommendation -> Portfolio Decision -> Review
```

The system should answer:

- Which stocks are worth watching today?
- Why did each candidate enter the list?
- Which factors, theory structures, market conditions, and news events support the selection?
- What risks or invalidation conditions should be monitored next?

## Quick Start

```bash
# Install dependencies
uv sync

# Run current experimental single-stock Kronos utility
uv run python scripts/run_prediction.py AAPL --period 3mo --model mini

# Migrate legacy local SQLite market data into MySQL once
uv run migrate-sqlite-market-data --sqlite-path data/market.db

# Run real-data factors and stock screening against MySQL
uv run stock-factors us_sample --as-of 2026-05-22 --period 1y
uv run stock-screen us_sample --as-of 2026-05-22 --top-n 10
uv run stock-recommend from-screen screen-run-id --universe-id us_sample --as-of 2026-05-22 --horizon 5d
uv run stock-recommend review-due --as-of 2026-05-29
uv run stock-portfolio decide rec-run-id --account-id paper --capital 100000 --decision-date 2026-05-22 --market-regime neutral

# Build core stock universes
uv run stock-universe build-core --market CN --as-of 2026-05-25
uv run stock-universe build-core --market US --as-of 2026-05-25

# Backfill 3-5 years of daily bars, then run daily incremental repair
uv run stock-data sync --universe us_core --market US --as-of 2026-05-25 --mode backfill --lookback-years 3
uv run stock-data sync --universe us_core --market US --as-of 2026-05-25 --mode incremental --incremental-days 10

# Run tests
uv run pytest tests/ -v
```

## Current Architecture

The current codebase contains the Week 1 foundation:

```text
src/openstockagent/
├── data/
│   ├── feeds/            # Polygon, AKShare, Yahoo-compatible adapters
│   ├── sqlite_migration.py # One-time legacy SQLite migration
│   ├── sync.py           # Universe-driven backfill and incremental sync
│   ├── sync_storage.py   # MySQL sync plan/run records
│   └── storage.py        # MySQL canonical stock market data storage
├── factors/              # Technical factor engine
├── market/               # Trading calendar, instrument status, corporate actions
├── portfolio/            # Position policy, decisions, and target allocations
├── recommendations/      # Horizon-aware recommendations and review storage
├── screening/            # Screening, ranking, and result storage
├── universe/             # Stock pool models and MySQL storage
├── predictors/
│   ├── base.py           # Predictor interface
│   └── kronos_adapter.py # Kronos adapter, now treated as an optional factor source
└── config.py             # Project settings
```

The target architecture is documented in:

- `docs/superpowers/specs/2026-05-24-global-aware-stock-selection-architecture.md`
- `docs/superpowers/plans/2026-05-24-global-aware-stock-selection-roadmap.md`
- `docs/superpowers/specs/2026-05-23-market-data-source-design.md`
- `docs/superpowers/plans/2026-05-23-market-data-source-implementation.md`

## Target Architecture

```text
External data and news
  -> canonical storage
  -> market reality constraints
  -> stock factors and theory structures
  -> global market context
  -> screening and ranking
  -> horizon recommendations
  -> portfolio decision and review
  -> LLM evidence explanation
```

Kronos remains useful, but it is not the product center. It can contribute optional factors such as direction score, confidence, and forecast volatility.

## Core Universe And Data Sync

The usable-stage stock universe is deliberately not full-market yet:

```text
CN core = CSI 300 + CSI 500 + custom industry leaders
US core = S&P 500 + Nasdaq 100 + custom theme watchlist
HK = deferred
```

Historical bootstrap keeps 3-5 years of daily adjusted bars. Daily operations fetch only a recent repair window, normally 5-10 natural days, and upsert into canonical MySQL `bars`.

Detailed landing doc: [Core Universe And Daily Bar Sync](/Users/zhangtianwei/IT/openstockagent/docs/superpowers/specs/2026-05-25-core-universe-data-sync.md)

```text
stock-universe build-core
  -> universes / universe_members
  -> instruments / instrument_aliases

stock-data sync
  -> data_sync_plans / data_sync_runs
  -> bars
```

## Recommendation And Review Loop

Screening results are research rankings, not direct buy decisions. The recommendation layer adds horizon, action, expected review date, thesis, confirmation conditions, invalidation conditions, and later review metrics. Horizon presets now map to strategy versions:

```text
1d  -> recommendation_1d_momentum:v1
5d  -> recommendation_5d_swing:v1
20d -> recommendation_20d_trend:v1
60d -> recommendation_60d_midterm:v1
```

```text
screen_results
  -> stock-recommend from-screen
  -> recommendation_runs / recommendation_items
  -> stock-recommend review-due or add-review
  -> recommendation_reviews
```

Example:

```bash
uv run stock-recommend from-screen screen-run-id --universe-id us_core --as-of 2026-05-25 --horizon 5d --top-n 10

uv run stock-recommend review-due --as-of 2026-06-01 --benchmark-return 0.02

uv run stock-recommend add-review rec-item-id --review-date 2026-06-01 --entry-price 100 --review-price 106 --benchmark-return 0.02 --thesis-status confirmed
```

This keeps historical `screen_results` immutable. Strategy changes should create new versions and new runs, while review records provide evidence for adjusting factor weights later.

## Market Reality And Portfolio Decisions

The market reality layer stores facts that prevent unrealistic screening and review:

```text
trading_calendar
instrument_status
corporate_actions
```

The portfolio layer converts actionable recommendations into allocation decisions. It can allocate, hold cash, or stay empty when market regime or signal quality is poor.

```bash
uv run stock-portfolio decide rec-run-id --account-id paper --capital 100000 --decision-date 2026-05-25 --market-regime neutral
```

Core decision tables:

```text
portfolio_accounts
portfolio_policies
portfolio_positions
portfolio_decisions
target_allocations
```

## Roadmap

- [x] Project scaffold
- [x] Yahoo Finance-compatible data feed
- [x] MySQL canonical stock market data storage
- [x] Legacy SQLite migration command
- [x] Core stock universe builders for CN/US
- [x] Universe-driven data sync plans and runs
- [x] Kronos adapter and experimental CLI
- [x] Global-aware stock selection architecture docs
- [x] Canonical market data core
- [x] Universe management
- [x] Factor engine MVP
- [x] Screening and ranking MVP
- [x] Recommendation and manual review loop MVP
- [x] Trading calendar, instrument status, and corporate action tables
- [x] Automatic due recommendation review MVP
- [x] Horizon-specific recommendation strategy presets
- [x] Portfolio decision and empty-position MVP
- [ ] Global market context MVP
- [ ] News and event ingestion MVP
- [ ] Classic theory engine, starting with Chan theory MVP
- [ ] Evidence-grounded selection reports
- [ ] Backtest harness
