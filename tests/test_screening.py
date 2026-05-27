import json

from openstockagent.database.mysql import MySQLConfig
from openstockagent.factors.models import FactorValue
from openstockagent.market.models import InstrumentStatus
from openstockagent.universe.models import UniverseMember


def test_rank_screen_candidates_applies_filters_and_scores_missing_optional_factors_neutral():
    try:
        from openstockagent.screening.scoring import build_default_strategy, rank_screen_candidates
    except ModuleNotFoundError as exc:
        raise AssertionError(f"missing screening scoring module: {exc}") from exc

    members = [
        UniverseMember("us_sample", "EQUITY:US:AAPL", "2024-01-01"),
        UniverseMember("us_sample", "EQUITY:US:MSFT", "2024-01-01"),
        UniverseMember("us_sample", "EQUITY:US:ILLQ", "2024-01-01"),
    ]
    values = [
        *_factor_set("EQUITY:US:AAPL", momentum=0.65, trend=0.60, volume=0.55, volatility=0.55, turnover=2_500_000),
        *_factor_set("EQUITY:US:MSFT", momentum=0.90, trend=0.85, volume=0.80, volatility=0.70, turnover=4_000_000),
        *_factor_set("EQUITY:US:ILLQ", momentum=0.99, trend=0.99, volume=0.99, volatility=0.99, turnover=100_000),
    ]
    strategy = build_default_strategy(
        hard_filters={"min_turnover_amount_20d": 1_000_000, "min_bar_count": 60},
        max_candidates=10,
    )

    results = rank_screen_candidates("screen-test", members, values, strategy)

    assert [result.instrument_id for result in results] == ["EQUITY:US:MSFT", "EQUITY:US:AAPL"]
    assert [result.rank for result in results] == [1, 2]
    assert all(result.selected for result in results)

    leader_breakdown = json.loads(results[0].score_breakdown_json)
    assert leader_breakdown["theory_score"]["score"] == 0.5
    assert leader_breakdown["market_context_score"]["score"] == 0.5
    assert leader_breakdown["kronos_score"]["score"] == 0.5
    assert results[0].total_score > results[1].total_score

    reasons = json.loads(results[0].reason_json)
    risks = json.loads(results[0].risk_json)
    evidence_refs = json.loads(results[0].evidence_refs_json)
    assert reasons["top_components"][0]["component"] in {"momentum_score", "trend_score"}
    assert "volatility_score" in risks
    assert "return_20d" in {item["factor_name"] for item in evidence_refs["factors"]}


def test_rank_screen_candidates_filters_market_reality_statuses():
    from openstockagent.screening.scoring import build_default_strategy, rank_screen_candidates

    members = [
        UniverseMember("cn_sample", "EQUITY:CN:000001", "2024-01-01"),
        UniverseMember("cn_sample", "EQUITY:CN:000002", "2024-01-01"),
        UniverseMember("cn_sample", "EQUITY:CN:000003", "2024-01-01"),
        UniverseMember("cn_sample", "EQUITY:CN:000004", "2024-01-01"),
    ]
    values = [
        *_factor_set("EQUITY:CN:000001", momentum=0.80, trend=0.80, volume=0.80, volatility=0.80, turnover=2_000_000),
        *_factor_set("EQUITY:CN:000002", momentum=0.90, trend=0.90, volume=0.90, volatility=0.90, turnover=2_000_000),
        *_factor_set("EQUITY:CN:000003", momentum=0.95, trend=0.95, volume=0.95, volatility=0.95, turnover=2_000_000),
        *_factor_set(
            "EQUITY:CN:000004",
            momentum=0.99,
            trend=0.99,
            volume=0.99,
            volatility=0.99,
            turnover=2_000_000,
            latest_close=10.0,
        ),
    ]
    statuses = {
        "EQUITY:CN:000002": InstrumentStatus("EQUITY:CN:000002", "2026-05-22", "st", True, is_st=True),
        "EQUITY:CN:000003": InstrumentStatus(
            "EQUITY:CN:000003", "2026-05-22", "suspended", False, is_suspended=True
        ),
        "EQUITY:CN:000004": InstrumentStatus(
            "EQUITY:CN:000004", "2026-05-22", "active", True, limit_up=10.0, limit_down=8.0
        ),
    }

    results = rank_screen_candidates("screen-test", members, values, build_default_strategy(), statuses)

    assert [result.instrument_id for result in results] == ["EQUITY:CN:000001"]


