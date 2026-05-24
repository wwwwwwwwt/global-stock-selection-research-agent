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

# Run tests
uv run pytest tests/ -v
```

## Current Architecture

The current codebase contains the Week 1 foundation:

```text
src/openstockagent/
├── data/
│   ├── feeds/            # Data adapters, currently Yahoo Finance
│   └── storage.py        # SQLite persistence
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
- [x] Yahoo Finance data feed
- [x] SQLite OHLCV storage
- [x] Kronos adapter and experimental CLI
- [x] Global-aware stock selection architecture docs
- [ ] Canonical market data core
- [ ] Universe management
- [ ] Factor engine MVP
- [ ] Screening and ranking MVP
- [ ] Global market context MVP
- [ ] News and event ingestion MVP
- [ ] Classic theory engine, starting with Chan theory MVP
- [ ] Evidence-grounded selection reports
- [ ] Backtest harness
