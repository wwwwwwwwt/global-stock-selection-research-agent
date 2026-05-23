import sys
from pathlib import Path
import pandas as pd
import numpy as np
import torch

# Add vendor Kronos to path
KRONOS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "vendor" / "Kronos"
if str(KRONOS_ROOT) not in sys.path:
    sys.path.insert(0, str(KRONOS_ROOT))

from model import Kronos, KronosTokenizer, KronosPredictor as _KronosPredictor

from .base import BasePredictor, PredictionResult


class KronosStockPredictor(BasePredictor):
    MODELS = {
        "mini": "NeoQuasar/Kronos-mini",
        "small": "NeoQuasar/Kronos-small",
        "base": "NeoQuasar/Kronos-base",
    }

    def __init__(self, variant: str = "small", device: str = "cpu"):
        self.variant = variant
        self.device = device
        model_id = self.MODELS[variant]

        tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        model = Kronos.from_pretrained(model_id)

        self.predictor = _KronosPredictor(model, tokenizer, max_context=512)

    def predict(self, symbol: str, df: pd.DataFrame, horizon: int = 5) -> PredictionResult:
        # Kronos expects specific column order
        required = ["open", "high", "low", "close", "volume"]
        input_df = df[required].copy()

        future_dates = pd.date_range(
            start=df.index[-1] + pd.Timedelta(days=1),
            periods=horizon,
            freq="B"
        )

        pred_df = self.predictor.predict(
            df=input_df,
            x_timestamp=df.index,
            y_timestamp=future_dates,
            pred_len=horizon,
            T=1.0,
            top_p=0.9,
            sample_count=5,
        )

        # Confidence: based on forecast stability
        last_close = df["close"].iloc[-1]
        pred_close_range = pred_df["close"].max() - pred_df["close"].min()
        confidence = float(np.clip(1.0 - (pred_close_range / (last_close + 1e-8)), 0.0, 1.0))

        return PredictionResult(
            symbol=symbol,
            model_name=f"kronos-{self.variant}",
            horizon=horizon,
            forecast=pred_df,
            confidence=confidence,
            metadata={
                "last_close": float(last_close),
                "device": self.device,
            }
        )
