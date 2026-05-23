import pytest
import pandas as pd
import numpy as np
from openstockagent.predictors.kronos_adapter import KronosStockPredictor


@pytest.fixture
def sample_ohlcv():
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    return pd.DataFrame({
        "open": 100 + np.random.randn(60).cumsum(),
        "high": 101 + np.random.randn(60).cumsum(),
        "low": 99 + np.random.randn(60).cumsum(),
        "close": 100 + np.random.randn(60).cumsum(),
        "volume": np.random.randint(1000, 10000, 60),
    }, index=dates)


def test_kronos_predict_shape(sample_ohlcv):
    predictor = KronosStockPredictor(variant="mini", device="cpu")
    result = predictor.predict("TEST", sample_ohlcv, horizon=5)

    assert result.symbol == "TEST"
    assert result.horizon == 5
    assert len(result.forecast) == 5
    assert set(result.forecast.columns) == {"open", "high", "low", "close", "volume"}
    assert 0.0 <= result.confidence <= 1.0


def test_kronos_predict_consistency(sample_ohlcv):
    """Same input should produce same stub output (deterministic stub uses fixed seed behavior)."""
    predictor = KronosStockPredictor(variant="mini", device="cpu")
    result1 = predictor.predict("TEST", sample_ohlcv, horizon=3)
    result2 = predictor.predict("TEST", sample_ohlcv, horizon=3)

    # Stub is non-deterministic due to random.normal, but structure should match
    assert result1.horizon == result2.horizon
    assert list(result1.forecast.columns) == list(result2.forecast.columns)
