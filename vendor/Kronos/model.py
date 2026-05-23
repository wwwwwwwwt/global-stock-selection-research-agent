"""
Kronos Model Stub
-----------------
This is a minimal stub implementation to allow the adapter to import and run.

TO USE REAL KRONOS:
1. Clone https://github.com/shiyu-coder/Kronos.git
2. Replace this file with the real model.py from the cloned repo.

The stub provides the same public API:
  - KronosTokenizer.from_pretrained(...)
  - Kronos.from_pretrained(...)
  - KronosPredictor(model, tokenizer, max_context=512)
  - predictor.predict(df, x_timestamp, y_timestamp, pred_len, T, top_p, sample_count)
"""

import torch
import torch.nn as nn
import pandas as pd
import numpy as np
from pathlib import Path


class KronosTokenizer:
    """Stub tokenizer."""
    def __init__(self):
        pass

    @classmethod
    def from_pretrained(cls, model_id: str):
        return cls()

    def encode(self, df: pd.DataFrame):
        # Return dummy tensor shape: (batch=1, seq_len, 5)
        return torch.zeros(1, len(df), 5)


class Kronos(nn.Module):
    """Stub Kronos model."""
    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or {}
        # Simple linear projection for stub
        self.proj = nn.Linear(5, 5)

    @classmethod
    def from_pretrained(cls, model_id: str):
        # Load config from HF if available, otherwise use defaults
        try:
            from huggingface_hub import hf_hub_download
            import json
            config_path = hf_hub_download(model_id, "config.json")
            with open(config_path) as f:
                config = json.load(f)
        except Exception:
            config = {
                "d_model": 512, "n_layers": 8, "n_heads": 8,
                "ff_dim": 1024, "s1_bits": 10, "s2_bits": 10
            }
        return cls(config)

    def forward(self, x):
        return self.proj(x)


class KronosPredictor:
    """Stub predictor that generates plausible-looking future candles."""
    def __init__(self, model: Kronos, tokenizer: KronosTokenizer, max_context: int = 512):
        self.model = model
        self.tokenizer = tokenizer
        self.max_context = max_context

    def predict(
        self,
        df: pd.DataFrame,
        x_timestamp=None,
        y_timestamp=None,
        pred_len: int = 5,
        T: float = 1.0,
        top_p: float = 0.9,
        sample_count: int = 1,
    ) -> pd.DataFrame:
        """
        Generate a stub prediction based on recent price history.
        Uses a simple random-walk with mean reversion to look realistic.
        """
        last = df.iloc[-1]
        closes = df["close"].values
        returns = np.diff(closes) / (closes[:-1] + 1e-8)
        vol = np.std(returns) if len(returns) > 1 else 0.01
        mean_return = np.mean(returns) if len(returns) > 1 else 0.0

        pred_dates = y_timestamp if y_timestamp is not None else pd.date_range(
            start=df.index[-1] + pd.Timedelta(days=1), periods=pred_len, freq="B"
        )

        pred_close = [last["close"]]
        for _ in range(pred_len):
            ret = np.random.normal(mean_return, vol)
            pred_close.append(pred_close[-1] * (1 + ret))
        pred_close = np.array(pred_close[1:])

        # Derive OHLC from close + volatility
        pred_open = np.concatenate([[last["close"]], pred_close[:-1]])
        pred_high = np.maximum(pred_open, pred_close) * (1 + np.abs(np.random.normal(0, vol * 0.5, pred_len)))
        pred_low = np.minimum(pred_open, pred_close) * (1 - np.abs(np.random.normal(0, vol * 0.5, pred_len)))
        pred_vol = last["volume"] * (1 + np.random.normal(0, 0.2, pred_len))
        pred_vol = np.maximum(pred_vol, last["volume"] * 0.3)

        result = pd.DataFrame({
            "open": pred_open,
            "high": pred_high,
            "low": pred_low,
            "close": pred_close,
            "volume": pred_vol.astype(int),
        }, index=pred_dates[:pred_len])

        return result
