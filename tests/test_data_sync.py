import pandas as pd

from openstockagent.data.feeds.registry import FeedRegistry
from openstockagent.data.sync import build_sync_plan, run_data_sync_plan
from openstockagent.data.sync_storage import MySQLDataSyncStorage
from openstockagent.database.mysql import MySQLConfig
from openstockagent.universe.models import UniverseMember


def test_run_data_sync_plan_fetches_backfill_window_and_persists_run():
    plan = build_sync_plan(universe_id="us_core", market="US", mode="backfill", lookback_years=3)
    universe_storage = FakeUniverseStorage(
        [
            UniverseMember("us_core", "EQUITY:US:AAPL", "2024-01-01"),
            UniverseMember("us_core", "EQUITY:US:MSFT", "2024-01-01"),
        ]
    )
    bar_storage = FakeBarStorage()
    feed = FakeFeed("polygon")
    registry = FeedRegistry()
    registry.register("US", "equity", "1d", feed)
    sync_storage = FakeSyncStorage()

    result = run_data_sync_plan(
        plan,
        as_of="2026-05-25",
        universe_storage=universe_storage,
        bar_storage=bar_storage,
        feed_registry=registry,
        sync_storage=sync_storage,
    )

    assert result.period == "3y"
    assert feed.calls == [("AAPL", "1d", "3y"), ("MSFT", "1d", "3y")]
    assert result.members_seen == 2
    assert result.instruments_fetched == 2
    assert result.bars_written == 4
    assert result.status == "completed"
    assert sync_storage.plans == [plan]
    assert sync_storage.runs == [result]


def test_run_data_sync_plan_uses_incremental_repair_window_and_max_symbols():
    plan = build_sync_plan(universe_id="cn_core", market="CN", mode="incremental", incremental_days=10)
    universe_storage = FakeUniverseStorage(
        [
            UniverseMember("cn_core", "EQUITY:CN:600519", "2024-01-01"),
            UniverseMember("cn_core", "EQUITY:CN:000001", "2024-01-01"),
        ]
    )
    feed = FakeFeed("akshare")
    registry = FeedRegistry()
    registry.register("CN", "equity", "1d", feed)

    result = run_data_sync_plan(
        plan,
        as_of="2026-05-25",
        universe_storage=universe_storage,
        bar_storage=FakeBarStorage(),
        feed_registry=registry,
        max_symbols=1,
    )

    assert result.period == "10d"
    assert result.members_seen == 1
    assert feed.calls == [("600519", "1d", "10d")]


def test_run_data_sync_plan_retries_transient_fetch_errors():
    plan = build_sync_plan(universe_id="us_core", market="US", mode="incremental")
    universe_storage = FakeUniverseStorage([UniverseMember("us_core", "EQUITY:US:AAPL", "2024-01-01")])
    feed = FlakyFeed("polygon")
    registry = FeedRegistry()
    registry.register("US", "equity", "1d", feed)

    result = run_data_sync_plan(
        plan,
        as_of="2026-05-25",
        universe_storage=universe_storage,
        bar_storage=FakeBarStorage(),
        feed_registry=registry,
        max_attempts=2,
        retry_sleep_seconds=0,
    )

    assert feed.attempts == 2
    assert result.instruments_fetched == 1
    assert result.failed_instruments == 0
    assert result.status == "completed"


def test_mysql_data_sync_storage_creates_and_writes_plans_and_runs():
    factory = FakeConnectionFactory()
    storage = MySQLDataSyncStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
    )
    plan = build_sync_plan(universe_id="us_core", market="US", mode="incremental")
    result = run_data_sync_plan(
        plan,
        as_of="2026-05-25",
        universe_storage=FakeUniverseStorage([UniverseMember("us_core", "EQUITY:US:AAPL", "2024-01-01")]),
        bar_storage=FakeBarStorage(),
        feed_registry=_registry("US", "polygon"),
    )

    storage.upsert_plan(plan)
    storage.save_run(result)

    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS data_sync_plans" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS data_sync_runs" in executed_sql
    assert "bar_interval VARCHAR(16) NOT NULL" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql


def _registry(market, source):
    registry = FeedRegistry()
    registry.register(market, "equity", "1d", FakeFeed(source))
    return registry


class FakeUniverseStorage:
    def __init__(self, members):
        self.members = members

    def load_universe_members(self, universe_id, as_of=None):
        return self.members


class FakeBarStorage:
    def __init__(self):
        self.frames = []

    def upsert_bars(self, bars):
        self.frames.append(bars.copy())
        return len(bars)


class FakeFeed:
    def __init__(self, source):
        self.source = source
        self.calls = []

    def fetch_bars(self, source_symbol, interval, start=None, end=None, period=None, adjusted=True):
        self.calls.append((source_symbol, interval, period))
        return pd.DataFrame(
            {
                "timestamp": ["2026-05-22T00:00:00Z", "2026-05-25T00:00:00Z"],
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1000.0, 1200.0],
                "amount": [101000.0, 122400.0],
            }
        )


class FlakyFeed(FakeFeed):
    def __init__(self, source):
        super().__init__(source)
        self.attempts = 0

    def fetch_bars(self, *args, **kwargs):
        self.attempts += 1
        if self.attempts == 1:
            raise ConnectionError("temporary upstream disconnect")
        return super().fetch_bars(*args, **kwargs)


class FakeSyncStorage:
    def __init__(self):
        self.plans = []
        self.runs = []

    def upsert_plan(self, plan):
        self.plans.append(plan)

    def save_run(self, result):
        self.runs.append(result)


class FakeConnectionFactory:
    def __init__(self):
        self.executed_sql = []
        self.executed_params = []

    def __call__(self, config):
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, factory):
        self.factory = factory

    def cursor(self):
        return FakeCursor(self.factory)

    def commit(self):
        pass

    def close(self):
        pass


class FakeCursor:
    def __init__(self, factory):
        self.factory = factory

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        pass

    def execute(self, sql, params=None):
        self.factory.executed_sql.append(sql)
        self.factory.executed_params.append(params)

    def executemany(self, sql, params):
        self.factory.executed_sql.append(sql)
        self.factory.executed_params.extend(params)
