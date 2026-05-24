# Market Data Source Design

Date: 2026-05-23
Project: OpenStockAgent
Status: Draft for review

## 1. Goal

Design a market data layer that can support three downstream consumers:

1. Kronos prediction, which needs clean time-ordered OHLCV candlestick data with stable timestamps.
2. Strategy and signal engines, which need multi-period K-line data and derived indicators such as moving averages, golden crosses, RSI, MACD, breakouts, and volume anomalies.
3. Future LLM analysis, which needs compact, structured, traceable context: market state, predictions, signals, sentiment, events, fundamentals, macro data, and data quality notes.

The data layer must keep external data source details away from predictors, strategies, and LLM prompts. Yahoo, AKShare, Tushare, Polygon, CSV, and later providers should all be normalized into the same internal model.

## 2. Scope

This design covers:

- Data source adapters and source selection.
- Canonical symbol and market metadata.
- Standard K-line storage for daily and intraday periods.
- Kronos-ready input views.
- Technical indicator and signal storage, including golden cross and death cross signals.
- Sentiment, event, fundamental, and macro data structures for future LLM analysis.
- Data quality, lineage, and anti-lookahead rules.
- Migration path from the current `ohlcv` table.

This design does not implement portfolio construction, order execution, broker integration, or trading automation.

## 3. Key Decisions

### 3.1 Use a layered data model

Raw external data is not consumed directly by Kronos, strategies, or LLM prompts. Every source follows this path:

```text
External source
  -> feed adapter
  -> raw payload or normalized dataframe
  -> validator
  -> canonical storage
  -> derived features and signals
  -> consumer-specific views
```

### 3.2 Keep canonical bars clean

`bars` stores only factual K-line data and source metadata. It must not store moving averages, golden cross flags, sentiment scores, LLM summaries, or strategy decisions. Those belong to derived tables.

This keeps K-line history stable and makes it easier to recompute indicators when formulas change.

### 3.3 Store both machine views and explanation views

Kronos needs numeric sequences. LLM analysis needs a compact narrative-ready snapshot with provenance. The same underlying data should produce both:

- `KronosInputFrame`: DataFrame with `open`, `high`, `low`, `close`, `volume`, optional `amount`, indexed by timestamp.
- `AnalysisContext`: JSON object with current price state, technical signals, prediction summary, sentiment, event facts, macro/fundamental facts, and evidence references.

### 3.4 SQLite first, PostgreSQL later

SQLite remains the first implementation target. The schema should avoid SQLite-only shortcuts so it can move to PostgreSQL later. JSON fields are allowed for flexible metadata, but primary query dimensions stay in normal columns.

## 4. Data Source Strategy

### 4.1 Source roles

| Source | Initial role | Markets | Data types | Notes |
| --- | --- | --- | --- | --- |
| Yahoo Finance via `yfinance` | MVP and US/HK prototype | US, HK, ETFs, indices | OHLCV, some metadata | Free and convenient, not the production reliability baseline |
| AKShare | CN prototype | A-share, HK, macro, public datasets | OHLCV, fundamentals, macro, sentiment-like public data | Good breadth for personal research |
| CSV | Tests and reproducible experiments | Any | OHLCV, labels, sample events | Required so tests do not depend on network |
| Tushare Pro | Future stable CN source | A-share, funds, indices | OHLCV, fundamentals, financial statements | Better for stable CN backtesting |
| Polygon or Finnhub | Future stable US source | US | OHLCV, realtime, news | Better for production monitoring |

### 4.2 Source selection

The `FeedRegistry` selects sources using market, asset type, interval, and purpose.

```text
US equity daily       -> YahooFinanceFeed in MVP, PolygonFeed later
US equity intraday    -> PolygonFeed later
HK equity daily       -> YahooFinanceFeed in MVP
CN equity daily       -> AKShareFeed in MVP, TushareFeed later
CN equity intraday    -> TushareFeed later
Regression test data  -> CsvFeed
```

