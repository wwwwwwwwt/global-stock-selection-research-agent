from openstockagent.database.mysql import MySQLConfig
from openstockagent.market.calendar import add_trading_days
from openstockagent.market.models import CorporateAction, InstrumentStatus, TradingCalendarDay
from openstockagent.market.storage import MySQLMarketRealityStorage


def test_calendar_helper_uses_stored_trading_days_before_business_day_fallback():
    storage = FakeCalendarStorage(next_date="2026-05-30")

    assert add_trading_days("2026-05-22", 5, calendar_storage=storage, market="US") == "2026-05-30"
    assert storage.calls == [("US", "2026-05-22", 5)]
    assert add_trading_days("2026-05-22", 5) == "2026-05-29"


def test_market_reality_models_convert_booleans_to_records():
    day = TradingCalendarDay("US", "2026-05-25", False, session_type="holiday")
    status = InstrumentStatus("EQUITY:CN:600519", "2026-05-25", "suspended", False, is_st=True, is_suspended=True)
    action = CorporateAction("ca-test", "EQUITY:US:AAPL", "2026-05-25", "2026-05-26", "split", split_ratio=2.0)

    assert day.to_record()["is_trading_day"] == 0
    assert status.to_record()["is_tradable"] == 0
    assert status.to_record()["is_st"] == 1
    assert action.to_record()["split_ratio"] == 2.0


def test_mysql_market_reality_storage_creates_upserts_and_loads_status():
    factory = FakeConnectionFactory(
        fetchone_row={
            "instrument_id": "EQUITY:CN:600519",
            "status_date": "2026-05-25",
            "status": "active",
            "is_tradable": 1,
            "is_st": 0,
            "is_suspended": 0,
            "limit_up": 102.0,
            "limit_down": 98.0,
            "reason_json": "{}",
        }
    )
    storage = MySQLMarketRealityStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
    )

    storage.upsert_trading_calendar_days([TradingCalendarDay("CN", "2026-05-25", True)])
    storage.upsert_instrument_statuses(
        [InstrumentStatus("EQUITY:CN:600519", "2026-05-25", "active", True, limit_up=102.0, limit_down=98.0)]
    )
    storage.upsert_corporate_actions(
        [CorporateAction("ca-test", "EQUITY:CN:600519", "2026-05-25", None, "dividend", cash_amount=1.0)]
    )
    status = storage.load_instrument_status("EQUITY:CN:600519", "2026-05-25")

    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS trading_calendar" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS instrument_status" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS corporate_actions" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql
    assert status is not None
    assert status.is_tradable is True
    assert status.limit_up == 102.0


class FakeCalendarStorage:
    def __init__(self, next_date):
        self.next_date = next_date
        self.calls = []

    def next_trading_date(self, market, start_date, offset):
        self.calls.append((market, start_date, offset))
        return self.next_date


class FakeConnectionFactory:
    def __init__(self, fetchone_row=None, fetchall_rows=None):
        self.fetchone_row = fetchone_row
        self.fetchall_rows = fetchall_rows or []
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
        return 1

    def executemany(self, sql, params):
        self.factory.executed_sql.append(sql)
        self.factory.executed_params.extend(params)

    def fetchone(self):
        return self.factory.fetchone_row

    def fetchall(self):
        return self.factory.fetchall_rows

