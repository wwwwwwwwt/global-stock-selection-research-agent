# Market Data Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first production-shaped market data core for OpenStockAgent: canonical instruments, multi-period bars, deterministic feeds, Kronos-ready inputs, prediction persistence, technical signals, and an LLM analysis context skeleton.

**Architecture:** External feeds write into canonical local storage; predictors, strategies, and LLM context builders read only canonical data. `bars` remains factual OHLCV data, while predictions, technical indicators, golden/death cross signals, explicit empty sentiment/event sections, and LLM context live in separate layers.

**Tech Stack:** Python 3.13, pandas, sqlite3, pytest, click, existing Kronos adapter.

---

## File Structure

Create and modify these files:

```text
src/openstockagent/data/
  models.py                 # Dataclasses and constants for instruments, bars, prediction runs, signals
  storage.py                # Expand SQLiteStorage into canonical market data storage while keeping old methods
  normalize.py              # Convert provider dataframes into canonical bar dataframes
  validate.py               # Validate OHLCV rows and produce quality issue records
  symbols.py                # Canonical symbol helpers and provider alias helpers
  feeds/
    base.py                 # Add BaseMarketDataFeed while preserving BaseDataFeed compatibility
    csv_feed.py             # Deterministic local feed for tests and regression fixtures
    yahoo.py                # Migrate Yahoo feed to fetch_bars
    registry.py             # Resolve source by instrument/market/interval

src/openstockagent/features/
  __init__.py
  technical.py              # Moving averages, volume z-score, and feature dataframe generation

src/openstockagent/signals/
  __init__.py
  technical.py              # Golden cross and death cross signal generation

src/openstockagent/context/
  __init__.py
  analysis_context.py       # LLM-ready structured context builder

src/openstockagent/pipelines/
  __init__.py
  sync_market_data.py       # Fetch, normalize, validate, and persist bars

scripts/run_prediction.py   # Stop fetching Yahoo directly; read/write via storage pipeline

tests/
  fixtures/sample_bars.csv
  test_data_models.py
  test_market_storage.py
  test_normalize_validate.py
  test_csv_feed.py
  test_feed_registry.py
  test_kronos_storage.py
  test_technical_signals.py
  test_analysis_context.py
```

Do not touch `scripts/benchmark_models.py` unless the user explicitly asks; it is currently an unrelated untracked file.

---

## Task 1: Canonical Data Models

**Files:**
- Create: `src/openstockagent/data/models.py`
- Test: `tests/test_data_models.py`

- [ ] **Step 1: Write failing tests for canonical models**

Create `tests/test_data_models.py`:

