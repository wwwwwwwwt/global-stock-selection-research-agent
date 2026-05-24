from pathlib import Path

from openstockagent.database.mysql import MySQLConfig
from openstockagent.universe.builders import load_universe_csv
from openstockagent.universe.models import Universe, UniverseMember
from openstockagent.universe.storage import MySQLUniverseStorage


def test_mysql_universe_storage_creates_required_tables():
    factory = FakeConnectionFactory()
    config = MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/", "root", "123456")

    MySQLUniverseStorage(config=config, connection_factory=factory)

    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS universes" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS universe_members" in executed_sql
    assert "PRIMARY KEY (universe_id, instrument_id, start_date)" in executed_sql


def test_upsert_and_load_time_aware_universe_members():
    factory = FakeConnectionFactory(
        rows=[
            {
                "universe_id": "cn_sample",
                "instrument_id": "EQUITY:CN:600519",
                "start_date": "2024-01-01",
                "end_date": None,
                "reason": "fixture leader",
            }
        ]
    )
    storage = MySQLUniverseStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/", "root", "123456"),
        connection_factory=factory,
    )
    universe = Universe(
        universe_id="cn_sample",
        name="CN Sample",
        market="CN",
        asset_type="equity",
        description="Deterministic test universe",
    )
    members = [
        UniverseMember(
            universe_id="cn_sample",
            instrument_id="EQUITY:CN:600519",
            start_date="2024-01-01",
            end_date=None,
            reason="fixture leader",
        )
    ]

    storage.upsert_universe(universe)
    storage.upsert_universe_members(members)
    loaded = storage.load_universe_members("cn_sample", as_of="2024-05-24")

    executed_sql = "\n".join(factory.executed_sql)
    assert "ON DUPLICATE KEY UPDATE" in executed_sql
    assert "start_date <= %s" in executed_sql
    assert loaded == members


def test_load_universe_csv_fixture():
    universe, members = load_universe_csv(
        Path("tests/fixtures/cn_sample_universe.csv"),
        universe_id="cn_sample",
        name="CN Sample",
        market="CN",
        asset_type="equity",
    )

    assert universe.universe_id == "cn_sample"
    assert [member.instrument_id for member in members] == ["EQUITY:CN:600519", "EQUITY:CN:000001"]
    assert members[0].start_date == "2024-01-01"


class FakeConnectionFactory:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed_sql = []
        self.executed_params = []

    def __call__(self, config):
        self.config = config
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

    def fetchall(self):
        return self.factory.rows
