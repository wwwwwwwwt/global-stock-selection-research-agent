import json
from uuid import uuid4

import pandas as pd

from openstockagent.data.models import utc_now_iso


def validate_bars(df: pd.DataFrame) -> list[dict]:
    issues: list[dict] = []
    required = ["instrument_id", "timestamp", "interval", "open", "high", "low", "close"]
    for column in required:
        if column not in df.columns:
            issues.append(_issue(None, None, None, "error", "missing_column", {"column": column}))
            return issues

    for _, row in df.iterrows():
        instrument_id = row["instrument_id"]
        interval = row["interval"]
        timestamp = row["timestamp"]
        high = row["high"]
        low = row["low"]
        open_ = row["open"]
        close = row["close"]
        if min(open_, high, low, close) < 0:
            issues.append(_issue(instrument_id, interval, timestamp, "error", "negative_price", row.to_dict()))
        if high < max(open_, close) or low > min(open_, close):
            issues.append(_issue(instrument_id, interval, timestamp, "error", "invalid_ohlc", row.to_dict()))
        if "volume" in row and pd.notna(row["volume"]) and row["volume"] < 0:
            issues.append(_issue(instrument_id, interval, timestamp, "error", "negative_volume", row.to_dict()))
    return issues


def _issue(instrument_id, interval, timestamp, severity, issue_type, details) -> dict:
    return {
        "issue_id": f"dq_{uuid4().hex}",
        "run_id": None,
        "instrument_id": instrument_id,
        "interval": interval,
        "timestamp": timestamp,
        "severity": severity,
        "issue_type": issue_type,
        "details_json": json.dumps(details, default=str),
        "created_at": utc_now_iso(),
    }
