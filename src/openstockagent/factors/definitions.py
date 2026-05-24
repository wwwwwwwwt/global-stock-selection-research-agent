"""Default factor definitions."""
from __future__ import annotations

from openstockagent.factors.models import FactorDefinition


DEFAULT_FACTOR_DEFINITIONS = [
    FactorDefinition("return_5d", "momentum", "higher_better", "Five-trading-day close-to-close return."),
    FactorDefinition("return_20d", "momentum", "higher_better", "Twenty-trading-day close-to-close return."),
    FactorDefinition("return_60d", "momentum", "higher_better", "Sixty-trading-day close-to-close return."),
    FactorDefinition("ma_trend_score", "trend", "higher_better", "Share of available moving averages below latest close."),
    FactorDefinition("ma_slope_20d", "trend", "higher_better", "Five-day slope of the 20-day moving average."),
    FactorDefinition("volume_expansion_20d", "volume", "higher_better", "Recent volume expansion versus prior 20-day baseline."),
    FactorDefinition("atr_14d", "volatility", "lower_better", "Average true range over 14 days divided by latest close."),
    FactorDefinition("max_drawdown_20d", "risk", "higher_better", "Worst 20-day close drawdown, expressed as a negative return."),
    FactorDefinition("turnover_amount_20d", "liquidity", "higher_better", "Twenty-day average traded amount."),
]

FACTOR_DEFINITIONS_BY_NAME = {definition.factor_name: definition for definition in DEFAULT_FACTOR_DEFINITIONS}
