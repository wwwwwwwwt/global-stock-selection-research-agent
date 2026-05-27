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


def test_stock_data_sync_cn_reference_cli_requires_tushare_token(monkeypatch):
    from openstockagent.cli import stock_data

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    result = CliRunner().invoke(
        stock_data.main,
        ["sync-cn-reference", "--start", "2026-05-01", "--end", "2026-05-28"],
    )

    assert result.exit_code != 0
    assert "TUSHARE_TOKEN is required" in result.output


def test_stock_data_sync_cn_reference_cli_runs_reference_pipeline(monkeypatch):
    from openstockagent.cli import stock_data
    from openstockagent.pipelines.tushare_reference import TushareReferenceSyncResult

    calls = {}

    class FakeReferenceFeed:
        def __init__(self, token=None):
            calls["token"] = token

    def fake_run(**kwargs):
        calls.update(kwargs)
        return TushareReferenceSyncResult(
            market="CN",
            start=kwargs["start"],
            end=kwargs["end"],
            status_date=kwargs["status_date"],
            instruments_written=2,
            aliases_written=2,
            calendar_days_written=5,
            statuses_written=3,
            corporate_actions_written=2,
        )

    monkeypatch.setenv("TUSHARE_TOKEN", "env-token")
    monkeypatch.setattr(stock_data, "TushareReferenceFeed", FakeReferenceFeed)
    monkeypatch.setattr(stock_data, "MySQLMarketDataStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLMarketRealityStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "run_tushare_reference_sync", fake_run)

    result = CliRunner().invoke(
        stock_data.main,
        [
            "sync-cn-reference",
            "--start",
            "2026-05-01",
            "--end",
            "2026-05-28",
            "--status-date",
            "2026-05-27",
        ],
    )

    assert result.exit_code == 0
    assert calls["token"] == "env-token"
    assert calls["status_date"] == "2026-05-27"
    assert "instruments_written=2" in result.output
    assert "statuses_written=3" in result.output


def test_stock_data_sync_cn_daily_cli_requires_tushare_token(monkeypatch):
    from openstockagent.cli import stock_data

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    result = CliRunner().invoke(
        stock_data.main,
        ["sync-cn-daily", "--universe", "cn_core", "--trade-date", "2026-05-27"],
    )

    assert result.exit_code != 0
    assert "TUSHARE_TOKEN is required" in result.output


def test_stock_data_sync_cn_daily_cli_runs_batch_pipeline(monkeypatch):
    from openstockagent.cli import stock_data
    from openstockagent.pipelines.tushare_daily_batch import TushareDailyBatchSyncResult

    calls = {}

    class FakeReferenceFeed:
        def __init__(self, token=None):
            calls["token"] = token

    def fake_run(**kwargs):
        calls.update(kwargs)
        return TushareDailyBatchSyncResult(
            universe_id=kwargs["universe_id"],
            trade_date=kwargs["trade_date"],
            members_seen=5,
            daily_rows_seen=5000,
            daily_basic_rows_seen=5000,
            bars_written=5,
            factor_values_written=45,
            instruments_matched=5,
        )

    monkeypatch.setenv("TUSHARE_TOKEN", "env-token")
    monkeypatch.setattr(stock_data, "TushareReferenceFeed", FakeReferenceFeed)
    monkeypatch.setattr(stock_data, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLMarketDataStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLFactorStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "run_tushare_daily_batch_sync", fake_run)

    result = CliRunner().invoke(
        stock_data.main,
        [
            "sync-cn-daily",
            "--universe",
            "cn_core",
            "--trade-date",
            "2026-05-27",
            "--max-symbols",
            "5",
            "--skip-bars",
        ],
    )

    assert result.exit_code == 0
    assert calls["token"] == "env-token"
    assert calls["universe_id"] == "cn_core"
    assert calls["trade_date"] == "2026-05-27"
    assert calls["include_bars"] is False
    assert calls["include_daily_basic"] is True
    assert calls["max_symbols"] == 5
    assert "factor_values_written=45" in result.output


def test_stock_data_run_cn_selection_cli_runs_end_to_end_pipeline(monkeypatch):
    from openstockagent.cli import stock_data
    from openstockagent.pipelines.cn_daily_selection import CNDailySelectionResult
    from openstockagent.pipelines.tushare_daily_batch import TushareDailyBatchSyncResult
    from openstockagent.pipelines.tushare_reference import TushareReferenceSyncResult
    from openstockagent.recommendations.runner import RecommendationRunResult
    from openstockagent.screening.runner import ScreeningRunResult

    calls = {}

    class FakeReferenceFeed:
        def __init__(self, token=None):
            calls["token"] = token

    class FakePortfolioResult:
        class Decision:
            decision_id = "decision-test"
            action = "allocate"
            target_gross_exposure = 0.5
            cash_pct = 0.5

        decision = Decision()
        allocations = [object()]

    def fake_run(**kwargs):
        calls.update(kwargs)
        return CNDailySelectionResult(
            universe_id=kwargs["universe_id"],
            trade_date=kwargs["trade_date"],
            reference=TushareReferenceSyncResult("CN", "2026-05-20", "2026-05-27", "2026-05-27", 2, 2, 1, 2, 2),
            daily=TushareDailyBatchSyncResult("cn_core", "2026-05-27", 5, 5506, 5506, 5, 45, 5),
            screening=ScreeningRunResult("screen-test", "cn_core", "2026-05-27", "1d", 800, 45, 5, 5, 795, [], []),
            recommendation=RecommendationRunResult(
                "rec-test", "screen-test", "cn_core", "2026-05-27", "5d", "2026-06-03", "completed", 5, 3, 2, 0, []
            ),
            portfolio=FakePortfolioResult(),
        )

    monkeypatch.setenv("TUSHARE_TOKEN", "env-token")
    monkeypatch.setattr(stock_data, "TushareReferenceFeed", FakeReferenceFeed)
    monkeypatch.setattr(stock_data, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLMarketDataStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLMarketRealityStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLFactorStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLScreeningStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLRecommendationStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "MySQLPortfolioStorage", lambda config: object())
    monkeypatch.setattr(stock_data, "run_cn_daily_selection_pipeline", fake_run)

    result = CliRunner().invoke(
        stock_data.main,
        [
            "run-cn-selection",
            "--universe",
            "cn_core",
            "--trade-date",
            "2026-05-27",
            "--reference-start",
            "2026-05-20",
            "--max-symbols",
            "5",
            "--top-n",
            "5",
        ],
    )

    assert result.exit_code == 0
    assert calls["token"] == "env-token"
    assert calls["reference_start"] == "2026-05-20"
    assert calls["max_symbols"] == 5
    assert calls["top_n"] == 5
    assert calls["run_reference"] is True
    assert calls["run_daily_sync"] is True
    assert calls["run_portfolio"] is True
    assert "screen_run_id=screen-test" in result.output
    assert "Portfolio: decision_id=decision-test" in result.output
