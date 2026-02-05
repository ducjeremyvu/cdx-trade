Rules and checklists (V0)

Risk policy
- Fixed position size: 1 share (SPY, QQQ, IWM).
- Max trades per day: 1 per symbol.
- Max open positions: 1.
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
- Watch-only: SPY (signals logged as no-trade).
- Universe file: data/universe.txt (used for scans/backtests).

Setup allowlist (auto-updated from 90d no-regime backtests)
- See knowledge/reviews/allowlist_noregime_2026-01-31.md for current list.
- Other symbols default to enabled_setups unless explicitly listed.

Allowlist enforcement
- allowlist_only is enabled in config.json (symbols not listed are ignored).

Setup definitions (daily bars)
- PrevDayBreakout_D1: yesterday close > prior day high; stop below prior day low.
- MeanReversion_D1: yesterday close < prior day low; stop below yesterday low.
- TwoDayBreakout_D1: yesterday close > prior 2-day high; stop below prior 2-day low.

Backtest gate (aligned to 90d window)
- BACKTEST_GATE_DAYS: 90
- BACKTEST_GATE_MIN_TRADES: 15
- BACKTEST_GATE_MIN_AVG_R: 0.10
- BACKTEST_GATE_MIN_WIN_RATE: 0.48

Regime filter (SMA-based)
- Enabled in config.json.
- PrevDayBreakout_D1 only when fast SMA > slow SMA (trend).
- MeanReversion_D1 only when fast SMA < slow SMA (range).

Review discipline
- Every closed trade must be reviewed the same or next day.
- Weekly review is mandatory.

Config notes
- Non-secret specs live in config.json; env vars override when set.
