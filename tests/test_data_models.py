from openstockagent.data.models import (
    BAR_COLUMNS,
    INTERVALS,
    Instrument,
    MarketBar,
    TechnicalSignal,
    utc_now_iso,
)


def test_bar_columns_are_kronos_compatible():
    assert BAR_COLUMNS == ["open", "high", "low", "close", "volume", "amount"]


def test_intervals_include_daily_weekly_and_intraday():
    assert {"1m", "5m", "1h", "1d", "1w"}.issubset(INTERVALS)


def test_instrument_id_is_stable():
    instrument = Instrument(
        instrument_id="EQUITY:US:AAPL",
        symbol="AAPL",
        market="US",
        exchange="NASDAQ",
        asset_type="equity",
        currency="USD",
        name="Apple Inc.",
        timezone="America/New_York",
    )
    assert instrument.instrument_id == "EQUITY:US:AAPL"
    assert instrument.market == "US"


def test_market_bar_to_record_has_required_fields():
    bar = MarketBar(
        instrument_id="EQUITY:US:AAPL",
        timestamp="2024-01-02T21:00:00Z",
        local_date="2024-01-02",
        interval="1d",
        source="csv",
        adjustment="split_adjusted",
        open=100.0,
        high=103.0,
        low=99.0,
        close=102.0,
        volume=1000.0,
        amount=101000.0,
        currency="USD",
    )
    record = bar.to_record()
    assert record["instrument_id"] == "EQUITY:US:AAPL"
    assert record["close"] == 102.0
    assert record["is_complete"] == 1


def test_technical_signal_requires_evidence():
    signal = TechnicalSignal(
        signal_id="sig_1",
        instrument_id="EQUITY:US:AAPL",
        timestamp="2024-01-10T21:00:00Z",
        interval="1d",
        signal_type="golden_cross",
        direction="bullish",
        strength=0.8,
        confidence=0.7,
        severity="watch",
        summary="MA5 crossed above MA20.",
        evidence_json='{"fast_ma": "ma_close_5"}',
        input_range_start="2023-12-01T21:00:00Z",
        input_range_end="2024-01-10T21:00:00Z",
    )
    assert signal.signal_type == "golden_cross"
    assert signal.evidence_json.startswith("{")


def test_utc_now_iso_is_sortable():
    value = utc_now_iso()
    assert value.endswith("Z")
    assert "T" in value
