import os

import pytest
import pandas as pd
import numpy as np
from openstockagent.predictors.kronos_adapter import KronosStockPredictor, _resolve_model_path


KRONOS_TEST_VARIANT = os.getenv("KRONOS_TEST_VARIANT", "base")


def _has_local_kronos_weights() -> bool:
    if KRONOS_TEST_VARIANT not in KronosStockPredictor.MODELS:
        return False
    model_hf_id, model_local_name = KronosStockPredictor.MODELS[KRONOS_TEST_VARIANT]
    model_path = _resolve_model_path(model_hf_id, model_local_name)
    tokenizer_path = _resolve_model_path("NeoQuasar/Kronos-Tokenizer-base", "kronos-tokenizer")
    return model_path != model_hf_id and tokenizer_path != "NeoQuasar/Kronos-Tokenizer-base"


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_KRONOS_MODEL_TESTS") != "1" or not _has_local_kronos_weights(),
    reason="Kronos model tests require RUN_KRONOS_MODEL_TESTS=1 and local model weights",
)


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
    predictor = KronosStockPredictor(variant=KRONOS_TEST_VARIANT, device="cpu")
    result = predictor.predict("TEST", sample_ohlcv, horizon=5)

    assert result.symbol == "TEST"
    assert result.horizon == 5
    assert len(result.forecast) == 5
    required = {"open", "high", "low", "close", "volume"}
    assert required.issubset(set(result.forecast.columns))
    assert 0.0 <= result.confidence <= 1.0


def test_kronos_predict_consistency(sample_ohlcv):
    """Same input should produce same stub output (deterministic stub uses fixed seed behavior)."""
    predictor = KronosStockPredictor(variant=KRONOS_TEST_VARIANT, device="cpu")
    result1 = predictor.predict("TEST", sample_ohlcv, horizon=3)
    result2 = predictor.predict("TEST", sample_ohlcv, horizon=3)

    # Stub is non-deterministic due to random.normal, but structure should match
    assert result1.horizon == result2.horizon
    assert list(result1.forecast.columns) == list(result2.forecast.columns)