Feed choice is configuration, not business logic. Strategy code asks for canonical data and never imports a specific external feed.

## 5. Canonical Identifiers

### 5.1 Instrument identity

Every asset uses a canonical instrument record:

```text
instrument_id: stable internal id, for example EQUITY:US:AAPL
symbol: external or display symbol, for example AAPL
market: US, HK, CN
exchange: NASDAQ, NYSE, HKEX, SSE, SZSE
asset_type: equity, etf, index, fund, future, forex, crypto
currency: USD, HKD, CNY
name: display name
timezone: exchange timezone
active: boolean
```

### 5.2 Symbol aliases

External providers use different symbol formats. Store aliases separately:

```text
instrument_id | source | source_symbol | priority
EQUITY:US:AAPL | yahoo | AAPL | 1
EQUITY:HK:09988 | yahoo | 9988.HK | 1
EQUITY:CN:600519 | akshare | 600519 | 1
EQUITY:CN:600519 | tushare | 600519.SH | 1
```

This avoids leaking provider-specific symbols into storage and analysis.

## 6. Core Tables

### 6.1 `instruments`

Stores asset metadata.

```text
instrument_id TEXT PRIMARY KEY
symbol TEXT NOT NULL
market TEXT NOT NULL
exchange TEXT
asset_type TEXT NOT NULL
currency TEXT
name TEXT
timezone TEXT
active INTEGER NOT NULL DEFAULT 1
metadata_json TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

### 6.2 `instrument_aliases`

Maps internal instruments to provider symbols.

```text
instrument_id TEXT NOT NULL
source TEXT NOT NULL
source_symbol TEXT NOT NULL
priority INTEGER NOT NULL DEFAULT 1
created_at TEXT NOT NULL
UNIQUE(source, source_symbol)
```

### 6.3 `bars`

Canonical K-line table.

```text
instrument_id TEXT NOT NULL
timestamp TEXT NOT NULL
local_date TEXT NOT NULL
interval TEXT NOT NULL
source TEXT NOT NULL
adjustment TEXT NOT NULL
open REAL NOT NULL
high REAL NOT NULL
low REAL NOT NULL
close REAL NOT NULL
volume REAL
amount REAL
currency TEXT
is_complete INTEGER NOT NULL DEFAULT 1
provider_payload_hash TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
UNIQUE(instrument_id, interval, timestamp, source, adjustment)
```

Rules:

- `timestamp` is ISO-8601 UTC for storage.
- `local_date` is exchange-local date for daily grouping and reports.
- `interval` uses fixed values: `1m`, `5m`, `15m`, `30m`, `1h`, `1d`, `1w`, `1mo`.
- `adjustment` uses fixed values: `raw`, `split_adjusted`, `total_return_adjusted`.
- `amount` is turnover. If the provider does not provide it, it may be calculated as `volume * mean(open, high, low, close)` and marked in feature metadata when used.
- `is_complete = 0` is allowed for live or still-forming bars, but Kronos and daily strategies use only complete bars by default.

### 6.4 `feed_runs`

Tracks sync attempts.

```text
run_id TEXT PRIMARY KEY
source TEXT NOT NULL
purpose TEXT NOT NULL
started_at TEXT NOT NULL
ended_at TEXT
status TEXT NOT NULL
requested_symbols_json TEXT
requested_interval TEXT
requested_start TEXT
requested_end TEXT
rows_fetched INTEGER DEFAULT 0
rows_inserted INTEGER DEFAULT 0
rows_updated INTEGER DEFAULT 0
error_message TEXT
metadata_json TEXT
```

### 6.5 `data_quality_issues`

Stores validation failures and warnings.

```text
issue_id TEXT PRIMARY KEY
run_id TEXT
instrument_id TEXT
interval TEXT
timestamp TEXT
severity TEXT NOT NULL
issue_type TEXT NOT NULL
details_json TEXT NOT NULL
created_at TEXT NOT NULL
```

Validation checks:

- Missing required OHLC fields.
- Negative prices or volume.
- `high < max(open, close)` or `low > min(open, close)`.
- Duplicate bars for the same source and timestamp.
- Suspicious gaps relative to the exchange calendar.
- Extreme returns beyond configured thresholds.
- Incomplete bar accidentally used for historical analysis.

## 7. Multi-Period K-Line Design

### 7.1 Store provider bars and derived bars consistently

Daily and intraday bars use the same `bars` table. Derived bars are stored with `source = derived:<base_source>` and metadata in `bar_derivations`.

### 7.2 `bar_derivations`

Tracks resampling lineage.

```text
derivation_id TEXT PRIMARY KEY
instrument_id TEXT NOT NULL
source_interval TEXT NOT NULL
target_interval TEXT NOT NULL
source TEXT NOT NULL
target_source TEXT NOT NULL
start_timestamp TEXT NOT NULL
end_timestamp TEXT NOT NULL
method TEXT NOT NULL
created_at TEXT NOT NULL
metadata_json TEXT
```

Resampling rules:

- `open` is first open in the target window.
- `high` is max high.
- `low` is min low.
- `close` is last close.
- `volume` and `amount` are sums.
- Target bars must align to exchange sessions, not naive wall-clock windows.

### 7.3 Period selection

Initial supported periods:

- `1d` for MVP prediction and daily monitoring.
- `1w` derived from `1d` for medium-term context.
- `5m` and `1h` added only after a stable intraday source exists.

Kronos can run on any interval if the input bars are complete, regularly ordered, and long enough. Strategy and LLM contexts should always include the interval used.

## 8. Kronos Compatibility

### 8.1 Required input view

Kronos receives a DataFrame sorted ascending by timestamp:

```text
index: timestamp
columns: open, high, low, close, volume, amount
```

`amount` is optional for the current Kronos adapter because the vendor predictor can derive it from volume and price. The internal view should still include it when available.

### 8.2 `KronosInputFrame` rules

The loader must:

- Select one instrument, one interval, one adjustment mode, and one source preference chain.
- Use only complete bars.
- Sort ascending by timestamp.
- Remove duplicate timestamps after source priority resolution.
- Reject rows with null price fields.
- Preserve a timestamp series for Kronos time features.
- Limit lookback to model context, currently 512 for small/base models, while allowing longer history to remain in storage.

Example:

```python
df = storage.load_kronos_frame(
    instrument_id="EQUITY:US:AAPL",
    interval="1d",
    adjustment="split_adjusted",
    lookback=512,
)
```

### 8.3 Prediction output storage

Kronos predictions should not be stored in `bars`. They belong to prediction tables:

```text
prediction_runs
  run_id, model_name, model_variant, instrument_id, interval,
  lookback_start, lookback_end, horizon, source_selection_json,
  created_at, metadata_json

