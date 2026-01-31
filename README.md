V0 paper-trading learning system using Alpaca.

Quick start
- Set env vars via `.env` or shell:
  - `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `ALPACA_PAPER=true`
- Optional: `FIXED_POSITION_SIZE=1`, `TRADE_JOURNAL_PATH=data/trade_journal.csv`
- Optional: `NO_TRADE_JOURNAL_PATH=data/no_trade_journal.csv`
- Optional: `PENDING_REVIEWS_PATH=data/pending_reviews.csv`, `REVIEW_QUEUE_PATH=data/review_queue.csv`
- Optional: `SIGNAL_QUEUE_PATH=data/signal_queue.csv`
- Optional: `ENABLED_SETUPS=PrevDayBreakout_D1,MeanReversion_D1`
- Optional: `SETUPS_BY_SYMBOL=QQQ=MeanReversion_D1;IWM=PrevDayBreakout_D1`
- Optional (approval gate): `BACKTEST_GATE_DAYS=60`, `BACKTEST_GATE_MIN_TRADES=10`, `BACKTEST_GATE_MIN_AVG_R=0`, `BACKTEST_GATE_MIN_WIN_RATE=0.45`
- Paper data note: Alpaca paper data is 15-min delayed, so V0 uses completed daily bars.

Run
- Place a trade idea (daily breakout): `python main.py trade --symbol SPY`
- Queue a signal without trading: `python main.py signal --symbol SPY`
- Log an exit + review: `python main.py log-exit --trade-id <id> --exit-price 450.12 --outcome win --r-multiple 1.5 --exit-reason "TP hit" --what-went-right "Waited for break" --what-went-wrong "Late entry" --improvement-idea "Set alert before open"`
- Review: `python main.py review --window daily`
- Write weekly snapshot to knowledge base: `python main.py review-snapshot --date 2026-01-28`
- Summarize no-trade logs: `python main.py no-trade-summary --window weekly`
- Sync entry prices from filled orders: `python main.py sync`
- Run automatically after the market close: `python main.py run-daily --symbol SPY`
- Run automatically after the market close (multi-symbol): `python main.py run-daily --symbol SPY --symbols SPY,QQQ`
- Run daily + write weekly snapshot on Friday: `python main.py run-daily --symbol SPY --mode propose --weekly-snapshot`
- Run in semi-auto mode (queue signals only): `python main.py run-daily --symbol SPY --mode propose`
- Run once immediately (multi-symbol): `python main.py run-once --symbol SPY --symbols SPY,QQQ`
- Recommended V0 universe (based on recent backtests): `python main.py run-daily --symbol QQQ --symbols QQQ,IWM --mode propose`
- List queued signals: `python main.py signal-queue`
- List queued signals with full details: `python main.py signal-queue --verbose`
- Approve a queued signal: `python main.py approve-signal --signal-id <id> --reason "Confirmed daily setup"`
- Ignore a queued signal: `python main.py ignore-signal --signal-id <id> --reason "No conviction"`
- Run continuous exit sync: `python main.py run-sync --interval-minutes 5`
- List trades needing review: `python main.py review-queue`
- Close a position + log review: `python main.py close-position --symbol SPY --outcome win --r-multiple 1.2 --exit-reason "time stop" --what-went-right "Followed plan" --what-went-wrong "Late entry" --improvement-idea "Set alert"`
- Backtest the daily strategy: `python main.py backtest --symbol SPY --start 2023-01-01 --end 2024-01-01 --risk-multiple 2 --time-stop-days 5`
- Backtest mean reversion: `python main.py backtest --symbol SPY --start 2023-01-01 --end 2024-01-01 --setup MeanReversion_D1`
- Backtest recent window: `python main.py backtest --symbol SPY --recent-days 60 --setup MeanReversion_D1`
- Summarize backtest results: `python main.py backtest-summary --trades-path data/backtest_trades.csv --months 6`
- Assess a queued signal with recent window: `python main.py assess-signal --signal-id <id> --recent-days 60`