def test_mysql_screening_storage_creates_upserts_and_loads_results():
    try:
        from openstockagent.screening.models import ScreenRun, ScreenResult
        from openstockagent.screening.scoring import build_default_strategy
        from openstockagent.screening.storage import MySQLScreeningStorage
    except ModuleNotFoundError as exc:
        raise AssertionError(f"missing screening storage module: {exc}") from exc

    factory = FakeConnectionFactory(
        rows=[
            {
                "run_id": "screen-test",
                "instrument_id": "EQUITY:US:MSFT",
                "rank": 1,
                "selected": 1,
                "total_score": 0.82,
                "score_breakdown_json": '{"momentum_score": {"score": 0.9}}',
                "reason_json": '{"top_components": []}',
                "risk_json": '{"flags": []}',
                "evidence_refs_json": '{"factors": []}',
            }
        ]
    )
    storage = MySQLScreeningStorage(
        config=MySQLConfig.from_jdbc_url("jdbc:mysql://127.0.0.1:13306/openstockagent", "root", "123456"),
        connection_factory=factory,
    )

    storage.upsert_strategy(build_default_strategy(max_candidates=5))
    storage.upsert_screen_run(
        ScreenRun(
            run_id="screen-test",
            universe_id="us_sample",
            trade_date="2026-05-22",
            interval="1d",
            strategy_name="mvp_factor_rank",
            version="v1",
            status="completed",
        )
    )
    storage.upsert_screen_results(
        [
            ScreenResult(
                run_id="screen-test",
                instrument_id="EQUITY:US:MSFT",
                rank=1,
                selected=True,
                total_score=0.82,
                score_breakdown_json='{"momentum_score": {"score": 0.9}}',
                reason_json='{"top_components": []}',
                risk_json='{"flags": []}',
                evidence_refs_json='{"factors": []}',
            )
        ]
    )
    storage.delete_screen_results("screen-test")
    loaded = storage.load_screen_results("screen-test")

    executed_sql = "\n".join(factory.executed_sql)
    assert "CREATE TABLE IF NOT EXISTS screen_strategies" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS screen_runs" in executed_sql
    assert "bar_interval VARCHAR(16) NOT NULL" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS screen_results" in executed_sql
    assert "rank_position INTEGER NOT NULL" in executed_sql
    assert " rank INTEGER NOT NULL" not in executed_sql
    assert "DELETE FROM screen_results WHERE run_id = %s" in executed_sql
    assert "ON DUPLICATE KEY UPDATE" in executed_sql
    assert loaded[0].instrument_id == "EQUITY:US:MSFT"
    assert loaded[0].selected is True


def test_run_screening_pipeline_persists_strategy_run_and_ranked_results():
    try:
        from openstockagent.screening.runner import run_screening_pipeline
        from openstockagent.screening.scoring import build_default_strategy
    except ModuleNotFoundError as exc:
        raise AssertionError(f"missing screening runner module: {exc}") from exc

    universe_storage = FakeUniverseStorage(
        [
            UniverseMember("us_sample", "EQUITY:US:AAPL", "2024-01-01"),
            UniverseMember("us_sample", "EQUITY:US:MSFT", "2024-01-01"),
        ]
    )
    factor_storage = FakeFactorStorage(
        [
            *_factor_set("EQUITY:US:AAPL", momentum=0.60, trend=0.55, volume=0.50, volatility=0.60, turnover=2_000_000),
            *_factor_set("EQUITY:US:MSFT", momentum=0.92, trend=0.88, volume=0.75, volatility=0.70, turnover=4_000_000),
        ]
    )
    screening_storage = FakeScreeningStorage()

    result = run_screening_pipeline(
        universe_id="us_sample",
        as_of="2026-05-22",
        interval="1d",
        universe_storage=universe_storage,
        factor_storage=factor_storage,
        screening_storage=screening_storage,
        strategy=build_default_strategy(max_candidates=1),
    )

    assert result.universe_id == "us_sample"
    assert result.candidates_seen == 2
    assert result.ranked_count == 2
    assert result.selected_count == 1
    assert screening_storage.strategies[0].strategy_name == "mvp_factor_rank"
    assert screening_storage.runs[0].status == "completed"
    assert screening_storage.deleted_run_ids == [result.run_id]
    assert [screen.instrument_id for screen in screening_storage.results] == ["EQUITY:US:MSFT", "EQUITY:US:AAPL"]
    assert screening_storage.results[0].selected is True
    assert screening_storage.results[1].selected is False


