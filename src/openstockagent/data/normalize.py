import pandas as pd


def normalize_bars(
    df: pd.DataFrame,
    instrument_id: str,
    interval: str,
    source: str,
    adjustment: str,
    currency: str | None = None,
) -> pd.DataFrame:
    normalized = df.copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    normalized["local_date"] = pd.to_datetime(normalized["timestamp"], utc=True).dt.strftime("%Y-%m-%d")
    if "amount" not in normalized.columns:
        normalized["amount"] = normalized["volume"] * normalized[["open", "high", "low", "close"]].mean(axis=1)
    normalized["instrument_id"] = instrument_id
    normalized["interval"] = interval
    normalized["source"] = source
    normalized["adjustment"] = adjustment
    normalized["currency"] = currency
    normalized["is_complete"] = 1
    normalized["provider_payload_hash"] = None
    columns = [
        "instrument_id",
        "timestamp",
        "local_date",
        "interval",
        "source",
        "adjustment",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "currency",
        "is_complete",
        "provider_payload_hash",
    ]
    return normalized[columns]
