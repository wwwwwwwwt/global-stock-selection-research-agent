# Kronos Stock Agent MVP - Week 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational MVP: project scaffold, Yahoo Finance data feed, SQLite storage, Kronos predictor wrapper, and a CLI that can fetch historical data and predict future candles for a single stock.

**Architecture:** A local-first, zero-LLM-token engine. Kronos (pre-trained financial candlestick foundation model) runs locally for prediction. Yahoo Finance fetches OHLCV data. SQLite stores raw data and predictions. A rule-based supervisor will be added in Week 2.

**Tech Stack:** Python 3.13, uv, yfinance, pandas, torch, transformers (for Kronos), pytest, click (CLI), SQLite

---

## File Structure

```
openstockagent/
├── pyproject.toml                  # uv project config + dependencies
├── README.md                       # Setup and run instructions
├── .python-version                 # 3.13
├── src/
│   └── openstockagent/
│       ├── __init__.py
│       ├── config.py               # Paths, model variant, DB URL
│       ├── data/
│       │   ├── __init__.py
│       │   ├── feeds/
│       │   │   ├── __init__.py
│       │   │   ├── base.py         # BaseDataFeed ABC
│       │   │   └── yahoo.py        # YahooFinanceFeed
│       │   └── storage.py          # SQLite manager
│       └── predictors/
│           ├── __init__.py
│           ├── base.py             # BasePredictor ABC
│           └── kronos_adapter.py   # KronosStockPredictor
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures
│   ├── test_feeds.py
│   ├── test_storage.py
│   └── test_kronos_adapter.py
└── scripts/
    └── run_prediction.py           # CLI entry point
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `src/openstockagent/__init__.py`
- Create: `src/openstockagent/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

---

- [ ] **Step 1: Initialize uv project and install base deps**

```bash
cd /Users/zhangtianwei/IT/openstockagent
uv init --python 3.13
uv add pandas yfinance click pytest
```

Expected: `pyproject.toml` created with `[project]` section and dependencies.

---

- [ ] **Step 2: Create `.python-version`**

```bash
echo "3.13" > .python-version
```

---

- [ ] **Step 3: Write `src/openstockagent/config.py`**

```python
"""Project-wide configuration."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "market.db"
KRONOS_MODEL_VARIANT = "small"  # mini/small/base
KRONOS_DEVICE = "cpu"
KRONOS_PRED_LEN = 5

DATA_DIR.mkdir(exist_ok=True)
```

---

- [ ] **Step 4: Write `tests/conftest.py`**

```python
import pytest
from pathlib import Path
import tempfile


@pytest.fixture
def temp_db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
```

---

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .python-version src/ tests/ README.md
if [ -f uv.lock ]; then git add uv.lock; fi
git commit -m "scaffold: project structure and config"
```

---

## Task 2: DataFeed Layer (Yahoo Finance)

**Files:**
- Create: `src/openstockagent/data/__init__.py`
- Create: `src/openstockagent/data/feeds/__init__.py`
- Create: `src/openstockagent/data/feeds/base.py`
- Create: `src/openstockagent/data/feeds/yahoo.py`
- Create: `tests/test_feeds.py`

---

- [ ] **Step 1: Write failing test for BaseDataFeed interface**

Create `tests/test_feeds.py`:

```python
import pandas as pd
import pytest
from openstockagent.data.feeds.base import BaseDataFeed


class DummyFeed(BaseDataFeed):
    def fetch_ohlcv(self, symbol, period="1y"):
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=3),
            "open": [1.0, 2.0, 3.0],
            "high": [1.5, 2.5, 3.5],
            "low": [0.5, 1.5, 2.5],
            "close": [1.2, 2.2, 3.2],
            "volume": [100, 200, 300],
        }).set_index("date")


def test_base_data_feed_returns_dataframe():
    feed = DummyFeed()
    df = feed.fetch_ohlcv("TEST")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3
```

Run:
```bash
uv run pytest tests/test_feeds.py::test_base_data_feed_returns_dataframe -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'openstockagent'`

---

- [ ] **Step 2: Fix module path and rerun test**

Ensure `pyproject.toml` has:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/openstockagent"]
```

Or if uv used setuptools by default, ensure `src/openstockagent` is importable. Run:
```bash
uv run pytest tests/test_feeds.py::test_base_data_feed_returns_dataframe -v
```
Expected: FAIL — `base.py` not found

---

