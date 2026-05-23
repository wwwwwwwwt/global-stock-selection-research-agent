# OpenStockAgent

Local-first stock monitoring agent with Kronos candlestick prediction.

## Quick Start

```bash
# Install dependencies
uv sync

# Run prediction for a single stock
uv run python scripts/run_prediction.py AAPL --period 3mo --model mini

# Run tests
uv run pytest tests/ -v
```

## Architecture

```
src/openstockagent/
├── data/
│   ├── feeds/           # Data adapters (Yahoo Finance)
│   └── storage.py       # SQLite persistence
├── predictors/
│   ├── base.py          # Predictor interface
│   └── kronos_adapter.py # Kronos integration
└── config.py            # Project settings
```

## Kronos Model Setup

Due to network restrictions, the project currently includes a **stub** `vendor/Kronos/model.py` that simulates predictions with realistic-looking random-walk behavior.

To use the **real Kronos model**:

```bash
rm -rf vendor/Kronos
git clone --depth 1 https://github.com/shiyu-coder/Kronos.git vendor/Kronos
```

The adapter (`kronos_adapter.py`) will automatically pick up the real implementation since it imports from `vendor/Kronos/model.py`.

## Week 1 MVP Status

- [x] Project scaffold (uv, pytest, config)
- [x] Yahoo Finance data feed
- [x] SQLite storage
- [x] Kronos predictor adapter (stub)
- [x] CLI entry point
- [ ] Real Kronos model (requires `git clone`)
- [ ] Technical analysis engine (Week 2)
- [ ] Rule-based supervisor (Week 2)
- [ ] Streamlit frontend (Week 3)
- [ ] Scheduled execution (Week 3)
- [ ] Feishu/DingTalk notifications (Week 4)
