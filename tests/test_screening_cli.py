from click.testing import CliRunner
import tomllib


def test_stock_screen_entrypoint_targets_packaged_module():
    with open("pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["scripts"]["stock-screen"].startswith("openstockagent.")


def test_screening_cli_runs_pipeline(monkeypatch):
    try:
        from openstockagent.cli import run_screening
    except ModuleNotFoundError as exc:
        raise AssertionError(f"missing screening CLI module: {exc}") from exc

    calls = {}

    def fake_pipeline(**kwargs):
        from openstockagent.screening.models import ScreenResult

        calls.update(kwargs)
        return run_screening.ScreeningRunResult(
            run_id="screen-test",
            universe_id=kwargs["universe_id"],
            trade_date=kwargs["as_of"],
            interval=kwargs["interval"],
            candidates_seen=2,
            factor_values_seen=18,
            ranked_count=2,
            selected_count=1,
            filtered_count=0,
            errors=[],
            results=[
                ScreenResult(
                    run_id="screen-test",
                    instrument_id="EQUITY:US:MSFT",
                    rank=1,
                    selected=True,
                    total_score=0.82,
                    score_breakdown_json="{}",
                    reason_json="{}",
                    risk_json="{}",
                    evidence_refs_json="{}",
                )
            ],
        )

    monkeypatch.setattr(run_screening, "run_screening_pipeline", fake_pipeline)
    monkeypatch.setattr(run_screening, "MySQLUniverseStorage", lambda config: object())
    monkeypatch.setattr(run_screening, "MySQLFactorStorage", lambda config: object())
    monkeypatch.setattr(run_screening, "MySQLScreeningStorage", lambda config: object())

    result = CliRunner().invoke(
        run_screening.main,
        ["us_sample", "--as-of", "2026-05-22", "--top-n", "1"],
    )

    assert result.exit_code == 0
    assert calls["universe_id"] == "us_sample"
    assert calls["as_of"] == "2026-05-22"
    assert calls["interval"] == "1d"
    assert calls["strategy"].config["max_candidates"] == 1
    assert "selected_count=1" in result.output
    assert "1. EQUITY:US:MSFT score=0.820000" in result.output
