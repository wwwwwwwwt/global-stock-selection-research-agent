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

## Roadmap

- [x] Project scaffold
- [x] Yahoo Finance-compatible data feed
- [x] MySQL canonical stock market data storage
- [x] Legacy SQLite migration command
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
