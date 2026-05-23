from abc import ABC, abstractmethod
from dataclasses import dataclass
import pandas as pd


@dataclass
class PredictionResult:
    symbol: str
    model_name: str
    horizon: int
    forecast: pd.DataFrame  # Future OHLCV
    confidence: float       # 0.0 - 1.0
    metadata: dict


class BasePredictor(ABC):
    @abstractmethod
    def predict(self, symbol: str, df: pd.DataFrame, horizon: int = 5) -> PredictionResult:
        ...
