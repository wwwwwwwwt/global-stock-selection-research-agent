import sys
from pathlib import Path
import pandas as pd
import numpy as np
import os

# Add vendor Kronos to path
KRONOS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "vendor" / "Kronos"
if str(KRONOS_ROOT) not in sys.path:
    sys.path.insert(0, str(KRONOS_ROOT))

from model import Kronos, KronosTokenizer, KronosPredictor as _KronosPredictor

from .base import BasePredictor, PredictionResult


# Local model directory (under project root)
LOCAL_MODELS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "models"


def _resolve_model_path(hf_repo_id: str, local_name: str) -> str:
    """Prefer local path if exists, otherwise fall back to HF Hub."""
    local_path = LOCAL_MODELS_DIR / local_name
    if local_path.exists() and (local_path / "config.json").exists():
        return str(local_path)
    return hf_repo_id


class KronosStockPredictor(BasePredictor):
    MODELS = {
        "mini": ("NeoQuasar/Kronos-mini", "kronos-mini"),
        "small": ("NeoQuasar/Kronos-small", "kronos-small"),
        "base": ("NeoQuasar/Kronos-base", "kronos-base"),
    }

    def __init__(self, variant: str = "small", device: str = "cpu"):
        self.variant = variant
        self.device = device
        hf_repo_id, local_name = self.MODELS[variant]

        model_path = _resolve_model_path(hf_repo_id, local_name)
        tokenizer_path = _resolve_model_path("NeoQuasar/Kronos-Tokenizer-base", "kronos-tokenizer")

        tokenizer = KronosTokenizer.from_pretrained(tokenizer_path)
        model = Kronos.from_pretrained(model_path)

        # Real KronosPredictor accepts: (model, tokenizer, device, max_context, clip)
        self.predictor = _KronosPredictor(
            model, tokenizer, device=device, max_context=512, clip=5
        )

    def predict(self, symbol: str, df: pd.DataFrame, horizon: int = 5) -> PredictionResult:
        # Real Kronos expects: open, high, low, close, volume (amount auto-computed)
        required = ["open", "high", "low", "close", "volume"]
        input_df = df[required].copy()

        future_dates = pd.date_range(
            start=df.index[-1] + pd.Timedelta(days=1),
            periods=horizon,
            freq="B"
        )

        # Real predict() signature:
        # predict(df, x_timestamp, y_timestamp, pred_len, T=1.0, top_k=0, top_p=0.9,
        #         sample_count=1, verbose=True)
        # NOTE: Kronos expects pd.Series for timestamps (needs .dt accessor)
        pred_df = self.predictor.predict(
            df=input_df,
            x_timestamp=pd.Series(df.index),
            y_timestamp=pd.Series(future_dates),
            pred_len=horizon,
            T=1.0,
            top_k=0,
            top_p=0.9,
            sample_count=5,
            verbose=False,
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
