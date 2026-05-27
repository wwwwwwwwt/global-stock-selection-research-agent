"""Technical and price-volume factor calculations."""
from __future__ import annotations

import json

import pandas as pd

from openstockagent.factors.models import FactorValue


def compute_technical_factors(
    instrument_id: str,
    bars: pd.DataFrame,
    trade_date: str,
    interval: str,
    version: str = "v1",
) -> list[FactorValue]:
    frame = _prepare_bars(bars, trade_date)
    if frame.empty:
        return []

    calculations = {
        "return_5d": (_return(frame, 5), {"lookback_days": 5}),
        "return_20d": (_return(frame, 20), {"lookback_days": 20}),
        "return_60d": (_return(frame, 60), {"lookback_days": 60}),
        "ma_trend_score": (_ma_trend_score(frame), {"windows": [5, 20, 60]}),
        "ma_slope_20d": (_ma_slope(frame, 20, 5), {"window": 20, "slope_days": 5}),
        "volume_expansion_20d": (_volume_expansion(frame), {"recent_days": 5, "baseline_days": 20}),
        "atr_14d": (_atr_ratio(frame, 14), {"window": 14}),
        "max_drawdown_20d": (_max_drawdown(frame, 20), {"window": 20}),
        "turnover_amount_20d": (_mean(frame, "amount", 20), {"window": 20}),
    }

    latest = frame.iloc[-1]
    values = []
    for factor_name, (factor_value, evidence) in calculations.items():
        evidence = {
            **evidence,
            "start_timestamp": frame.iloc[0]["timestamp"],
            "end_timestamp": latest["timestamp"],
            "bar_count": int(len(frame)),
            "latest_close": _float_or_none(latest.get("close")),
        }
        values.append(
            FactorValue(
                instrument_id=instrument_id,
                trade_date=trade_date,
                interval=interval,
                factor_name=factor_name,
                factor_value=factor_value,
                version=version,
                evidence_json=json.dumps(evidence, sort_keys=True),
            )
        )
    return values


def _prepare_bars(bars: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    frame = bars.copy()
    if "local_date" not in frame.columns:
        frame["local_date"] = pd.to_datetime(frame["timestamp"], utc=True).dt.strftime("%Y-%m-%d")
    else:
        # Ensure local_date is string for consistent comparison
        frame["local_date"] = pd.to_datetime(frame["local_date"], utc=True).dt.strftime("%Y-%m-%d")
    frame = frame[frame["local_date"] <= trade_date].copy()
    if frame.empty:
        return frame
    frame["timestamp_sort"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp_sort")
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.drop(columns=["timestamp_sort"])


def _return(frame: pd.DataFrame, days: int) -> float | None:
    if len(frame) <= days:
        return None
    latest = frame["close"].iloc[-1]
    base = frame["close"].iloc[-days - 1]
    if pd.isna(latest) or pd.isna(base) or base == 0:
        return None
    return float(latest / base - 1.0)


def _ma_trend_score(frame: pd.DataFrame) -> float | None:
    latest = frame["close"].iloc[-1]
    checks = []
    for window in [5, 20, 60]:
        if len(frame) >= window:
            moving_average = frame["close"].tail(window).mean()
            checks.append(float(latest > moving_average))
    if not checks:
        return None
    return float(sum(checks) / len(checks))


def _ma_slope(frame: pd.DataFrame, window: int, slope_days: int) -> float | None:
    if len(frame) < window + slope_days:
        return None
    ma = frame["close"].rolling(window).mean().dropna()
    latest = ma.iloc[-1]
    base = ma.iloc[-slope_days - 1]
    if base == 0 or pd.isna(base) or pd.isna(latest):
        return None
    return float(latest / base - 1.0)


def _volume_expansion(frame: pd.DataFrame) -> float | None:
    if len(frame) < 25 or "volume" not in frame.columns:
        return None
    recent = frame["volume"].tail(5).mean()
    baseline = frame["volume"].iloc[-25:-5].mean()
    if baseline == 0 or pd.isna(baseline) or pd.isna(recent):
        return None
    return float(recent / baseline - 1.0)


def _atr_ratio(frame: pd.DataFrame, window: int) -> float | None:
    if len(frame) < window + 1:
        return None
    recent = frame.tail(window + 1).copy()
    previous_close = recent["close"].shift(1)
    true_range = pd.concat(
        [
            recent["high"] - recent["low"],
            (recent["high"] - previous_close).abs(),
            (recent["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1).iloc[1:]
    latest_close = frame["close"].iloc[-1]
    if latest_close == 0 or pd.isna(latest_close):
        return None
    return float(true_range.mean() / latest_close)


def _max_drawdown(frame: pd.DataFrame, window: int) -> float | None:
    if len(frame) < window:
        return None
    closes = frame["close"].tail(window)
    drawdowns = closes / closes.cummax() - 1.0
    return float(drawdowns.min())


def _mean(frame: pd.DataFrame, column: str, window: int) -> float | None:
    if column not in frame.columns or len(frame) < window:
        return None
    value = frame[column].tail(window).mean()
    if pd.isna(value):
        return None
    return float(value)


def _float_or_none(value) -> float | None:
    if pd.isna(value):
        return None
    return float(value)