```python
from openstockagent.data.models import (
    BAR_COLUMNS,
    INTERVALS,
    Instrument,
    MarketBar,
    TechnicalSignal,
    utc_now_iso,
)


def test_bar_columns_are_kronos_compatible():
    assert BAR_COLUMNS == ["open", "high", "low", "close", "volume", "amount"]


def test_intervals_include_daily_weekly_and_intraday():
    assert {"1m", "5m", "1h", "1d", "1w"}.issubset(INTERVALS)


def test_instrument_id_is_stable():
    instrument = Instrument(
        instrument_id="EQUITY:US:AAPL",
        symbol="AAPL",
        market="US",
        exchange="NASDAQ",
        asset_type="equity",
        currency="USD",
        name="Apple Inc.",
        timezone="America/New_York",
    )
    assert instrument.instrument_id == "EQUITY:US:AAPL"
    assert instrument.market == "US"


def test_market_bar_to_record_has_required_fields():
    bar = MarketBar(
        instrument_id="EQUITY:US:AAPL",
        timestamp="2024-01-02T21:00:00Z",
        local_date="2024-01-02",
        interval="1d",
        source="csv",
        adjustment="split_adjusted",
        open=100.0,
        high=103.0,
        low=99.0,
        close=102.0,
        volume=1000.0,
        amount=101000.0,
        currency="USD",
    )
    record = bar.to_record()
    assert record["instrument_id"] == "EQUITY:US:AAPL"
    assert record["close"] == 102.0
    assert record["is_complete"] == 1


def test_technical_signal_requires_evidence():
    signal = TechnicalSignal(
        signal_id="sig_1",
        instrument_id="EQUITY:US:AAPL",
        timestamp="2024-01-10T21:00:00Z",
        interval="1d",
        signal_type="golden_cross",
        direction="bullish",
        strength=0.8,
        confidence=0.7,
        severity="watch",
        summary="MA5 crossed above MA20.",
        evidence_json='{"fast_ma": "ma_close_5"}',
        input_range_start="2023-12-01T21:00:00Z",
        input_range_end="2024-01-10T21:00:00Z",
    )
    assert signal.signal_type == "golden_cross"
    assert signal.evidence_json.startswith("{")


def test_utc_now_iso_is_sortable():
    value = utc_now_iso()
    assert value.endswith("Z")
    assert "T" in value
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_data_models.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `openstockagent.data.models`.

- [ ] **Step 3: Create canonical model file**

Create `src/openstockagent/data/models.py`:

```python
"""Canonical data models used by feeds, storage, predictors, and analysis context."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


BAR_COLUMNS = ["open", "high", "low", "close", "volume", "amount"]
PRICE_COLUMNS = ["open", "high", "low", "close"]
INTERVALS = {"1m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo"}
ADJUSTMENTS = {"raw", "split_adjusted", "total_return_adjusted"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    symbol: str
    market: str
    exchange: str | None
    asset_type: str
    currency: str | None
    name: str | None
    timezone: str | None
    active: bool = True
    metadata_json: str | None = None

    def to_record(self) -> dict:
        record = asdict(self)
        record["active"] = 1 if self.active else 0
        return record


@dataclass(frozen=True)
class InstrumentAlias:
    instrument_id: str
    source: str
    source_symbol: str
    priority: int = 1

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MarketBar:
    instrument_id: str
    timestamp: str
    local_date: str
    interval: str
    source: str
    adjustment: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None
    currency: str | None = None
    is_complete: bool = True
    provider_payload_hash: str | None = None

    def to_record(self) -> dict:
        record = asdict(self)
        record["is_complete"] = 1 if self.is_complete else 0
        return record


@dataclass(frozen=True)
class PredictionRun:
    run_id: str
    model_name: str
    model_variant: str
    instrument_id: str
    interval: str
    lookback_start: str
    lookback_end: str
    horizon: int
    source_selection_json: str
    metadata_json: str | None = None

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TechnicalSignal:
    signal_id: str
    instrument_id: str
    timestamp: str
    interval: str
    signal_type: str
    direction: str
    strength: float
    confidence: float | None
    severity: str
    summary: str
    evidence_json: str
    input_range_start: str
    input_range_end: str
    created_at: str = field(default_factory=utc_now_iso)

    def to_record(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_data_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openstockagent/data/models.py tests/test_data_models.py
git commit -m "feat: add canonical market data models"
```

---

## Task 2: Canonical SQLite Storage

**Files:**
- Modify: `src/openstockagent/data/storage.py`
- Test: `tests/test_market_storage.py`
- Keep: existing `tests/test_storage.py` should still pass.

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_market_storage.py`:

```python
import json

import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias, PredictionRun, TechnicalSignal
from openstockagent.data.storage import SQLiteStorage


def test_upsert_instrument_and_alias(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    instrument = Instrument(
        instrument_id="EQUITY:US:AAPL",
        symbol="AAPL",
        market="US",
        exchange="NASDAQ",
        asset_type="equity",
        currency="USD",
        name="Apple Inc.",
        timezone="America/New_York",
    )
    alias = InstrumentAlias("EQUITY:US:AAPL", "yahoo", "AAPL")

    storage.upsert_instrument(instrument)
    storage.upsert_instrument_alias(alias)

    assert storage.resolve_alias("yahoo", "AAPL") == "EQUITY:US:AAPL"


def test_upsert_and_load_bars(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    df = pd.DataFrame(
        {
            "instrument_id": ["EQUITY:US:AAPL", "EQUITY:US:AAPL"],
            "timestamp": ["2024-01-02T21:00:00Z", "2024-01-03T21:00:00Z"],
            "local_date": ["2024-01-02", "2024-01-03"],
            "interval": ["1d", "1d"],
            "source": ["csv", "csv"],
            "adjustment": ["split_adjusted", "split_adjusted"],
            "open": [100.0, 102.0],
            "high": [103.0, 104.0],
            "low": [99.0, 101.0],
            "close": [102.0, 103.5],
            "volume": [1000.0, 1200.0],
            "amount": [101000.0, 123000.0],
            "currency": ["USD", "USD"],
            "is_complete": [1, 1],
        }
    )

    assert storage.upsert_bars(df) == 2
    assert storage.upsert_bars(df) == 2

    loaded = storage.load_bars("EQUITY:US:AAPL", "1d", "2024-01-01T00:00:00Z", "2024-01-04T00:00:00Z")
    assert list(loaded["close"]) == [102.0, 103.5]
    assert loaded.iloc[0]["source"] == "csv"


def test_save_prediction_run_and_predicted_bars(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    run = PredictionRun(
        run_id="pred_1",
        model_name="kronos",
        model_variant="small",
        instrument_id="EQUITY:US:AAPL",
        interval="1d",
        lookback_start="2024-01-01T21:00:00Z",
        lookback_end="2024-01-31T21:00:00Z",
        horizon=2,
        source_selection_json=json.dumps({"source": "csv"}),
    )
    predicted = pd.DataFrame(
        {
            "forecast_timestamp": ["2024-02-01T21:00:00Z", "2024-02-02T21:00:00Z"],
            "step": [1, 2],
            "open": [104.0, 105.0],
            "high": [106.0, 107.0],
            "low": [103.0, 104.0],
            "close": [105.5, 106.5],
            "volume": [1300.0, 1400.0],
            "amount": [136500.0, 149100.0],
            "confidence": [0.7, 0.68],
        }
    )

    storage.save_prediction_run(run, predicted)
    loaded = storage.load_latest_prediction_summary("EQUITY:US:AAPL", "1d")
    assert loaded["run_id"] == "pred_1"
    assert loaded["horizon"] == 2
    assert loaded["forecast_close_max"] == 106.5


def test_save_technical_signal(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    signal = TechnicalSignal(
        signal_id="sig_1",
        instrument_id="EQUITY:US:AAPL",
        timestamp="2024-01-31T21:00:00Z",
        interval="1d",
        signal_type="golden_cross",
        direction="bullish",
        strength=0.75,
        confidence=0.8,
        severity="watch",
        summary="MA5 crossed above MA20.",
        evidence_json='{"fast": 101.0, "slow": 100.0}',
        input_range_start="2024-01-01T21:00:00Z",
        input_range_end="2024-01-31T21:00:00Z",
    )

    assert storage.save_technical_signals([signal]) == 1
    loaded = storage.load_recent_technical_signals("EQUITY:US:AAPL", "1d", limit=5)
    assert loaded[0]["signal_type"] == "golden_cross"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_market_storage.py -q
```

Expected: FAIL because new storage methods do not exist.

- [ ] **Step 3: Expand `SQLiteStorage._ensure_tables`**

Modify `src/openstockagent/data/storage.py` imports:

```python
import json
import sqlite3
from pathlib import Path

import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias, PredictionRun, TechnicalSignal, utc_now_iso
```

Inside `_ensure_tables`, keep the existing `ohlcv` table and add these `CREATE TABLE IF NOT EXISTS` statements:

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS instruments (
        instrument_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        market TEXT NOT NULL,
        exchange TEXT,
        asset_type TEXT NOT NULL,
        currency TEXT,
        name TEXT,
        timezone TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS instrument_aliases (
        instrument_id TEXT NOT NULL,
        source TEXT NOT NULL,
        source_symbol TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        UNIQUE(source, source_symbol)
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS bars (
        instrument_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        local_date TEXT NOT NULL,
        interval TEXT NOT NULL,
        source TEXT NOT NULL,
        adjustment TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL,
        amount REAL,
        currency TEXT,
        is_complete INTEGER NOT NULL DEFAULT 1,
        provider_payload_hash TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(instrument_id, interval, timestamp, source, adjustment)
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS feed_runs (
        run_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        purpose TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT NOT NULL,
        requested_symbols_json TEXT,
        requested_interval TEXT,
        requested_start TEXT,
        requested_end TEXT,
        rows_fetched INTEGER DEFAULT 0,
        rows_inserted INTEGER DEFAULT 0,
        rows_updated INTEGER DEFAULT 0,
        error_message TEXT,
        metadata_json TEXT
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS data_quality_issues (
        issue_id TEXT PRIMARY KEY,
        run_id TEXT,
        instrument_id TEXT,
        interval TEXT,
        timestamp TEXT,
        severity TEXT NOT NULL,
        issue_type TEXT NOT NULL,
        details_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS prediction_runs (
        run_id TEXT PRIMARY KEY,
        model_name TEXT NOT NULL,
        model_variant TEXT NOT NULL,
        instrument_id TEXT NOT NULL,
        interval TEXT NOT NULL,
        lookback_start TEXT NOT NULL,
        lookback_end TEXT NOT NULL,
        horizon INTEGER NOT NULL,
        source_selection_json TEXT NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS predicted_bars (
        run_id TEXT NOT NULL,
        forecast_timestamp TEXT NOT NULL,
        step INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL,
        amount REAL,
        confidence REAL,
        created_at TEXT NOT NULL,
        UNIQUE(run_id, forecast_timestamp)
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS technical_features (
        instrument_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        interval TEXT NOT NULL,
        feature_name TEXT NOT NULL,
        feature_value REAL,
        window TEXT,
        params_json TEXT,
        input_range_start TEXT NOT NULL,
        input_range_end TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(instrument_id, interval, timestamp, feature_name, params_json)
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS technical_signals (
        signal_id TEXT PRIMARY KEY,
        instrument_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        interval TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        direction TEXT NOT NULL,
        strength REAL NOT NULL,
        confidence REAL,
        severity TEXT NOT NULL,
        summary TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        input_range_start TEXT NOT NULL,
        input_range_end TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
""")
```

- [ ] **Step 4: Add storage methods**

Add these methods to `SQLiteStorage`:

```python
def upsert_instrument(self, instrument: Instrument) -> None:
    now = utc_now_iso()
    record = instrument.to_record() | {"created_at": now, "updated_at": now}
    with sqlite3.connect(self.db_path) as conn:
        conn.execute(
            """INSERT INTO instruments (
                instrument_id, symbol, market, exchange, asset_type, currency,
                name, timezone, active, metadata_json, created_at, updated_at
            ) VALUES (
                :instrument_id, :symbol, :market, :exchange, :asset_type, :currency,
                :name, :timezone, :active, :metadata_json, :created_at, :updated_at
            )
            ON CONFLICT(instrument_id) DO UPDATE SET
                symbol=excluded.symbol,
                market=excluded.market,
                exchange=excluded.exchange,
                asset_type=excluded.asset_type,
                currency=excluded.currency,
                name=excluded.name,
                timezone=excluded.timezone,
                active=excluded.active,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            record,
        )

def upsert_instrument_alias(self, alias: InstrumentAlias) -> None:
    record = alias.to_record() | {"created_at": utc_now_iso()}
    with sqlite3.connect(self.db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO instrument_aliases (
                instrument_id, source, source_symbol, priority, created_at
            ) VALUES (
                :instrument_id, :source, :source_symbol, :priority, :created_at
            )""",
            record,
        )

