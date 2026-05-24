import sqlite3

from openstockagent.data.sqlite_migration import migrate_sqlite_market_data


def test_sqlite_migration_moves_canonical_bars_and_skips_legacy_ohlcv(temp_db_path):
    with sqlite3.connect(temp_db_path) as conn:
        conn.execute(
            """CREATE TABLE instruments (
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
            )"""
        )
        conn.execute(
            """CREATE TABLE instrument_aliases (
                instrument_id TEXT NOT NULL,
                source TEXT NOT NULL,
                source_symbol TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE bars (
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
                updated_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE ohlcv (
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL
            )"""
        )
        conn.execute(
            """INSERT INTO instruments VALUES (
                'EQUITY:US:AAPL', 'AAPL', 'US', 'NASDAQ', 'equity', 'USD',
                'Apple Inc.', 'America/New_York', 1, NULL, '2024-01-01', '2024-01-01'
            )"""
        )
        conn.execute(
            """INSERT INTO instrument_aliases VALUES (
                'EQUITY:US:AAPL', 'polygon', 'AAPL', 1, '2024-01-01'
            )"""
        )
        conn.execute(
            """INSERT INTO bars VALUES (
                'EQUITY:US:AAPL', '2024-01-02T21:00:00Z', '2024-01-02', '1d',
                'polygon', 'split_adjusted', 100, 103, 99, 102, 1000, 101000,
                'USD', 1, NULL, '2024-01-02', '2024-01-02'
            )"""
        )
        conn.execute("INSERT INTO ohlcv VALUES ('AAPL', '2024-01-02', 100, 103, 99, 102, 1000)")

    target = FakeMigrationTarget()

    result = migrate_sqlite_market_data(temp_db_path, target)

    assert result.instruments == 1
    assert result.aliases == 1
    assert result.bars == 1
    assert result.legacy_ohlcv_rows_skipped == 1
    assert target.instruments[0].instrument_id == "EQUITY:US:AAPL"
    assert target.aliases[0].source_symbol == "AAPL"
    assert target.bars[0].iloc[0]["source"] == "polygon"


class FakeMigrationTarget:
    def __init__(self):
        self.instruments = []
        self.aliases = []
        self.bars = []
        self.feed_runs = []
        self.issues = []
        self.predictions = []
        self.signals = []

    def upsert_instrument(self, instrument):
        self.instruments.append(instrument)

    def upsert_instrument_alias(self, alias):
        self.aliases.append(alias)

    def upsert_bars(self, bars):
        self.bars.append(bars)
        return len(bars)

    def upsert_feed_run_records(self, records):
        self.feed_runs.extend(records)
        return len(records)

    def upsert_data_quality_issue_records(self, records):
        self.issues.extend(records)
        return len(records)

    def save_prediction_run(self, run, predicted_bars):
        self.predictions.append((run, predicted_bars))
        return run.run_id

    def save_technical_signals(self, signals):
        self.signals.extend(signals)
        return len(signals)