- [ ] **Step 3: Write `src/openstockagent/data/feeds/base.py`**

```python
from abc import ABC, abstractmethod
import pandas as pd


class BaseDataFeed(ABC):
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        """
        Fetch OHLCV data.

        Returns DataFrame with columns: [open, high, low, close, volume]
        Index: datetime (business days)
        """
        ...
```

Run test again. Expected: PASS

---

- [ ] **Step 4: Write failing test for YahooFinanceFeed**

Add to `tests/test_feeds.py`:

```python
from openstockagent.data.feeds.yahoo import YahooFinanceFeed


def test_yahoo_fetch_aapl():
    feed = YahooFinanceFeed()
    df = feed.fetch_ohlcv("AAPL", period="3mo")
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 30
    required = {"open", "high", "low", "close", "volume"}
    assert required.issubset(set(df.columns))
    assert df.index.dtype == "datetime64[ns, UTC]" or str(df.index.dtype).startswith("datetime64")
```

Run:
```bash
uv run pytest tests/test_feeds.py::test_yahoo_fetch_aapl -v
```
Expected: FAIL — `yahoo.py` not found

---

- [ ] **Step 5: Write `src/openstockagent/data/feeds/yahoo.py`**

```python
import yfinance as yf
import pandas as pd
from .base import BaseDataFeed


class YahooFinanceFeed(BaseDataFeed):
    def fetch_ohlcv(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df.empty:
            raise ValueError(f"No data returned for {symbol}")

        # Standardize columns
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })
        df = df[["open", "high", "low", "close", "volume"]]
        df.index = df.index.tz_localize(None)  # Remove timezone for simplicity
        return df
```

Run test. Expected: PASS (requires network). If network is unavailable, mark skip.

---

- [ ] **Step 6: Commit**

```bash
git add src/openstockagent/data/ tests/test_feeds.py
git commit -m "feat: add Yahoo Finance data feed with tests"
```

---

## Task 3: SQLite Storage

**Files:**
- Create: `src/openstockagent/data/storage.py`
- Create: `tests/test_storage.py`

---

- [ ] **Step 1: Write failing test for storage**

Create `tests/test_storage.py`:

```python
import pandas as pd
from openstockagent.data.storage import SQLiteStorage


def test_save_and_load_ohlcv(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    df = pd.DataFrame({
        "open": [1.0, 2.0],
        "high": [1.5, 2.5],
        "low": [0.5, 1.5],
        "close": [1.2, 2.2],
        "volume": [100, 200],
    }, index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    df.index.name = "date"

    storage.save_ohlcv("TEST", df)
    loaded = storage.load_ohlcv("TEST")

    assert len(loaded) == 2
    assert loaded["close"].iloc[-1] == 2.2
```

Run:
```bash
uv run pytest tests/test_storage.py -v
```
Expected: FAIL — `storage.py` not found

---

- [ ] **Step 2: Write `src/openstockagent/data/storage.py`**

```python
import sqlite3
import pandas as pd
from pathlib import Path


class SQLiteStorage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    PRIMARY KEY (symbol, date)
                )
            """)

    def save_ohlcv(self, symbol: str, df: pd.DataFrame):
        df = df.copy()
        df["symbol"] = symbol
        df = df.reset_index()
        if "date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "date"})

        with sqlite3.connect(self.db_path) as conn:
            df[["symbol", "date", "open", "high", "low", "close", "volume"]].to_sql(
                "ohlcv", conn, if_exists="append", index=False
            )

    def load_ohlcv(self, symbol: str) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                "SELECT date, open, high, low, close, volume FROM ohlcv WHERE symbol = ? ORDER BY date",
                conn, params=(symbol,), parse_dates=["date"]
            )
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return df.set_index("date")
```

Run test. Expected: PASS

---

- [ ] **Step 3: Commit**

```bash
git add src/openstockagent/data/storage.py tests/test_storage.py
git commit -m "feat: add SQLite storage for OHLCV data"
```

---

## Task 4: Kronos Predictor Adapter

**Files:**
- Create: `src/openstockagent/predictors/__init__.py`
- Create: `src/openstockagent/predictors/base.py`
- Create: `src/openstockagent/predictors/kronos_adapter.py`
- Create: `tests/test_kronos_adapter.py`

---

- [ ] **Step 1: Clone Kronos repo locally (vendor)**

```bash
mkdir -p vendor
cd vendor
git clone --depth 1 https://github.com/shiyu-coder/Kronos.git
```