predicted_bars
  run_id, forecast_timestamp, step,
  open, high, low, close, volume, amount,
  confidence, created_at
```

This lets later evaluation compare predicted bars to realized bars without confusing forecasts with market facts.

## 9. Technical Features and Signals

### 9.1 Separate features from signals

Features are numeric time series, such as `ma_5`, `ma_20`, `rsi_14`, `macd`, `bb_upper`, and `volume_zscore`.

Signals are interpreted events, such as `golden_cross`, `death_cross`, `rsi_overbought`, `volume_spike`, or `breakout_above_resistance`.

### 9.2 `technical_features`

```text
instrument_id TEXT NOT NULL
timestamp TEXT NOT NULL
interval TEXT NOT NULL
feature_name TEXT NOT NULL
feature_value REAL
window TEXT
params_json TEXT
input_range_start TEXT NOT NULL
input_range_end TEXT NOT NULL
created_at TEXT NOT NULL
UNIQUE(instrument_id, interval, timestamp, feature_name, params_json)
```

Examples:

```text
ma_close_5
ma_close_20
ema_close_12
ema_close_26
rsi_14
macd_line
macd_signal
macd_hist
bb_upper_20_2
bb_lower_20_2
atr_14
volume_zscore_20
```

### 9.3 `technical_signals`

```text
signal_id TEXT PRIMARY KEY
instrument_id TEXT NOT NULL
timestamp TEXT NOT NULL
interval TEXT NOT NULL
signal_type TEXT NOT NULL
direction TEXT NOT NULL
strength REAL NOT NULL
confidence REAL
severity TEXT NOT NULL
summary TEXT NOT NULL
evidence_json TEXT NOT NULL
input_range_start TEXT NOT NULL
input_range_end TEXT NOT NULL
created_at TEXT NOT NULL
```

Example golden cross signal:

```json
{
  "signal_type": "golden_cross",
  "direction": "bullish",
  "strength": 0.72,
  "confidence": 0.81,
  "severity": "watch",
  "summary": "MA5 crossed above MA20 on 1d bars with rising volume.",
  "evidence": {
    "fast_ma": "ma_close_5",
    "slow_ma": "ma_close_20",
    "previous_fast": 182.1,
    "previous_slow": 183.0,
    "current_fast": 184.2,
    "current_slow": 183.6,
    "volume_zscore_20": 1.4
  }
}
```

Rules:

- Golden cross is a signal, not a column in `bars`.
- Signal computation must record the input range used.
- A signal is immutable once stored. If a formula changes, recompute under a new strategy version.

## 10. Sentiment and Events

### 10.1 Text source storage

Text data should be stored as observations with provenance. The first implementation can ingest CSV or manual samples; future providers can ingest news APIs, social media, earnings call transcripts, filings, and announcement feeds.

### 10.2 `text_observations`

```text
observation_id TEXT PRIMARY KEY
source TEXT NOT NULL
source_type TEXT NOT NULL
instrument_id TEXT
published_at TEXT NOT NULL
collected_at TEXT NOT NULL
title TEXT
url TEXT
language TEXT
text_hash TEXT NOT NULL
text_excerpt TEXT
raw_payload_json TEXT
```

`source_type` values:

```text
news, filing, announcement, social, research_note, earnings_call, macro_release
```

### 10.3 `sentiment_scores`

```text
sentiment_id TEXT PRIMARY KEY
observation_id TEXT NOT NULL
instrument_id TEXT
model_name TEXT NOT NULL
model_version TEXT NOT NULL
sentiment_score REAL NOT NULL
confidence REAL
labels_json TEXT
rationale TEXT
created_at TEXT NOT NULL
```

Rules:

- `sentiment_score` ranges from `-1.0` to `1.0`.
- Store model name and version because sentiment models will change.
- Store a short rationale for LLM context, but keep raw long text outside prompts unless specifically needed.
- Use `published_at` for market timing. `collected_at` is only ingestion metadata.

### 10.4 `market_events`

Events are structured facts that may come from text or explicit APIs.

```text
event_id TEXT PRIMARY KEY
instrument_id TEXT
event_type TEXT NOT NULL
event_time TEXT NOT NULL
source TEXT NOT NULL
title TEXT NOT NULL
summary TEXT
impact_direction TEXT
impact_score REAL
confidence REAL
evidence_refs_json TEXT
created_at TEXT NOT NULL
```

Event types:

```text
earnings_release, earnings_call, dividend, split, buyback,
guidance_change, regulatory_filing, macro_release, price_spike,
volume_anomaly, analyst_rating_change, sector_news
```

## 11. Fundamentals and Macro

### 11.1 Fundamentals

Fundamental data should be point-in-time where possible.

```text
fundamental_snapshots
  instrument_id, period_end, report_date, source,
  metric_name, metric_value, unit, currency,
  created_at