def test_run_screening_pipeline_loads_market_reality_statuses():
    from openstockagent.screening.runner import run_screening_pipeline
    from openstockagent.screening.scoring import build_default_strategy

    universe_storage = FakeUniverseStorage(
        [
            UniverseMember("cn_sample", "EQUITY:CN:000001", "2024-01-01"),
            UniverseMember("cn_sample", "EQUITY:CN:000002", "2024-01-01"),
        ]
    )
    factor_storage = FakeFactorStorage(
        [
            *_factor_set("EQUITY:CN:000001", momentum=0.60, trend=0.55, volume=0.50, volatility=0.60, turnover=2_000_000),
            *_factor_set("EQUITY:CN:000002", momentum=0.92, trend=0.88, volume=0.75, volatility=0.70, turnover=4_000_000),
        ]
    )
    screening_storage = FakeScreeningStorage()
    market_reality_storage = FakeMarketRealityStorage(
        {
            "EQUITY:CN:000002": InstrumentStatus("EQUITY:CN:000002", "2026-05-22", "st", True, is_st=True),
        }
    )

    result = run_screening_pipeline(
        universe_id="cn_sample",
        as_of="2026-05-22",
        interval="1d",
        universe_storage=universe_storage,
        factor_storage=factor_storage,
        screening_storage=screening_storage,
        market_reality_storage=market_reality_storage,
        strategy=build_default_strategy(max_candidates=5),
    )

    assert result.ranked_count == 1
    assert result.filtered_count == 1
    assert screening_storage.results[0].instrument_id == "EQUITY:CN:000001"
    assert market_reality_storage.calls == [
        ("EQUITY:CN:000001", "2026-05-22"),
        ("EQUITY:CN:000002", "2026-05-22"),
    ]


def _factor_set(
    instrument_id: str,
    *,
    momentum: float,
    trend: float,
    volume: float,
    volatility: float,
    turnover: float,
    latest_close: float | None = None,
) -> list[FactorValue]:
    evidence_payload = {"bar_count": 70, "end_timestamp": "2026-05-22T00:00:00Z"}
    if latest_close is not None:
        evidence_payload["latest_close"] = latest_close
    evidence = json.dumps(evidence_payload, sort_keys=True)
    return [
        FactorValue(instrument_id, "2026-05-22", "1d", "return_5d", 0.01, percentile=momentum, evidence_json=evidence),
        FactorValue(instrument_id, "2026-05-22", "1d", "return_20d", 0.03, percentile=momentum, evidence_json=evidence),
        FactorValue(instrument_id, "2026-05-22", "1d", "return_60d", 0.06, percentile=momentum, evidence_json=evidence),
        FactorValue(instrument_id, "2026-05-22", "1d", "ma_trend_score", 1.0, percentile=trend, evidence_json=evidence),
        FactorValue(instrument_id, "2026-05-22", "1d", "ma_slope_20d", 0.02, percentile=trend, evidence_json=evidence),
        FactorValue(instrument_id, "2026-05-22", "1d", "volume_expansion_20d", 0.10, percentile=volume, evidence_json=evidence),
        FactorValue(instrument_id, "2026-05-22", "1d", "atr_14d", 0.02, percentile=volatility, evidence_json=evidence),
        FactorValue(instrument_id, "2026-05-22", "1d", "max_drawdown_20d", -0.04, percentile=volatility, evidence_json=evidence),
        FactorValue(
            instrument_id,
            "2026-05-22",
            "1d",
            "turnover_amount_20d",
            turnover,
            percentile=volume,
            evidence_json=evidence,
        ),
    ]


class FakeUniverseStorage:
    def __init__(self, members):
        self.members = members
        self.calls = []

    def load_universe_members(self, universe_id, as_of=None):
        self.calls.append((universe_id, as_of))
        return self.members


class FakeFactorStorage:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def load_factor_values(self, trade_date, interval):
        self.calls.append((trade_date, interval))
        return self.values


class FakeScreeningStorage:
    def __init__(self):
        self.strategies = []
        self.runs = []
        self.results = []

    def upsert_strategy(self, strategy):
        self.strategies.append(strategy)

    def upsert_screen_run(self, run):
        self.runs.append(run)

    def upsert_screen_results(self, results):
        self.results.extend(results)
        return len(results)

    def delete_screen_results(self, run_id):
        self.deleted_run_ids = getattr(self, "deleted_run_ids", [])
        self.deleted_run_ids.append(run_id)


class FakeMarketRealityStorage:
    def __init__(self, statuses):
        self.statuses = statuses
        self.calls = []

    def load_instrument_status(self, instrument_id, as_of):
        self.calls.append((instrument_id, as_of))
        return self.statuses.get(instrument_id)


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