Expected: `vendor/Kronos/` directory created.

---

- [ ] **Step 2: Install Kronos dependencies**

Check `vendor/Kronos/requirements.txt` and add to project:

```bash
cd /Users/zhangtianwei/IT/openstockagent
# Add torch CPU and transformers
cat vendor/Kronos/requirements.txt >> requirements-kronos.txt
uv add torch --index-strategy unsafe-best-match
# Manually add other deps from Kronos requirements if needed
```

Note: Kronos may need specific packages. Inspect `vendor/Kronos/requirements.txt` first.

If Kronos is installable as editable:
```bash
uv pip install -e vendor/Kronos
```

But uv init uses its own venv. We may need to add a dependency line in pyproject.toml:
```toml
dependencies = [
    ...
    "torch",
    "transformers",
    "kronos @ file:///${PROJECT_ROOT}/vendor/Kronos",
]
```

Or simpler: add `vendor/Kronos` to PYTHONPATH and import directly.

---

- [ ] **Step 3: Write `src/openstockagent/predictors/base.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
import pandas as pd
import numpy as np
from typing import Optional


@dataclass
class PredictionResult:
    symbol: str
    model_name: str
    horizon: int
    forecast: pd.DataFrame  # Future OHLCV
    confidence: float       # 0.0 - 1.0
    metadata: dict


class BasePredictor(ABC):
    @abstractmethod
    def predict(self, symbol: str, df: pd.DataFrame, horizon: int = 5) -> PredictionResult:
        ...
```

---

- [ ] **Step 4: Write failing test for Kronos adapter**

Create `tests/test_kronos_adapter.py`:

```python
import pytest
import pandas as pd
import numpy as np
from openstockagent.predictors.kronos_adapter import KronosStockPredictor


@pytest.fixture
def sample_ohlcv():
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    return pd.DataFrame({
        "open": 100 + np.random.randn(60).cumsum(),
        "high": 101 + np.random.randn(60).cumsum(),
        "low": 99 + np.random.randn(60).cumsum(),
        "close": 100 + np.random.randn(60).cumsum(),
        "volume": np.random.randint(1000, 10000, 60),
    }, index=dates)


def test_kronos_predict_shape(sample_ohlcv):
    predictor = KronosStockPredictor(variant="mini", device="cpu")
    result = predictor.predict("TEST", sample_ohlcv, horizon=5)

    assert result.symbol == "TEST"
    assert result.horizon == 5
    assert len(result.forecast) == 5
    assert set(result.forecast.columns) == {"open", "high", "low", "close", "volume"}
    assert 0.0 <= result.confidence <= 1.0
```

Run:
```bash
uv run pytest tests/test_kronos_adapter.py::test_kronos_predict_shape -v
```
Expected: FAIL — `kronos_adapter.py` not found or Kronos import error

---

- [ ] **Step 5: Write `src/openstockagent/predictors/kronos_adapter.py`**

```python
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import torch

# Add vendor Kronos to path
KRONOS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "vendor" / "Kronos"
if str(KRONOS_ROOT) not in sys.path:
    sys.path.insert(0, str(KRONOS_ROOT))

from model import Kronos, KronosTokenizer, KronosPredictor as _KronosPredictor

from .base import BasePredictor, PredictionResult


class KronosStockPredictor(BasePredictor):
    MODELS = {
        "mini": "NeoQuasar/Kronos-mini",
        "small": "NeoQuasar/Kronos-small",
        "base": "NeoQuasar/Kronos-base",
    }

    def __init__(self, variant: str = "small", device: str = "cpu"):
        self.variant = variant
        self.device = device
        model_id = self.MODELS[variant]

        tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        model = Kronos.from_pretrained(model_id)

        self.predictor = _KronosPredictor(model, tokenizer, max_context=512)

    def predict(self, symbol: str, df: pd.DataFrame, horizon: int = 5) -> PredictionResult:
        # Kronos expects specific column order
        required = ["open", "high", "low", "close", "volume"]
        input_df = df[required].copy()

        future_dates = pd.date_range(
            start=df.index[-1] + pd.Timedelta(days=1),
            periods=horizon,
            freq="B"
        )

        pred_df = self.predictor.predict(
            df=input_df,
            x_timestamp=df.index,
            y_timestamp=future_dates,
            pred_len=horizon,
            T=1.0,
            top_p=0.9,
            sample_count=5,
        )

        # Confidence: based on forecast stability across samples
        # For now, use a heuristic based on predicted close range vs last close
        last_close = df["close"].iloc[-1]
        pred_close_range = pred_df["close"].max() - pred_df["close"].min()
        confidence = float(np.clip(1.0 - (pred_close_range / (last_close + 1e-8)), 0.0, 1.0))

        return PredictionResult(
            symbol=symbol,
            model_name=f"kronos-{self.variant}",
            horizon=horizon,
            forecast=pred_df,
            confidence=confidence,
            metadata={
                "last_close": float(last_close),
                "device": self.device,
            }
        )
```

