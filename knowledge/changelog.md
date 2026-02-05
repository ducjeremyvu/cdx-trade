Changelog

2026-01-28
- Added semi-auto signal queue with manual approvals.
- Added weekly review summary fields (counts, win rate, avg R, no-trade count).
- Added knowledge base structure and initial setup doc.

2026-01-30
- Added MeanReversion_D1 setup alongside PrevDayBreakout_D1.

2026-02-01
- Added multi-symbol support for run-daily and a run-once command.
- Added study prompts for quiet days.

2026-01-31
- Updated rules to include SPY/QQQ/IWM universe and per-symbol daily limit.
- Generated weekend backtest report.
- Added project state report and setup allowlist based on weekend backtests.
- Refreshed 30/60/90d backtests and tightened backtest gate defaults.
- Added monthly backtest rollup report command and generated latest rollup.
- Moved non-secret runtime specs to config.json and trimmed .env to secrets + CONFIG_PATH.
- Added universe file, batch backtest command, regime filter, and daily scan output.
- Added TwoDayBreakout_D1 setup with backtest + scan support.
- Ran universe batch backtests and generated a daily scan report.
- Ran no-regime batch backtests, auto-updated allowlist, and wrote no-regime weekend report.
- Expanded universe, re-ran regime and no-regime batch backtests, and compared 30d results.
- Expanded universe again and refreshed allowlist + regime/no-regime reports.

2026-02-01
- Added per-symbol setup allowlist and backtest approval gate.
- Added options learning notes (no options execution in V0).
- Added max open positions guard for small accounts.
- Added daily markdown report command.
- Added watch-only symbols (SPY) for signal logging only.
