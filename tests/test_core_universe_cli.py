from click.testing import CliRunner


def test_stock_universe_build_core_cli_persists_core_universe(monkeypatch):
    from openstockagent.cli import stock_universe
    from openstockagent.universe.models import Universe, UniverseMember

    calls = {}

    class Result:
        universe = Universe("us_core", "US Core", "US", "equity")
        members = [UniverseMember("us_core", "EQUITY:US:AAPL", "2026-05-25")]
        instruments = []
        aliases = []

    def fake_build(**kwargs):
        calls["build"] = kwargs
        return Result()

    monkeypatch.setattr(stock_universe, "build_us_core_universe", fake_build)
    monkeypatch.setattr(stock_universe, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(stock_universe, "MySQLMarketDataStorage", lambda config: object())
    monkeypatch.setattr(stock_universe, "persist_core_universe", lambda result, universe_storage, market_data_storage: 1)

    result = CliRunner().invoke(stock_universe.main, ["build-core", "--market", "US", "--as-of", "2026-05-25"])

    assert result.exit_code == 0
    assert calls["build"]["as_of"] == "2026-05-25"
    assert calls["build"]["universe_id"] == "us_core"
    assert "Core universe build complete" in result.output


def test_stock_data_sync_cli_runs_data_sync(monkeypatch):
    from openstockagent.cli import stock_data
    from openstockagent.data.sync import DataSyncRunResult

    calls = {}

    def fake_run(plan, **kwargs):
        calls["plan"] = plan
        calls.update(kwargs)
        return DataSyncRunResult(
            run_id="sync-test",
            plan_id=plan.plan_id,
            universe_id=plan.universe_id,
            market=plan.market,
            as_of=kwargs["as_of"],
            mode=plan.mode,
            interval=plan.interval,
            period=plan.period(),
            members_seen=2,
            instruments_fetched=2,
            failed_instruments=0,
            bars_written=20,
            errors=[],
            started_at="2026-05-25T00:00:00Z",
            ended_at="2026-05-25T00:00:01Z",
            status="completed",
        )

    class FakePolygonFeed:
        source = "polygon"

    monkeypatch.setattr(stock_data, "PolygonStockFeed", FakePolygonFeed)
    monkeypatch.setattr(stock_data, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLMarketDataStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLDataSyncStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "run_data_sync_plan", fake_run)

    result = CliRunner().invoke(
        stock_data.main,
        ["sync", "--universe", "us_core", "--market", "US", "--as-of", "2026-05-25", "--mode", "incremental"],
    )

    assert result.exit_code == 0
    assert calls["plan"].period() == "10d"
    assert calls["max_symbols"] is None
    assert calls["max_attempts"] == 3
    assert calls["retry_sleep_seconds"] == 0.5
    assert "bars_written=20" in result.output


def test_stock_data_sync_cli_uses_tushare_for_cn_when_token_is_configured(monkeypatch):
    from openstockagent.cli import stock_data
    from openstockagent.data.sync import DataSyncRunResult

    calls = {}
    feeds = {}

    class FakeTushareFeed:
        source = "tushare"

        def __init__(self, token=None):
            feeds["tushare_token"] = token

    def fake_run(plan, **kwargs):
        calls["plan"] = plan
        calls.update(kwargs)
        return DataSyncRunResult(
            run_id="sync-test",
            plan_id=plan.plan_id,
            universe_id=plan.universe_id,
            market=plan.market,
            as_of=kwargs["as_of"],
            mode=plan.mode,
            interval=plan.interval,
            period=plan.period(),
            members_seen=2,
            instruments_fetched=2,
            failed_instruments=0,
            bars_written=20,
            errors=[],
            started_at="2026-05-25T00:00:00Z",
            ended_at="2026-05-25T00:00:01Z",
            status="completed",
        )

    monkeypatch.setenv("TUSHARE_TOKEN", "env-token")
    monkeypatch.setattr(stock_data, "TushareAStockFeed", FakeTushareFeed)
    monkeypatch.setattr(stock_data, "AkShareAStockFeed", lambda: object())
    monkeypatch.setattr(stock_data, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLMarketDataStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLDataSyncStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "run_data_sync_plan", fake_run)

    result = CliRunner().invoke(
        stock_data.main,
        ["sync", "--universe", "cn_core", "--market", "CN", "--as-of", "2026-05-25"],
    )

    assert result.exit_code == 0
    assert calls["plan"].provider == "tushare"
    assert feeds["tushare_token"] == "env-token"


def test_stock_data_sync_cli_falls_back_to_akshare_for_cn_without_tushare_token(monkeypatch):
    from openstockagent.cli import stock_data
    from openstockagent.data.sync import DataSyncRunResult

    calls = {}

    class FakeAkShareFeed:
        source = "akshare"

    def fake_run(plan, **kwargs):
        calls["plan"] = plan
        return DataSyncRunResult(
            run_id="sync-test",
            plan_id=plan.plan_id,
            universe_id=plan.universe_id,
            market=plan.market,
            as_of=kwargs["as_of"],
            mode=plan.mode,
            interval=plan.interval,
            period=plan.period(),
            members_seen=1,
            instruments_fetched=1,
            failed_instruments=0,
            bars_written=10,
            errors=[],
            started_at="2026-05-25T00:00:00Z",
            ended_at="2026-05-25T00:00:01Z",
            status="completed",
        )

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(stock_data, "AkShareAStockFeed", FakeAkShareFeed)
    monkeypatch.setattr(stock_data, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLMarketDataStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLDataSyncStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "run_data_sync_plan", fake_run)

    result = CliRunner().invoke(
        stock_data.main,
        ["sync", "--universe", "cn_core", "--market", "CN", "--as-of", "2026-05-25"],
    )

    assert result.exit_code == 0
    assert calls["plan"].provider == "akshare"
