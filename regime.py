from __future__ import annotations

import pandas as pd


def detect_regime(bars: pd.DataFrame, fast_sma: int, slow_sma: int) -> str | None:
    if bars is None or bars.empty:
        return None
    if "close" not in bars.columns:
        return None
    if fast_sma < 1 or slow_sma < 2 or slow_sma <= fast_sma:
        raise ValueError("fast_sma must be >= 1 and slow_sma must be > fast_sma")

    closes = pd.to_numeric(bars["close"], errors="coerce").dropna()
    if len(closes) < slow_sma:
        return None

    fast_value = closes.tail(fast_sma).mean()
    slow_value = closes.tail(slow_sma).mean()
    if fast_value > slow_value:
        return "trend"
    if fast_value < slow_value:
        return "range"
    return "neutral"


def regime_allows(setup_name: str, regime: str | None) -> bool:
    if regime is None:
        return False
    if setup_name == "PrevDayBreakout_D1":
        return regime == "trend"
    if setup_name == "TwoDayBreakout_D1":
        return regime == "trend"
    if setup_name == "MeanReversion_D1":
        return regime == "range"
    return False