def resolve_alias(self, source: str, source_symbol: str) -> str | None:
    with sqlite3.connect(self.db_path) as conn:
        row = conn.execute(
            """SELECT instrument_id FROM instrument_aliases
               WHERE source = ? AND source_symbol = ?
               ORDER BY priority ASC LIMIT 1""",
            (source, source_symbol),
        ).fetchone()
    return row[0] if row else None

def upsert_bars(self, df: pd.DataFrame) -> int:
    now = utc_now_iso()
    records = df.copy()
    if "created_at" not in records.columns:
        records["created_at"] = now
    records["updated_at"] = now
    records = records.to_dict("records")
    with sqlite3.connect(self.db_path) as conn:
        conn.executemany(
            """INSERT INTO bars (
                instrument_id, timestamp, local_date, interval, source, adjustment,
                open, high, low, close, volume, amount, currency, is_complete,
                provider_payload_hash, created_at, updated_at
            ) VALUES (
                :instrument_id, :timestamp, :local_date, :interval, :source, :adjustment,
                :open, :high, :low, :close, :volume, :amount, :currency, :is_complete,
                :provider_payload_hash, :created_at, :updated_at
            )
            ON CONFLICT(instrument_id, interval, timestamp, source, adjustment) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                amount=excluded.amount,
                currency=excluded.currency,
                is_complete=excluded.is_complete,
                provider_payload_hash=excluded.provider_payload_hash,
                updated_at=excluded.updated_at
            """,
            records,
        )
    return len(records)

def load_bars(self, instrument_id: str, interval: str, start: str, end: str) -> pd.DataFrame:
    with sqlite3.connect(self.db_path) as conn:
        return pd.read_sql_query(
            """SELECT * FROM bars
               WHERE instrument_id = ?
                 AND interval = ?
                 AND timestamp >= ?
                 AND timestamp <= ?
               ORDER BY timestamp ASC""",
            conn,
            params=(instrument_id, interval, start, end),
        )

def save_prediction_run(self, run: PredictionRun, predicted_bars: pd.DataFrame) -> str:
    now = utc_now_iso()
    run_record = run.to_record() | {"created_at": now}
    pred = predicted_bars.copy()
    pred["run_id"] = run.run_id
    pred["created_at"] = now
    with sqlite3.connect(self.db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO prediction_runs (
                run_id, model_name, model_variant, instrument_id, interval,
                lookback_start, lookback_end, horizon, source_selection_json,
                metadata_json, created_at
            ) VALUES (
                :run_id, :model_name, :model_variant, :instrument_id, :interval,
                :lookback_start, :lookback_end, :horizon, :source_selection_json,
                :metadata_json, :created_at
            )""",
            run_record,
        )
        conn.executemany(
            """INSERT OR REPLACE INTO predicted_bars (
                run_id, forecast_timestamp, step, open, high, low, close,
                volume, amount, confidence, created_at
            ) VALUES (
                :run_id, :forecast_timestamp, :step, :open, :high, :low, :close,
                :volume, :amount, :confidence, :created_at
            )""",
            pred.to_dict("records"),
        )
    return run.run_id

def load_latest_prediction_summary(self, instrument_id: str, interval: str) -> dict | None:
    with sqlite3.connect(self.db_path) as conn:
        run = conn.execute(
            """SELECT run_id, model_name, model_variant, horizon, created_at
               FROM prediction_runs
               WHERE instrument_id = ? AND interval = ?
               ORDER BY created_at DESC LIMIT 1""",
            (instrument_id, interval),
        ).fetchone()
        if run is None:
            return None
        rows = conn.execute(
            """SELECT close FROM predicted_bars
               WHERE run_id = ?
               ORDER BY step ASC""",
            (run[0],),
        ).fetchall()
    closes = [row[0] for row in rows]
    return {
        "run_id": run[0],
        "model_name": run[1],
        "model_variant": run[2],
        "horizon": run[3],
        "forecast_close_min": min(closes) if closes else None,
        "forecast_close_max": max(closes) if closes else None,
        "created_at": run[4],
    }

def save_technical_signals(self, signals: list[TechnicalSignal]) -> int:
    records = [signal.to_record() for signal in signals]
    with sqlite3.connect(self.db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO technical_signals (
                signal_id, instrument_id, timestamp, interval, signal_type,
                direction, strength, confidence, severity, summary, evidence_json,
                input_range_start, input_range_end, created_at
            ) VALUES (
                :signal_id, :instrument_id, :timestamp, :interval, :signal_type,
                :direction, :strength, :confidence, :severity, :summary, :evidence_json,
                :input_range_start, :input_range_end, :created_at
            )""",
            records,
        )
    return len(records)

def load_recent_technical_signals(self, instrument_id: str, interval: str, limit: int = 10) -> list[dict]:
    with sqlite3.connect(self.db_path) as conn:
        rows = pd.read_sql_query(
            """SELECT * FROM technical_signals
               WHERE instrument_id = ? AND interval = ?
               ORDER BY timestamp DESC LIMIT ?""",
            conn,
            params=(instrument_id, interval, limit),
        )
    return rows.to_dict("records")
```

- [ ] **Step 5: Run new and existing storage tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_market_storage.py tests/test_storage.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openstockagent/data/storage.py tests/test_market_storage.py
git commit -m "feat: add canonical market data storage"
```

---

## Task 3: CSV Feed, Normalization, and Validation

**Files:**
- Create: `src/openstockagent/data/normalize.py`
- Create: `src/openstockagent/data/validate.py`
- Create: `src/openstockagent/data/feeds/csv_feed.py`
- Create: `tests/fixtures/sample_bars.csv`
- Test: `tests/test_csv_feed.py`
- Test: `tests/test_normalize_validate.py`

- [ ] **Step 1: Create deterministic CSV fixture**

Create `tests/fixtures/sample_bars.csv`:

