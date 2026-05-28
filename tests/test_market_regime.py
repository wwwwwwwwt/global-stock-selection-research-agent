import json

from openstockagent.factors.models import FactorValue
from openstockagent.market.regime import build_market_context_snapshot_from_values
from openstockagent.universe.models import UniverseMember


def test_market_context_snapshot_classifies_risk_on_from_breadth_trend_and_volatility():
    members = _members("EQUITY:CN:000001", "EQUITY:CN:000002", "EQUITY:CN:000003")
    values = [
        *_regime_factors("EQUITY:CN:000001", return_20d=0.08, return_60d=0.12, trend=0.8, slope=0.02, atr=0.03, drawdown=-0.02),
        *_regime_factors("EQUITY:CN:000002", return_20d=0.04, return_60d=0.06, trend=0.6, slope=0.01, atr=0.04, drawdown=-0.04),
        *_regime_factors("EQUITY:CN:000003", return_20d=-0.01, return_60d=0.03, trend=0.5, slope=0.00, atr=0.05, drawdown=-0.07),
    ]

    snapshot = build_market_context_snapshot_from_values(
        universe_id="cn_core",
        as_of="2026-05-27",
        market="CN",
        members=members,
        factor_values=values,
    )

    assert snapshot.risk_regime == "risk_on"
    assert snapshot.coverage == 1.0
    assert snapshot.regime_score is not None
    assert snapshot.regime_score >= 0.65
    assert snapshot.snapshot_id.startswith("market-context-")
    assert json.loads(snapshot.summary_json)["flags"] == []


def test_market_context_snapshot_classifies_high_risk_when_trend_and_volatility_break():
    members = _members("EQUITY:CN:000001", "EQUITY:CN:000002", "EQUITY:CN:000003")
    values = [
        *_regime_factors("EQUITY:CN:000001", return_20d=-0.10, return_60d=-0.16, trend=0.2, slope=-0.03, atr=0.09, drawdown=-0.18),
        *_regime_factors("EQUITY:CN:000002", return_20d=-0.08, return_60d=-0.12, trend=0.1, slope=-0.02, atr=0.08, drawdown=-0.15),
        *_regime_factors("EQUITY:CN:000003", return_20d=-0.03, return_60d=-0.06, trend=0.4, slope=-0.01, atr=0.07, drawdown=-0.12),
    ]

    snapshot = build_market_context_snapshot_from_values(
        universe_id="cn_core",
        as_of="2026-05-27",
        market="CN",
        members=members,
        factor_values=values,
    )

    assert snapshot.risk_regime == "high_risk"
    assert "severe_volatility_and_weak_trend" in json.loads(snapshot.summary_json)["flags"]


def test_market_context_snapshot_returns_unknown_when_only_daily_basic_factors_exist():
    members = _members("EQUITY:CN:000001", "EQUITY:CN:000002")
    values = [
        _factor("EQUITY:CN:000001", "turnover_rate", 2.0),
        _factor("EQUITY:CN:000002", "turnover_rate", 1.5),
    ]

    snapshot = build_market_context_snapshot_from_values(
        universe_id="cn_core",
        as_of="2026-05-27",
        market="CN",
        members=members,
        factor_values=values,
    )

    assert snapshot.risk_regime == "unknown"
    assert snapshot.coverage == 0.0
    assert snapshot.liquidity_score == 1.0
    assert "insufficient_regime_factor_coverage" in json.loads(snapshot.summary_json)["flags"]


def test_market_context_snapshot_returns_data_bad_when_factor_coverage_is_empty():
    snapshot = build_market_context_snapshot_from_values(
        universe_id="cn_core",
        as_of="2026-05-27",
        market="CN",
        members=_members("EQUITY:CN:000001"),
        factor_values=[],
    )

    assert snapshot.risk_regime == "data_bad"
    assert "insufficient_factor_coverage" in json.loads(snapshot.summary_json)["flags"]


def _members(*instrument_ids):
    return [UniverseMember("cn_core", instrument_id, "2026-01-01") for instrument_id in instrument_ids]


def _regime_factors(instrument_id, *, return_20d, return_60d, trend, slope, atr, drawdown):
    return [
        _factor(instrument_id, "return_20d", return_20d),
        _factor(instrument_id, "return_60d", return_60d),
        _factor(instrument_id, "ma_trend_score", trend),
        _factor(instrument_id, "ma_slope_20d", slope),
        _factor(instrument_id, "atr_14d", atr),
        _factor(instrument_id, "max_drawdown_20d", drawdown),
    ]


def _factor(instrument_id, factor_name, value):
    return FactorValue(
        instrument_id=instrument_id,
        trade_date="2026-05-27",
        interval="1d",
        factor_name=factor_name,
        factor_value=value,
        evidence_json="{}",
    )
