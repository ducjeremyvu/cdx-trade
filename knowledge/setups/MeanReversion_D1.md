MeanReversion_D1

Setup definition
- Go long if yesterday's close < prior day's low.
- Entry uses next session after market close (daily bars only).

Timeframe and data
- Daily bars.
- Paper data is 15-minute delayed, so signals are evaluated after close.

Entry rule
- Condition: close[t-1] < low[t-2].
- Entry: market on next session (paper) or limit if configured.

Invalidation
- Fails if price closes below yesterday's low.

Stop loss logic
- Stop below yesterday's low (rule-based).

Take profit logic
- 2R target from entry (risk multiple defined by entry - stop).

Market context
- Range/mean-reversion regime.

Notes
- This setup assumes a short-term overextension and a bounce back.
