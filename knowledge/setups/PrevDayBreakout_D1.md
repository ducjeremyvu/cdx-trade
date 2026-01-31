PrevDayBreakout_D1

Setup definition
- Go long if yesterday's close > prior day's high.
- Entry uses next session after market close (daily bars only).

Timeframe and data
- Daily bars.
- Paper data is 15-minute delayed, so signals are evaluated after close.

Entry rule
- Condition: close[t-1] > high[t-2].
- Entry: market on next session (paper) or limit if configured.

Invalidation
- Fails if price breaks below prior day's low.

Stop loss logic
- Stop below prior day's low (rule-based).

Take profit logic
- 2R target from entry (risk multiple defined by entry - stop).

Market context
- Trend/Range/Unclear. Default: unclear unless explicitly tagged.

Notes
- This is a learning setup. It favors clarity over responsiveness.
