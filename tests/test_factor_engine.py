import json

import pandas as pd
import pytest

from openstockagent.database.mysql import MySQLConfig
from openstockagent.factors.cross_section import add_cross_section_scores
from openstockagent.factors.definitions import DEFAULT_FACTOR_DEFINITIONS
from openstockagent.factors.engine import compute_universe_factors
from openstockagent.factors.models import FactorValue
from openstockagent.factors.storage import MySQLFactorStorage
from openstockagent.factors.technical import compute_technical_factors
from openstockagent.universe.models import UniverseMember


def test_default_factor_definitions_cover_initial_mvp_set():
    names = {definition.factor_name for definition in DEFAULT_FACTOR_DEFINITIONS}

    assert names == {
        "return_5d",
        "return_20d",
        "return_60d",
        "ma_trend_score",
        "ma_slope_20d",
        "volume_expansion_20d",
        "atr_14d",
        "max_drawdown_20d",
        "turnover_amount_20d",
    }
    assert {definition.version for definition in DEFAULT_FACTOR_DEFINITIONS} == {"v1"}
    assert {definition.direction for definition in DEFAULT_FACTOR_DEFINITIONS} <= {"higher_better", "lower_better"}


def test_compute_technical_factors_filters_future_bars_and_adds_evidence():
    bars = _sample_bars(periods=70)
    future = bars.iloc[[-1]].copy()
    future["timestamp"] = "2024-06-30T00:00:00Z"
    future["local_date"] = "2024-06-30"
    future["close"] = 9999.0
    bars = pd.concat([bars.iloc[:-1], future], ignore_index=True)
    as_of = bars.iloc[-2]["local_date"]
    as_of_close = bars.iloc[-2]["close"]
    close_5d_ago = bars.iloc[-7]["close"]

    factors = compute_technical_factors("EQUITY:CN:600519", bars, trade_date=as_of, interval="1d")
    by_name = {factor.factor_name: factor for factor in factors}

    assert set(by_name) == {definition.factor_name for definition in DEFAULT_FACTOR_DEFINITIONS}
    assert by_name["return_5d"].factor_value == pytest.approx(as_of_close / close_5d_ago - 1.0)
    assert by_name["turnover_amount_20d"].factor_value < 9999.0 * 9999.0
    evidence = json.loads(by_name["return_5d"].evidence_json)
    assert evidence["lookback_days"] == 5
    assert evidence["end_timestamp"] == bars.iloc[-2]["timestamp"]


def test_cross_section_scores_respect_factor_direction():
    values = [
        FactorValue("A", "2024-05-24", "1d", "return_5d", 0.01, version="v1", evidence_json="{}"),
        FactorValue("B", "2024-05-24", "1d", "return_5d", 0.03, version="v1", evidence_json="{}"),
        FactorValue("C", "2024-05-24", "1d", "return_5d", -0.01, version="v1", evidence_json="{}"),
        FactorValue("A", "2024-05-24", "1d", "atr_14d", 0.03, version="v1", evidence_json="{}"),
        FactorValue("B", "2024-05-24", "1d", "atr_14d", 0.01, version="v1", evidence_json="{}"),
        FactorValue("C", "2024-05-24", "1d", "atr_14d", 0.02, version="v1", evidence_json="{}"),
    ]

    scored = add_cross_section_scores(values)
    scored_by_key = {(value.instrument_id, value.factor_name): value for value in scored}

    assert scored_by_key[("B", "return_5d")].percentile == pytest.approx(1.0)
    assert scored_by_key[("C", "return_5d")].percentile == pytest.approx(1 / 3)
    assert scored_by_key[("B", "atr_14d")].percentile == pytest.approx(1.0)
    assert scored_by_key[("A", "atr_14d")].percentile == pytest.approx(1 / 3)
    assert scored_by_key[("B", "return_5d")].zscore is not None


def test_mysql_factor_storage_creates_upserts_and_loads_values():
    factory = FakeConnectionFactory(
        rows=[
            {
                "instrument_id": "EQUITY:CN:600519",
                "trade_date": "2024-05-24",
                "interval": "1d",
                "factor_name": "return_5d",
                "factor_value": 0.05,
                "percentile": 1.0,
                "zscore": 0.7,
                "version": "v1",
                "evidence_json": "{}",
            }
        ]
    )
    storage = MySQLFactorStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
    )

    storage.upsert_factor_definitions(DEFAULT_FACTOR_DEFINITIONS)
    storage.upsert_factor_values(
        [
            FactorValue(
                "EQUITY:CN:600519",
                "2024-05-24",
                "1d",
                "return_5d",
                0.05,
                percentile=1.0,
                zscore=0.7,
                version="v1",
                evidence_json="{}",
            )
        ]
    )
    loaded = storage.load_factor_values("2024-05-24", "1d")

    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS factor_definitions" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS factor_values" in executed_sql
    assert "bar_interval VARCHAR(16) NOT NULL" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql
    assert loaded[0].factor_name == "return_5d"
    assert loaded[0].percentile == 1.0


def test_compute_universe_factors_returns_cross_sectional_values_for_members_only():
    members = [
        UniverseMember("cn_sample", "EQUITY:CN:600519", "2024-01-01"),
        UniverseMember("cn_sample", "EQUITY:CN:000001", "2024-01-01"),
    ]
    first = _sample_bars(periods=70)
    second = _sample_bars(periods=70)
    second["close"] = second["close"] * 0.9
    second["amount"] = second["close"] * second["volume"]
    bars_by_instrument = {
        "EQUITY:CN:600519": first,
        "EQUITY:CN:000001": second,
        "EQUITY:CN:999999": _sample_bars(periods=70),
    }
    trade_date = first.iloc[-1]["local_date"]

    values = compute_universe_factors(members, bars_by_instrument, trade_date=trade_date, interval="1d")

    instruments = {value.instrument_id for value in values}
    assert instruments == {"EQUITY:CN:600519", "EQUITY:CN:000001"}
    assert len(values) == len(DEFAULT_FACTOR_DEFINITIONS) * 2
    assert all(value.percentile is not None for value in values)


def _sample_bars(periods: int) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=periods)
    close = pd.Series([100.0 + i for i in range(periods)])
    volume = pd.Series([1000.0 + i * 10 for i in range(periods)])
    return pd.DataFrame(
        {
            "timestamp": dates.strftime("%Y-%m-%dT00:00:00Z"),
            "local_date": dates.strftime("%Y-%m-%d"),
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": volume,
            "amount": close * volume,
        }
    )


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
