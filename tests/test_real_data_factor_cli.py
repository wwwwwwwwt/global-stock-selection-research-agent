from click.testing import CliRunner
import tomllib


def test_stock_factors_entrypoint_targets_packaged_module():
    with open("pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["scripts"]["stock-factors"].startswith("openstockagent.")


def test_real_data_factor_cli_runs_pipeline(monkeypatch):
    from openstockagent.cli import run_real_data_factors

    calls = {}

    def fake_pipeline(**kwargs):
        calls.update(kwargs)
        return run_real_data_factors.RealDataFactorRunResult(
            universe_id=kwargs["universe_id"],
            trade_date=kwargs["as_of"],
            interval=kwargs["interval"],
            members_seen=2,
            instruments_fetched=2,
            failed_instruments=0,
            bars_written=140,
            factor_values_written=18,
            errors=[],
        )

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(run_real_data_factors, "run_real_data_factor_pipeline", fake_pipeline)
    monkeypatch.setattr(run_real_data_factors, "PolygonStockFeed", lambda: object())
    monkeypatch.setattr(run_real_data_factors, "AkShareAStockFeed", lambda: object())
    monkeypatch.setattr(run_real_data_factors, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(run_real_data_factors, "MySQLFactorStorage", lambda config: object())
    monkeypatch.setattr(run_real_data_factors, "MySQLMarketDataStorage", lambda config: object())

    result = CliRunner().invoke(
        run_real_data_factors.main,
        ["cn_sample", "--as-of", "2024-04-05", "--period", "6mo"],
    )

    assert result.exit_code == 0
    assert calls["universe_id"] == "cn_sample"
    assert calls["as_of"] == "2024-04-05"
    assert calls["period"] == "6mo"
    assert calls["interval"] == "1d"
    assert "factor_values_written=18" in result.output


def test_real_data_factor_cli_uses_cn_feed_without_requiring_polygon(monkeypatch):
    from openstockagent.cli import run_real_data_factors

    calls = {}

    class FakeTushareFeed:
        source = "tushare"

        def __init__(self, token=None):
            calls["tushare_token"] = token

    def fail_polygon():
        raise AssertionError("Polygon should not be constructed for CN factor runs")

    def fake_pipeline(**kwargs):
        calls.update(kwargs)
        return run_real_data_factors.RealDataFactorRunResult(
            universe_id=kwargs["universe_id"],
            trade_date=kwargs["as_of"],
            interval=kwargs["interval"],
            members_seen=5,
            instruments_fetched=5,
            failed_instruments=0,
            bars_written=40,
            factor_values_written=45,
            errors=[],
        )

    monkeypatch.setenv("TUSHARE_TOKEN", "env-token")
    monkeypatch.setattr(run_real_data_factors, "PolygonStockFeed", fail_polygon)
    monkeypatch.setattr(run_real_data_factors, "TushareAStockFeed", FakeTushareFeed)
    monkeypatch.setattr(run_real_data_factors, "run_real_data_factor_pipeline", fake_pipeline)
    monkeypatch.setattr(run_real_data_factors, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(run_real_data_factors, "MySQLFactorStorage", lambda config: object())
    monkeypatch.setattr(run_real_data_factors, "MySQLMarketDataStorage", lambda config: object())

    result = CliRunner().invoke(
        run_real_data_factors.main,
        ["cn_core", "--as-of", "2026-05-28", "--period", "10d", "--max-symbols", "5"],
    )

    assert result.exit_code == 0
    assert calls["tushare_token"] == "env-token"
    assert calls["max_symbols"] == 5
    assert "factor_values_written=45" in result.output