```

Examples:

```text
revenue, net_income, eps, pe_ttm, pb, roe, gross_margin,
debt_to_equity, operating_cash_flow
```

### 11.2 Macro series

```text
macro_series
  series_id, name, region, source, frequency, unit

macro_observations
  series_id, observation_time, release_time,
  value, previous_value, revised_from,
  created_at
```

LLM and strategy layers should use `release_time` to avoid using data before it was publicly available.

## 12. LLM Analysis Context

### 12.1 LLM should consume summaries, not raw tables

LLM prompts should receive compact, structured snapshots. The data layer should provide an `AnalysisContext` object assembled from bars, predictions, technical signals, sentiment, events, fundamentals, macro data, and quality notes.

### 12.2 `AnalysisContext` shape

```json
{
  "as_of": "2026-05-23T08:00:00Z",
  "instrument": {
    "instrument_id": "EQUITY:US:AAPL",
    "symbol": "AAPL",
    "market": "US",
    "currency": "USD"
  },
  "price_state": {
    "interval": "1d",
    "last_close": 190.12,
    "return_1d": 0.018,
    "return_5d": 0.043,
    "return_20d": -0.021,
    "volume_zscore_20": 1.4
  },
  "kronos_prediction": {
    "model": "kronos-small",
    "interval": "1d",
    "horizon": 5,
    "expected_direction": "up",
    "forecast_close_min": 188.4,
    "forecast_close_max": 197.2,
    "confidence": 0.68,
    "run_id": "pred_..."
  },
  "technical_signals": [
    {
      "type": "golden_cross",
      "direction": "bullish",
      "strength": 0.72,
      "summary": "MA5 crossed above MA20 with rising volume.",
      "evidence_ref": "signal_..."
    }
  ],
  "sentiment": {
    "window": "3d",
    "mean_score": 0.22,
    "confidence": 0.7,
    "top_drivers": [
      {
        "source_type": "news",
        "published_at": "2026-05-22T13:30:00Z",
        "summary": "Positive product demand commentary.",
        "evidence_ref": "obs_..."
      }
    ]
  },
  "events": [
    {
      "type": "earnings_release",
      "event_time": "2026-05-21T20:00:00Z",
      "summary": "Revenue beat consensus and guidance was raised.",
      "impact_direction": "bullish",
      "evidence_ref": "event_..."
    }
  ],
  "data_quality": {
    "status": "ok",
    "notes": []
  }
}
```

### 12.3 Anti-hallucination requirements

Every LLM-facing summary should include evidence references. If the context has no news, no fundamentals, or incomplete bars, the LLM context should say so explicitly. Missing data is a fact, not an invitation to infer.

## 13. Anti-Lookahead Rules

Backtests, model evaluation, and LLM historical reports must use `as_of` semantics:

- A bar is usable only after its period is complete.
- News and sentiment are usable only after `published_at`.
- Fundamentals are usable only after `report_date` or actual release timestamp.
- Macro data is usable only after `release_time`.
- Revised macro/fundamental values must retain original and revised values.
- Predictions are evaluated against realized bars only after those bars exist.

These rules matter more than model sophistication. Without them, the system can look accurate in backtests while being unusable in live monitoring.

## 14. Module Design

### 14.1 Proposed files

```text
src/openstockagent/data/
  feeds/
    base.py
    yahoo.py
    akshare.py
    csv_feed.py
    registry.py
  normalize.py
  validate.py
  storage.py
  symbols.py
  quality.py

