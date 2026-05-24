# OpenStockAgent

Global-aware quantitative stock selection research agent.

OpenStockAgent is being built as a local-first research system for selecting stock candidates from a universe, not as a one-symbol forecasting utility. It combines canonical market data, factor scoring, classic technical theory structures, global market context, international news events, and evidence-grounded LLM explanations.

## Product Flow

```text
Universe -> Data -> Factors -> Market Context -> Ranking -> Evidence -> LLM Explanation
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
  -> stock factors and theory structures
  -> global market context
  -> screening and ranking
  -> candidate evidence pack
  -> LLM explanation and daily report
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
- [ ] Global market context MVP
- [ ] News and event ingestion MVP
- [ ] Classic theory engine, starting with Chan theory MVP
- [ ] Evidence-grounded selection reports
- [ ] Backtest harness
