from __future__ import annotations

import pandas as pd

from alpaca_client import AlpacaClient


def _setup_enabled(allowed_setups: set[str] | None, name: str) -> bool:
    if not allowed_setups:
        return True
    return name in allowed_setups


def find_trade_idea(
    client: AlpacaClient,
    symbol: str,
    allowed_setups: set[str] | None = None,
) -> dict | None:
    bars = client.get_recent_daily_bars(symbol)
    if bars is None or bars.empty:
        return None

    bars = bars.reset_index()
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True).dt.tz_convert(
        "America/New_York"
    )
    bars = bars.sort_values("timestamp")

    today = pd.Timestamp.now(tz="America/New_York").date()
    now = pd.Timestamp.now(tz="America/New_York")
    daily_bar_ready = now.time() >= pd.Timestamp("16:20").time()
    if bars["timestamp"].dt.date.max() == today and not daily_bar_ready:
        bars = bars[bars["timestamp"].dt.date < today]

    if len(bars) < 2:
        return None

    prior_bar = bars.iloc[-2]
    latest_bar = bars.iloc[-1]

    if latest_bar["close"] <= prior_bar["high"]:
        if latest_bar["close"] >= prior_bar["low"]:
            return None
        if not _setup_enabled(allowed_setups, "MeanReversion_D1"):
            return None
        return {
            "symbol": symbol,
            "direction": "long",
            "setup_name": "MeanReversion_D1",
            "entry_reason": (
                "Using completed daily bars due to 15-min delayed data; "
                "yesterday close < prior day low"
            ),
            "invalidation_reason": "Closes below yesterday low",
            "stop_loss_logic": f"Below yesterday low ({latest_bar['low']:.2f})",
            "take_profit_logic": "2R target",
            "market_context": "range",
            "emotional_state": "calm",
        }

    if not _setup_enabled(allowed_setups, "PrevDayBreakout_D1"):
        return None
    return {
        "symbol": symbol,
        "direction": "long",
        "setup_name": "PrevDayBreakout_D1",
        "entry_reason": (
            "Using completed daily bars due to 15-min delayed data; "
            "yesterday close > prior day high"
        ),
        "invalidation_reason": "Closes back below prior day high",
        "stop_loss_logic": f"Below prior day low ({prior_bar['low']:.2f})",
        "take_profit_logic": "2R target",
        "market_context": "trend",
        "emotional_state": "calm",
    }
