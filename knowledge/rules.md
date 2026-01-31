Rules and checklists (V0)

Risk policy
- Fixed position size: 1 share (SPY, QQQ, IWM).
- Max trades per day: 1 per symbol.
- No averaging down.
- No new trades if a review is pending from prior trade.

Approval checklist (semi-auto)
- Setup matches the definition exactly.
- Stop and take-profit are clear, specific, and logged.
- Entry reason is 1-2 testable sentences (not vibe-based).
- Emotional state is noted; skip if rushed/FOMO/tired.
- Position size is the fixed size (no overrides).
- Backtest gate must pass for the setup+symbol (recent window).

Exit rules
- Take profit at 2R or stop loss at prior day low.
- If time stop is used, log it explicitly as exit reason.

Universe and data
- Symbols: QQQ, IWM (SPY on hold due to weak backtests).
- Data: daily bars only (paper data is 15-minute delayed).

Review discipline
- Every closed trade must be reviewed the same or next day.
- Weekly review is mandatory.