```csv
timestamp,open,high,low,close,volume,amount
2024-01-02T21:00:00Z,100,103,99,102,1000,101000
2024-01-03T21:00:00Z,102,104,101,103.5,1200,123000
2024-01-04T21:00:00Z,103.5,105,102,104,1100,114400
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_csv_feed.py`:

```python
from pathlib import Path

from openstockagent.data.feeds.csv_feed import CsvFeed


def test_csv_feed_fetches_bars():
    feed = CsvFeed(Path("tests/fixtures/sample_bars.csv"))
    df = feed.fetch_bars("AAPL", interval="1d")

    assert len(df) == 3
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "amount"]
    assert df.iloc[-1]["close"] == 104
```

Create `tests/test_normalize_validate.py`:

```python
import pandas as pd

from openstockagent.data.normalize import normalize_bars
from openstockagent.data.validate import validate_bars


def test_normalize_bars_adds_canonical_metadata():
    raw = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T21:00:00Z"],
            "open": [100.0],
            "high": [103.0],
            "low": [99.0],
            "close": [102.0],
            "volume": [1000.0],
        }
    )
    normalized = normalize_bars(
        raw,
        instrument_id="EQUITY:US:AAPL",
        interval="1d",
        source="csv",
        adjustment="split_adjusted",
        currency="USD",
    )

    assert normalized.iloc[0]["instrument_id"] == "EQUITY:US:AAPL"
    assert normalized.iloc[0]["amount"] == 101000.0
    assert normalized.iloc[0]["local_date"] == "2024-01-02"
    assert normalized.iloc[0]["is_complete"] == 1


def test_validate_bars_detects_invalid_ohlc():
    invalid = pd.DataFrame(
        {
            "instrument_id": ["EQUITY:US:AAPL"],
            "timestamp": ["2024-01-02T21:00:00Z"],
            "local_date": ["2024-01-02"],
            "interval": ["1d"],
            "source": ["csv"],
            "adjustment": ["split_adjusted"],
            "open": [100.0],
            "high": [98.0],
            "low": [99.0],
            "close": [102.0],
            "volume": [1000.0],
            "amount": [101000.0],
            "currency": ["USD"],
            "is_complete": [1],
        }
    )

    issues = validate_bars(invalid)
    assert issues[0]["issue_type"] == "invalid_ohlc"
    assert issues[0]["severity"] == "error"
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_csv_feed.py tests/test_normalize_validate.py -q
```

Expected: FAIL because new modules do not exist.

- [ ] **Step 4: Implement `CsvFeed`**

Create `src/openstockagent/data/feeds/csv_feed.py`:

```python
from pathlib import Path

import pandas as pd


class CsvFeed:
    source = "csv"

    def __init__(self, path: Path):
        self.path = path

    def fetch_bars(
        self,
        source_symbol: str,
        interval: str,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        df = pd.read_csv(self.path)
        expected = ["timestamp", "open", "high", "low", "close", "volume"]
        missing = [column for column in expected if column not in df.columns]
        if missing:
            raise ValueError(f"CSV feed missing required columns: {missing}")
        if "amount" not in df.columns:
            df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
        return df[["timestamp", "open", "high", "low", "close", "volume", "amount"]]
```

- [ ] **Step 5: Implement normalization**

Create `src/openstockagent/data/normalize.py`:

```python
import pandas as pd


def normalize_bars(
    df: pd.DataFrame,
    instrument_id: str,
    interval: str,
    source: str,
    adjustment: str,
    currency: str | None = None,
) -> pd.DataFrame:
    normalized = df.copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    normalized["local_date"] = pd.to_datetime(normalized["timestamp"], utc=True).dt.strftime("%Y-%m-%d")
    if "amount" not in normalized.columns:
        normalized["amount"] = normalized["volume"] * normalized[["open", "high", "low", "close"]].mean(axis=1)
    normalized["instrument_id"] = instrument_id
    normalized["interval"] = interval
    normalized["source"] = source
    normalized["adjustment"] = adjustment
    normalized["currency"] = currency
    normalized["is_complete"] = 1
    normalized["provider_payload_hash"] = None
    columns = [
        "instrument_id", "timestamp", "local_date", "interval", "source", "adjustment",
        "open", "high", "low", "close", "volume", "amount", "currency",
        "is_complete", "provider_payload_hash",
    ]
    return normalized[columns]
```

- [ ] **Step 6: Implement validation**

Create `src/openstockagent/data/validate.py`:

```python
import json
from uuid import uuid4

import pandas as pd

from openstockagent.data.models import utc_now_iso


def validate_bars(df: pd.DataFrame) -> list[dict]:
    issues: list[dict] = []
    required = ["instrument_id", "timestamp", "interval", "open", "high", "low", "close"]
    for column in required:
        if column not in df.columns:
            issues.append(_issue(None, None, None, "error", "missing_column", {"column": column}))
            return issues

    for _, row in df.iterrows():
        instrument_id = row["instrument_id"]
        interval = row["interval"]
        timestamp = row["timestamp"]
        high = row["high"]
        low = row["low"]
        open_ = row["open"]
        close = row["close"]
        if min(open_, high, low, close) < 0:
            issues.append(_issue(instrument_id, interval, timestamp, "error", "negative_price", row.to_dict()))
        if high < max(open_, close) or low > min(open_, close):
            issues.append(_issue(instrument_id, interval, timestamp, "error", "invalid_ohlc", row.to_dict()))
        if "volume" in row and pd.notna(row["volume"]) and row["volume"] < 0:
            issues.append(_issue(instrument_id, interval, timestamp, "error", "negative_volume", row.to_dict()))
    return issues


def _issue(instrument_id, interval, timestamp, severity, issue_type, details) -> dict:
    return {
        "issue_id": f"dq_{uuid4().hex}",
        "run_id": None,
        "instrument_id": instrument_id,
        "interval": interval,
        "timestamp": timestamp,
        "severity": severity,
        "issue_type": issue_type,
        "details_json": json.dumps(details, default=str),
        "created_at": utc_now_iso(),
    }
```

- [ ] **Step 7: Run tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_csv_feed.py tests/test_normalize_validate.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/openstockagent/data/normalize.py src/openstockagent/data/validate.py src/openstockagent/data/feeds/csv_feed.py tests/fixtures/sample_bars.csv tests/test_csv_feed.py tests/test_normalize_validate.py
git commit -m "feat: add deterministic feed normalization and validation"
```

---

## Task 4: Feed Interface, Yahoo Migration, and Registry

**Files:**
- Modify: `src/openstockagent/data/feeds/base.py`
- Modify: `src/openstockagent/data/feeds/yahoo.py`
- Create: `src/openstockagent/data/feeds/registry.py`
- Create: `src/openstockagent/data/symbols.py`
- Test: `tests/test_feed_registry.py`
- Modify: `tests/test_feeds.py`

- [ ] **Step 1: Write failing registry tests**

Create `tests/test_feed_registry.py`:

```python
from pathlib import Path

from openstockagent.data.feeds.csv_feed import CsvFeed
from openstockagent.data.feeds.registry import FeedRegistry
from openstockagent.data.symbols import infer_instrument


