from click.testing import CliRunner


def test_real_data_factor_cli_runs_pipeline(monkeypatch):
    from scripts import run_real_data_factors

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

    monkeypatch.setattr(run_real_data_factors, "run_real_data_factor_pipeline", fake_pipeline)
    monkeypatch.setattr(run_real_data_factors, "PolygonStockFeed", lambda: object())
    monkeypatch.setattr(run_real_data_factors, "AkShareAStockFeed", lambda: object())
    monkeypatch.setattr(run_real_data_factors, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(run_real_data_factors, "MySQLFactorStorage", lambda config: object())

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