src/openstockagent/features/
  technical.py

src/openstockagent/signals/
  technical.py

src/openstockagent/context/
  analysis_context.py

src/openstockagent/pipelines/
  sync_market_data.py
  build_features.py
  build_analysis_context.py
```

### 14.2 Feed interface

```python
class BaseMarketDataFeed:
    source: str

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
```

The feed returns provider-normalized columns, but canonical IDs and final validation are handled by the data layer.

### 14.3 Storage interface

```python
class MarketDataStorage:
    def upsert_bars(self, bars: pd.DataFrame) -> int: ...
    def load_bars(self, instrument_id: str, interval: str, start: str, end: str) -> pd.DataFrame: ...
    def load_kronos_frame(self, instrument_id: str, interval: str, lookback: int) -> pd.DataFrame: ...
    def save_prediction_run(self, run: PredictionRun, predicted_bars: pd.DataFrame) -> str: ...
    def save_technical_features(self, features: pd.DataFrame) -> int: ...
    def save_technical_signals(self, signals: list[TechnicalSignal]) -> int: ...
```

## 15. Pipeline Design

### 15.1 Sync bars

```text
resolve instrument
  -> choose source from FeedRegistry
  -> fetch bars
  -> normalize provider fields
  -> validate bars
  -> write feed_run
  -> upsert bars
  -> write quality issues