def test_infer_us_instrument():
    instrument, alias = infer_instrument("AAPL", source="yahoo")
    assert instrument.instrument_id == "EQUITY:US:AAPL"
    assert alias.source_symbol == "AAPL"


def test_infer_hk_instrument():
    instrument, alias = infer_instrument("9988.HK", source="yahoo")
    assert instrument.instrument_id == "EQUITY:HK:09988"
    assert instrument.market == "HK"


def test_registry_returns_configured_feed():
    registry = FeedRegistry()
    csv_feed = CsvFeed(Path("tests/fixtures/sample_bars.csv"))
    registry.register("US", "equity", "1d", csv_feed)

    feed = registry.resolve(market="US", asset_type="equity", interval="1d")
    assert feed.source == "csv"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_feed_registry.py -q
```

Expected: FAIL because registry and symbol helpers do not exist.

- [ ] **Step 3: Update feed base interface**

Modify `src/openstockagent/data/feeds/base.py`:

```python
from abc import ABC, abstractmethod

import pandas as pd


class BaseMarketDataFeed(ABC):
    source: str

    @abstractmethod
    def fetch_bars(
        self,
        source_symbol: str,
        interval: str,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        ...


class BaseDataFeed(ABC):
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        """
        Backward-compatible interface for the existing Week 1 tests.
        New code should use BaseMarketDataFeed.fetch_bars.
        """
        ...
```

- [ ] **Step 4: Add symbol helpers**

Create `src/openstockagent/data/symbols.py`:

```python
from openstockagent.data.models import Instrument, InstrumentAlias


def infer_instrument(source_symbol: str, source: str) -> tuple[Instrument, InstrumentAlias]:
    if source_symbol.endswith(".HK"):
        raw = source_symbol[:-3].zfill(5)
        instrument = Instrument(
            instrument_id=f"EQUITY:HK:{raw}",
            symbol=raw,
            market="HK",
            exchange="HKEX",
            asset_type="equity",
            currency="HKD",
            name=None,
            timezone="Asia/Hong_Kong",
        )
    elif source_symbol.endswith(".SH") or source_symbol.endswith(".SZ"):
        raw, suffix = source_symbol.split(".")
        exchange = "SSE" if suffix == "SH" else "SZSE"
        instrument = Instrument(
            instrument_id=f"EQUITY:CN:{raw}",
            symbol=raw,
            market="CN",
            exchange=exchange,
            asset_type="equity",
            currency="CNY",
            name=None,
            timezone="Asia/Shanghai",
        )
    else:
        raw = source_symbol.upper()
        instrument = Instrument(
            instrument_id=f"EQUITY:US:{raw}",
            symbol=raw,
            market="US",
            exchange=None,
            asset_type="equity",
            currency="USD",
            name=None,
            timezone="America/New_York",
        )
    return instrument, InstrumentAlias(instrument.instrument_id, source, source_symbol)
```

- [ ] **Step 5: Add registry**

Create `src/openstockagent/data/feeds/registry.py`:

```python
class FeedRegistry:
    def __init__(self):
        self._feeds = {}

    def register(self, market: str, asset_type: str, interval: str, feed) -> None:
        self._feeds[(market, asset_type, interval)] = feed

    def resolve(self, market: str, asset_type: str, interval: str):
        key = (market, asset_type, interval)
        if key in self._feeds:
            return self._feeds[key]
        fallback = (market, asset_type, "1d")
        if fallback in self._feeds:
            return self._feeds[fallback]
        raise ValueError(f"No feed registered for market={market}, asset_type={asset_type}, interval={interval}")
```

- [ ] **Step 6: Migrate Yahoo feed while keeping old method**

Modify `src/openstockagent/data/feeds/yahoo.py`:

```python
import pandas as pd
import yfinance as yf

from .base import BaseDataFeed, BaseMarketDataFeed


class YahooFinanceFeed(BaseDataFeed, BaseMarketDataFeed):
    source = "yahoo"

    def fetch_bars(
        self,
        source_symbol: str,
        interval: str,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        ticker = yf.Ticker(source_symbol)
        kwargs = {"interval": interval}
        if period:
            kwargs["period"] = period
        else:
            kwargs["start"] = start
            kwargs["end"] = end
        df = ticker.history(**kwargs, auto_adjust=adjusted)
        if df.empty:
            raise ValueError(f"No data returned for {source_symbol}")
        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.reset_index().rename(columns={df.index.name or "Date": "timestamp"})
        if "timestamp" not in df.columns:
            df = df.rename(columns={df.columns[0]: "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
        return df[["timestamp", "open", "high", "low", "close", "volume", "amount"]]

    def fetch_ohlcv(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        df = self.fetch_bars(symbol, interval="1d", period=period)
        df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        return df.set_index("date")[["open", "high", "low", "close", "volume"]]
```

- [ ] **Step 7: Run registry and feed tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_feed_registry.py tests/test_feeds.py::test_base_data_feed_returns_dataframe -q
```

Expected: PASS. Do not run the Yahoo network test by default.

- [ ] **Step 8: Commit**

```bash
git add src/openstockagent/data/feeds/base.py src/openstockagent/data/feeds/yahoo.py src/openstockagent/data/feeds/registry.py src/openstockagent/data/symbols.py tests/test_feed_registry.py
git commit -m "feat: add feed registry and canonical symbol mapping"
```

---

## Task 5: Kronos Input Frame and Prediction Persistence

**Files:**
- Modify: `src/openstockagent/data/storage.py`
- Modify: `src/openstockagent/predictors/kronos_adapter.py`
- Test: `tests/test_kronos_storage.py`

- [ ] **Step 1: Write failing tests for Kronos frame loading**

Create `tests/test_kronos_storage.py`:

```python
import pandas as pd

from openstockagent.data.storage import SQLiteStorage


def test_load_kronos_frame_returns_sorted_numeric_columns(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    df = pd.DataFrame(
        {
            "instrument_id": ["EQUITY:US:AAPL"] * 3,
            "timestamp": ["2024-01-03T21:00:00Z", "2024-01-02T21:00:00Z", "2024-01-04T21:00:00Z"],
            "local_date": ["2024-01-03", "2024-01-02", "2024-01-04"],
            "interval": ["1d"] * 3,
            "source": ["csv"] * 3,
            "adjustment": ["split_adjusted"] * 3,
            "open": [102.0, 100.0, 103.5],
            "high": [104.0, 103.0, 105.0],
            "low": [101.0, 99.0, 102.0],
            "close": [103.5, 102.0, 104.0],
            "volume": [1200.0, 1000.0, 1100.0],
            "amount": [123000.0, 101000.0, 114400.0],
            "currency": ["USD"] * 3,
            "is_complete": [1, 1, 1],
        }
    )
    storage.upsert_bars(df)

    frame = storage.load_kronos_frame("EQUITY:US:AAPL", "1d", lookback=2)

    assert list(frame.columns) == ["open", "high", "low", "close", "volume", "amount"]
    assert list(frame["close"]) == [103.5, 104.0]
    assert str(frame.index[0]) == "2024-01-03 21:00:00+00:00"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_kronos_storage.py -q
```

Expected: FAIL because `load_kronos_frame` does not exist.

- [ ] **Step 3: Implement `load_kronos_frame`**

Add to `SQLiteStorage`:

```python
def load_kronos_frame(
    self,
    instrument_id: str,
    interval: str,
    lookback: int = 512,
    adjustment: str = "split_adjusted",
) -> pd.DataFrame:
    with sqlite3.connect(self.db_path) as conn:
        df = pd.read_sql_query(
            """SELECT timestamp, open, high, low, close, volume, amount
               FROM bars
               WHERE instrument_id = ?
                 AND interval = ?
                 AND adjustment = ?
                 AND is_complete = 1
               ORDER BY timestamp DESC
               LIMIT ?""",
            conn,
            params=(instrument_id, interval, adjustment, lookback),
        )
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])
    df = df.sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp")
    return df[["open", "high", "low", "close", "volume", "amount"]]
```

- [ ] **Step 4: Run Kronos storage test**

Run:

```bash
.venv/bin/python -m pytest tests/test_kronos_storage.py -q
```

Expected: PASS.

- [ ] **Step 5: Adjust Kronos adapter to accept `amount` without dropping it**

Modify `src/openstockagent/predictors/kronos_adapter.py` in `predict`:

```python
required = ["open", "high", "low", "close", "volume"]
missing = [column for column in required if column not in df.columns]
if missing:
    raise ValueError(f"Kronos input missing required columns: {missing}")
columns = ["open", "high", "low", "close", "volume"]
if "amount" in df.columns:
    columns.append("amount")
input_df = df[columns].copy()
```

- [ ] **Step 6: Run relevant tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_kronos_storage.py tests/test_kronos_adapter.py::test_kronos_predict_consistency -q
```

Expected: PASS if model artifacts are cached. If Kronos model download is unavailable, record the failure and mark Kronos integration tests as slow/model in a later task.

- [ ] **Step 7: Commit**

```bash
git add src/openstockagent/data/storage.py src/openstockagent/predictors/kronos_adapter.py tests/test_kronos_storage.py
git commit -m "feat: add Kronos storage frame and prediction persistence"
```

---

## Task 6: Technical Features and Golden/Death Cross Signals

**Files:**
- Create: `src/openstockagent/features/__init__.py`
- Create: `src/openstockagent/features/technical.py`
- Create: `src/openstockagent/signals/__init__.py`
- Create: `src/openstockagent/signals/technical.py`
- Test: `tests/test_technical_signals.py`

- [ ] **Step 1: Write failing tests for moving average signals**

Create `tests/test_technical_signals.py`:

```python
import pandas as pd

from openstockagent.features.technical import compute_moving_average_features
from openstockagent.signals.technical import detect_ma_cross_signals


def test_compute_moving_average_features():
    df = pd.DataFrame(
        {"close": [10, 11, 12, 13, 14]},
        index=pd.to_datetime(
            [
                "2024-01-01T21:00:00Z",
                "2024-01-02T21:00:00Z",
                "2024-01-03T21:00:00Z",
                "2024-01-04T21:00:00Z",
                "2024-01-05T21:00:00Z",
            ],
            utc=True,
        ),
    )
    features = compute_moving_average_features(df, instrument_id="EQUITY:US:AAPL", interval="1d", windows=(2, 3))
    latest = features[features["timestamp"] == "2024-01-05T21:00:00Z"]

    assert set(latest["feature_name"]) == {"ma_close_2", "ma_close_3"}
    assert latest[latest["feature_name"] == "ma_close_2"].iloc[0]["feature_value"] == 13.5


def test_detects_golden_cross():
    df = pd.DataFrame(
        {"close": [10, 9, 8, 8, 9, 11, 13]},
        index=pd.to_datetime(
            [
                "2024-01-01T21:00:00Z",
                "2024-01-02T21:00:00Z",
                "2024-01-03T21:00:00Z",
                "2024-01-04T21:00:00Z",
                "2024-01-05T21:00:00Z",
                "2024-01-08T21:00:00Z",
                "2024-01-09T21:00:00Z",
            ],
            utc=True,
        ),
    )
    signals = detect_ma_cross_signals(
        df,
        instrument_id="EQUITY:US:AAPL",
        interval="1d",
        fast_window=2,
        slow_window=3,
    )

    assert any(signal.signal_type == "golden_cross" for signal in signals)
    assert signals[-1].direction == "bullish"
    assert "MA2 crossed above MA3" in signals[-1].summary
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_technical_signals.py -q
```

Expected: FAIL because features and signals packages do not exist.

- [ ] **Step 3: Implement moving average feature generation**

Create `src/openstockagent/features/__init__.py`:

```python
"""Feature generation utilities."""
```

Create `src/openstockagent/features/technical.py`:

```python
import json

import pandas as pd

from openstockagent.data.models import utc_now_iso


def compute_moving_average_features(
    df: pd.DataFrame,
    instrument_id: str,
    interval: str,
    windows: tuple[int, ...] = (5, 20),
) -> pd.DataFrame:
    if "close" not in df.columns:
        raise ValueError("close column is required for moving averages")
    rows = []
    for window in windows:
        series = df["close"].rolling(window=window).mean()
        for timestamp, value in series.dropna().items():
            rows.append(
                {
                    "instrument_id": instrument_id,
                    "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "interval": interval,
                    "feature_name": f"ma_close_{window}",
                    "feature_value": float(value),
                    "window": str(window),
                    "params_json": json.dumps({"price": "close", "window": window}),
                    "input_range_start": df.index[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "input_range_end": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "created_at": utc_now_iso(),
                }
            )
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Implement MA cross signals**

Create `src/openstockagent/signals/__init__.py`:

```python
"""Signal generation utilities."""
```

Create `src/openstockagent/signals/technical.py`:

```python
import json
from uuid import uuid4

import pandas as pd

from openstockagent.data.models import TechnicalSignal


def detect_ma_cross_signals(
    df: pd.DataFrame,
    instrument_id: str,
    interval: str,
    fast_window: int = 5,
    slow_window: int = 20,
) -> list[TechnicalSignal]:
    if fast_window >= slow_window:
        raise ValueError("fast_window must be less than slow_window")
    close = df["close"]
    fast = close.rolling(window=fast_window).mean()
    slow = close.rolling(window=slow_window).mean()
    signals: list[TechnicalSignal] = []
    for idx in range(1, len(df)):
        prev_fast, prev_slow = fast.iloc[idx - 1], slow.iloc[idx - 1]
        curr_fast, curr_slow = fast.iloc[idx], slow.iloc[idx]
        if pd.isna(prev_fast) or pd.isna(prev_slow) or pd.isna(curr_fast) or pd.isna(curr_slow):
            continue
        timestamp = df.index[idx].strftime("%Y-%m-%dT%H:%M:%SZ")
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            signals.append(
                _ma_signal(
                    instrument_id, interval, timestamp, "golden_cross", "bullish",
                    fast_window, slow_window, prev_fast, prev_slow, curr_fast, curr_slow,
                    df.index[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            )
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            signals.append(
                _ma_signal(
                    instrument_id, interval, timestamp, "death_cross", "bearish",
                    fast_window, slow_window, prev_fast, prev_slow, curr_fast, curr_slow,
                    df.index[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            )
    return signals


def _ma_signal(
    instrument_id, interval, timestamp, signal_type, direction,
    fast_window, slow_window, prev_fast, prev_slow, curr_fast, curr_slow,
    input_range_start,
) -> TechnicalSignal:
    strength = min(abs(curr_fast - curr_slow) / (abs(curr_slow) + 1e-8), 1.0)
    action = "above" if direction == "bullish" else "below"
    summary = f"MA{fast_window} crossed {action} MA{slow_window} on {interval} bars."
    evidence = {
        "fast_ma": f"ma_close_{fast_window}",
        "slow_ma": f"ma_close_{slow_window}",
        "previous_fast": float(prev_fast),
        "previous_slow": float(prev_slow),
        "current_fast": float(curr_fast),
        "current_slow": float(curr_slow),
    }
    return TechnicalSignal(
        signal_id=f"sig_{uuid4().hex}",
        instrument_id=instrument_id,
        timestamp=timestamp,
        interval=interval,
        signal_type=signal_type,
        direction=direction,
        strength=float(strength),
        confidence=0.7,
        severity="watch",
        summary=summary,
        evidence_json=json.dumps(evidence),
        input_range_start=input_range_start,
        input_range_end=timestamp,
    )
```

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_technical_signals.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openstockagent/features src/openstockagent/signals tests/test_technical_signals.py
git commit -m "feat: add moving average technical signals"
```

---

## Task 7: LLM Analysis Context Skeleton

**Files:**
- Create: `src/openstockagent/context/__init__.py`
- Create: `src/openstockagent/context/analysis_context.py`
- Test: `tests/test_analysis_context.py`

- [ ] **Step 1: Write failing context tests**

Create `tests/test_analysis_context.py`:

```python
import json

import pandas as pd

from openstockagent.context.analysis_context import build_analysis_context
from openstockagent.data.models import PredictionRun, TechnicalSignal
from openstockagent.data.storage import SQLiteStorage


def test_analysis_context_contains_prediction_signal_and_empty_sections(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    bars = pd.DataFrame(
        {
            "instrument_id": ["EQUITY:US:AAPL"] * 3,
            "timestamp": ["2024-01-02T21:00:00Z", "2024-01-03T21:00:00Z", "2024-01-04T21:00:00Z"],
            "local_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "interval": ["1d"] * 3,
            "source": ["csv"] * 3,
            "adjustment": ["split_adjusted"] * 3,
            "open": [100.0, 102.0, 103.5],
            "high": [103.0, 104.0, 105.0],
            "low": [99.0, 101.0, 102.0],
            "close": [102.0, 103.5, 104.0],
            "volume": [1000.0, 1200.0, 1100.0],
            "amount": [101000.0, 123000.0, 114400.0],
            "currency": ["USD"] * 3,
            "is_complete": [1, 1, 1],
        }
    )
    storage.upsert_bars(bars)
    storage.save_prediction_run(
        PredictionRun(
            run_id="pred_1",
            model_name="kronos",
            model_variant="small",
            instrument_id="EQUITY:US:AAPL",
            interval="1d",
            lookback_start="2024-01-02T21:00:00Z",
            lookback_end="2024-01-04T21:00:00Z",
            horizon=1,
            source_selection_json=json.dumps({"source": "csv"}),
        ),
        pd.DataFrame(
            {
                "forecast_timestamp": ["2024-01-05T21:00:00Z"],
                "step": [1],
                "open": [104.0],
                "high": [106.0],
                "low": [103.0],
                "close": [105.5],
                "volume": [1300.0],
                "amount": [136500.0],
                "confidence": [0.7],
            }
        ),
    )
    storage.save_technical_signals(
        [
            TechnicalSignal(
                signal_id="sig_1",
                instrument_id="EQUITY:US:AAPL",
                timestamp="2024-01-04T21:00:00Z",
                interval="1d",
                signal_type="golden_cross",
                direction="bullish",
                strength=0.75,
                confidence=0.8,
                severity="watch",
                summary="MA5 crossed above MA20.",
                evidence_json='{"fast": 101.0, "slow": 100.0}',
                input_range_start="2024-01-01T21:00:00Z",
                input_range_end="2024-01-04T21:00:00Z",
            )
        ]
    )

    context = build_analysis_context(storage, "EQUITY:US:AAPL", "1d", as_of="2024-01-05T00:00:00Z")

    assert context["instrument"]["instrument_id"] == "EQUITY:US:AAPL"
    assert context["price_state"]["last_close"] == 104.0
    assert context["kronos_prediction"]["run_id"] == "pred_1"
    assert context["technical_signals"][0]["type"] == "golden_cross"
    assert context["sentiment"]["status"] == "not_available"
    assert context["events"] == []
    assert context["data_quality"]["status"] == "ok"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_analysis_context.py -q
```

Expected: FAIL because context package does not exist.

- [ ] **Step 3: Implement context builder**

Create `src/openstockagent/context/__init__.py`:

```python
"""LLM analysis context builders."""
```

Create `src/openstockagent/context/analysis_context.py`:

```python
import json


def build_analysis_context(storage, instrument_id: str, interval: str, as_of: str) -> dict:
    bars = storage.load_bars(instrument_id, interval, "0000-01-01T00:00:00Z", as_of)
    latest = bars.iloc[-1] if not bars.empty else None
    prediction = storage.load_latest_prediction_summary(instrument_id, interval)
    signals = storage.load_recent_technical_signals(instrument_id, interval, limit=5)
    return {
        "as_of": as_of,
        "instrument": {
            "instrument_id": instrument_id,
            "symbol": instrument_id.split(":")[-1],
            "market": instrument_id.split(":")[1] if ":" in instrument_id else None,
            "currency": latest["currency"] if latest is not None and "currency" in latest else None,
        },
        "price_state": _price_state(latest, interval),
        "kronos_prediction": _prediction_context(prediction, interval),
        "technical_signals": [_signal_context(signal) for signal in signals],
        "sentiment": {
            "status": "not_available",
            "window": None,
            "mean_score": None,
            "confidence": None,
            "top_drivers": [],
        },
        "events": [],
        "fundamentals": {"status": "not_available", "items": []},
        "macro": {"status": "not_available", "items": []},
        "data_quality": {"status": "ok", "notes": []},
    }


def _price_state(latest, interval: str) -> dict:
    if latest is None:
        return {"interval": interval, "status": "not_available"}
    return {
        "interval": interval,
        "last_close": float(latest["close"]),
        "volume": float(latest["volume"]) if latest.get("volume") is not None else None,
    }


def _prediction_context(prediction: dict | None, interval: str) -> dict:
    if prediction is None:
        return {"status": "not_available", "interval": interval}
    return {
        "status": "available",
        "model": f"{prediction['model_name']}-{prediction['model_variant']}",
        "interval": interval,
        "horizon": prediction["horizon"],
        "forecast_close_min": prediction["forecast_close_min"],
        "forecast_close_max": prediction["forecast_close_max"],
        "run_id": prediction["run_id"],
    }


def _signal_context(signal: dict) -> dict:
    evidence = json.loads(signal["evidence_json"])
    return {
        "type": signal["signal_type"],
        "direction": signal["direction"],
        "strength": signal["strength"],
        "confidence": signal["confidence"],
        "summary": signal["summary"],
        "evidence_ref": signal["signal_id"],
        "evidence": evidence,
    }
```

- [ ] **Step 4: Run context test**

Run:

```bash
.venv/bin/python -m pytest tests/test_analysis_context.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openstockagent/context tests/test_analysis_context.py
git commit -m "feat: add LLM analysis context skeleton"
```

---

## Task 8: Market Data Sync Pipeline and CLI Migration

**Files:**
- Create: `src/openstockagent/pipelines/__init__.py`
- Create: `src/openstockagent/pipelines/sync_market_data.py`
- Modify: `scripts/run_prediction.py`
- Test: `tests/test_sync_market_data.py`

- [ ] **Step 1: Write failing sync pipeline test**

Create `tests/test_sync_market_data.py`:

```python
from pathlib import Path

from openstockagent.data.feeds.csv_feed import CsvFeed
from openstockagent.data.storage import SQLiteStorage
from openstockagent.pipelines.sync_market_data import sync_bars_for_symbol


def test_sync_bars_for_symbol_persists_canonical_bars(temp_db_path):
    storage = SQLiteStorage(temp_db_path)
    feed = CsvFeed(Path("tests/fixtures/sample_bars.csv"))

    result = sync_bars_for_symbol(
        storage=storage,
        feed=feed,
        source_symbol="AAPL",
        interval="1d",
        source="csv",
        adjustment="split_adjusted",
    )

    assert result["rows_inserted"] == 3
    frame = storage.load_kronos_frame("EQUITY:US:AAPL", "1d", lookback=10)
    assert len(frame) == 3
    assert frame.iloc[-1]["close"] == 104
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_sync_market_data.py -q
```

Expected: FAIL because pipeline module does not exist.

- [ ] **Step 3: Implement sync pipeline**

Create `src/openstockagent/pipelines/__init__.py`:

```python
"""Pipeline entry points."""
```

Create `src/openstockagent/pipelines/sync_market_data.py`:

```python
from openstockagent.data.normalize import normalize_bars
from openstockagent.data.symbols import infer_instrument
from openstockagent.data.validate import validate_bars


def sync_bars_for_symbol(
    storage,
    feed,
    source_symbol: str,
    interval: str,
    source: str,
    adjustment: str = "split_adjusted",
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    instrument, alias = infer_instrument(source_symbol, source)
    storage.upsert_instrument(instrument)
    storage.upsert_instrument_alias(alias)
    raw = feed.fetch_bars(source_symbol, interval=interval, period=period, start=start, end=end)
    bars = normalize_bars(
        raw,
        instrument_id=instrument.instrument_id,
        interval=interval,
        source=source,
        adjustment=adjustment,
        currency=instrument.currency,
    )
    issues = validate_bars(bars)
    errors = [issue for issue in issues if issue["severity"] == "error"]
    if errors:
        raise ValueError(f"Data validation failed for {source_symbol}: {errors[0]['issue_type']}")
    rows = storage.upsert_bars(bars)
    return {
        "instrument_id": instrument.instrument_id,
        "rows_inserted": rows,
        "quality_issues": len(issues),
    }
```

- [ ] **Step 4: Run sync pipeline test**

Run:

```bash
.venv/bin/python -m pytest tests/test_sync_market_data.py -q
```

Expected: PASS.

- [ ] **Step 5: Migrate `scripts/run_prediction.py` data loading path**

Modify `scripts/run_prediction.py` so the data path is:

```python
from openstockagent.config import DB_PATH, KRONOS_PRED_LEN
from openstockagent.data.feeds.yahoo import YahooFinanceFeed
from openstockagent.data.storage import SQLiteStorage
from openstockagent.pipelines.sync_market_data import sync_bars_for_symbol
from openstockagent.predictors.kronos_adapter import KronosStockPredictor
```

Inside `main`, replace direct Yahoo fetch and `save_ohlcv` with:

```python
storage = SQLiteStorage(DB_PATH)
feed = YahooFinanceFeed()
sync_result = sync_bars_for_symbol(
    storage=storage,
    feed=feed,
    source_symbol=symbol,
    interval="1d",
    source=feed.source,
    adjustment="split_adjusted",
    period=period,
)
instrument_id = sync_result["instrument_id"]
df = storage.load_kronos_frame(instrument_id, "1d", lookback=512)
click.echo(f"Loaded {len(df)} canonical rows for {instrument_id}")
```

Keep the existing prediction printout. Prediction persistence is available through `save_prediction_run`, but wiring it into the CLI should be a separate small follow-up if the CLI needs stable run IDs.

- [ ] **Step 6: Run safe tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_sync_market_data.py tests/test_kronos_storage.py tests/test_storage.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openstockagent/pipelines scripts/run_prediction.py tests/test_sync_market_data.py
git commit -m "feat: route predictions through canonical market data"
```

---

## Task 9: Final Verification

**Files:**
- No new files unless tests require minor import fixes.

- [ ] **Step 1: Run deterministic test suite**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_data_models.py \
  tests/test_market_storage.py \
  tests/test_normalize_validate.py \
  tests/test_csv_feed.py \
  tests/test_feed_registry.py \
  tests/test_kronos_storage.py \
  tests/test_technical_signals.py \
  tests/test_analysis_context.py \
  tests/test_sync_market_data.py \
  tests/test_storage.py \
  tests/test_feeds.py::test_base_data_feed_returns_dataframe \
  -q
```

Expected: PASS. This command intentionally excludes Yahoo network fetch and Kronos full model inference.

- [ ] **Step 2: Check git status**

Run:

```bash
git status --short
```

Expected: only user-owned unrelated files remain, such as `?? scripts/benchmark_models.py` if still present.

- [ ] **Step 3: Commit any final import or compatibility fixes**

If Step 1 required small fixes:

```bash
git add <changed-files>
git commit -m "test: stabilize canonical market data suite"
```

If Step 1 required no fixes, do not create an empty commit.

---

## Self-Review Checklist

- [ ] **Spec coverage:** Implements canonical instruments, aliases, bars, feed runs foundation, quality validation, Kronos input frames, prediction persistence, MA cross signals, and LLM context skeleton from `docs/superpowers/specs/2026-05-23-market-data-source-design.md`.
- [ ] **Deferred by design:** Paid providers, realtime streaming, full news ingestion, full macro/fundamental ingestion, LLM API calls, and frontend changes are intentionally out of first implementation scope.
- [ ] **Kronos compatibility:** `load_kronos_frame` returns sorted `open/high/low/close/volume/amount` columns indexed by timestamp.
- [ ] **LLM compatibility:** `AnalysisContext` includes price state, prediction summary, technical signals with evidence refs, explicit empty sentiment/events/fundamentals/macro sections, and data quality status.
- [ ] **Anti-lookahead base:** Context builder accepts `as_of`; future sentiment/events/fundamental loaders must filter using public release timestamps.
- [ ] **Test hygiene:** Default verification excludes network and model-download tests.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-23-market-data-source-implementation.md`. Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