Run test. Expected: PASS (may take time for first model download).

---

- [ ] **Step 6: Commit**

```bash
git add vendor/ src/openstockagent/predictors/ tests/test_kronos_adapter.py
git commit -m "feat: add Kronos predictor adapter"
```

---

## Task 5: CLI Integration

**Files:**
- Create: `scripts/run_prediction.py`
- Modify: `pyproject.toml` (add script entry point)

---

- [ ] **Step 1: Write `scripts/run_prediction.py`**

```python
#!/usr/bin/env python3
"""CLI to fetch data and run Kronos prediction for a single stock."""
import click
from openstockagent.config import DB_PATH, KRONOS_PRED_LEN
from openstockagent.data.feeds.yahoo import YahooFinanceFeed
from openstockagent.data.storage import SQLiteStorage
from openstockagent.predictors.kronos_adapter import KronosStockPredictor


@click.command()
@click.argument("symbol")
@click.option("--period", default="6mo", help="Historical data period (e.g. 3mo, 1y)")
@click.option("--horizon", default=KRONOS_PRED_LEN, help="Prediction horizon (candles)")
@click.option("--model", default="small", help="Kronos variant: mini/small/base")
def main(symbol: str, period: str, horizon: int, model: str):
    click.echo(f"Fetching {period} data for {symbol}...")
    feed = YahooFinanceFeed()
    df = feed.fetch_ohlcv(symbol, period=period)
    click.echo(f"Loaded {len(df)} rows from {df.index[0].date()} to {df.index[-1].date()}")

    storage = SQLiteStorage(DB_PATH)
    storage.save_ohlcv(symbol, df)
    click.echo(f"Saved to {DB_PATH}")

    click.echo(f"Loading Kronos ({model})...")
    predictor = KronosStockPredictor(variant=model, device="cpu")

    click.echo(f"Predicting next {horizon} candles...")
    result = predictor.predict(symbol, df, horizon=horizon)

    click.echo("\n--- Prediction Result ---")
    click.echo(f"Model: {result.model_name}")
    click.echo(f"Confidence: {result.confidence:.4f}")
    click.echo(f"\nForecast:\n{result.forecast.to_string()}")


if __name__ == "__main__":
    main()
```

---

- [ ] **Step 2: Add entry point to `pyproject.toml`**

```toml
[project.scripts]
stock-predict = "scripts.run_prediction:main"
```

---

- [ ] **Step 3: Run CLI manually**

```bash
uv run python scripts/run_prediction.py AAPL --period 3mo --model mini
```

Expected: Fetches AAPL data, saves to SQLite, loads Kronos-mini, outputs 5-row prediction DataFrame.

---

- [ ] **Step 4: Commit**

```bash
git add scripts/ pyproject.toml
git commit -m "feat: add CLI for single-stock prediction"
```

---

## Self-Review Checklist

- [ ] **Spec coverage:** Week 1 MVP = project scaffold + data feed + storage + Kronos wrapper + CLI. All covered.
- [ ] **Placeholder scan:** No TBDs, all code blocks contain real code.
- [ ] **Type consistency:** `fetch_ohlcv` returns `pd.DataFrame` everywhere. `predict` returns `PredictionResult` everywhere.
- [ ] **Testability:** Each module has a test file. Kronos test may be slow due to model download; acceptable for integration test.
- [ ] **Python 3.13 compatibility:** yfinance, pandas, torch all support 3.13. Kronos code uses standard PyTorch/transformers APIs, should be compatible.

---

## Execution Handoff

**Plan complete.** Two execution options:

1. **Subagent-Driven (recommended)** - Fresh subagent per task, review between tasks
2. **Inline Execution** - Execute tasks sequentially in this session

**Recommended:** Inline for Week 1 since tasks are tightly coupled (scaffold → feed → storage → Kronos → CLI).