```

### 15.2 Build technical features and signals

```text
load canonical bars
  -> compute features per interval
  -> save technical_features
  -> derive signals such as golden_cross and volume_spike
  -> save technical_signals
```

### 15.3 Run Kronos prediction

```text
load KronosInputFrame from canonical bars
  -> run Kronos
  -> save prediction_run
  -> save predicted_bars
```

### 15.4 Build LLM context

```text
load latest bars and returns
  -> load latest prediction run
  -> load active technical signals
  -> aggregate sentiment window
  -> load relevant events, fundamentals, macro observations
  -> attach data quality notes
  -> return AnalysisContext JSON
```

## 16. Testing Strategy

Unit tests:

- `CsvFeed` loads deterministic bars.
- Normalizer maps provider columns to canonical columns.
- Validator detects invalid OHLC rows and duplicate timestamps.
- Storage upserts bars idempotently.
- Kronos frame loader returns correct sorted columns and lookback.
- Golden cross signal detects a known fixture.
- LLM context builder includes evidence refs and missing-data notes.

Integration tests:

- Yahoo fetch smoke test, marked as network.
- AKShare fetch smoke test, marked as network.
- Kronos prediction smoke test, marked as slow/model.

Default test runs should not require network or model downloads.

## 17. Migration Plan

Current state:

- `BaseDataFeed.fetch_ohlcv(symbol, period)` returns OHLCV.
- `SQLiteStorage` stores `ohlcv(symbol, date, open, high, low, close, volume)`.
- `run_prediction.py` fetches Yahoo data directly and runs Kronos.

Migration steps:

1. Add new canonical tables while keeping existing `ohlcv` temporarily.
2. Implement `CsvFeed` and canonical `MarketDataStorage` tests first.
3. Migrate Yahoo feed to `BaseMarketDataFeed.fetch_bars`.
4. Add `FeedRegistry` and symbol alias mapping.
5. Update prediction pipeline to load `KronosInputFrame` from storage.
6. Add prediction tables and persist Kronos outputs.
7. Add technical features and golden cross/death cross signals.
8. Add `AnalysisContext` builder with empty sentiment/events support.
9. Add AKShare feed.
10. Deprecate old `ohlcv` table after the new `bars` path is stable.

## 18. Initial Implementation Boundary

The first implementation should include:

- `instruments`, `instrument_aliases`, `bars`, `feed_runs`, `data_quality_issues`.
- `CsvFeed`, migrated `YahooFinanceFeed`, and `FeedRegistry`.
- `load_kronos_frame`.
- `prediction_runs` and `predicted_bars`.
- `technical_features` and `technical_signals` for MA5/MA20 golden cross and death cross.
- `AnalysisContext` with price state, prediction summary, technical signals, data quality notes, and explicit empty sections for sentiment/events/fundamentals/macro.

The first implementation should not include:

- Paid data providers.
- Realtime streaming.
- Full news ingestion.
- Full macro and fundamental ingestion.
- LLM API calls.
- Frontend changes.

This boundary creates a useful local-first data core while leaving clean extension points for richer market context later.
