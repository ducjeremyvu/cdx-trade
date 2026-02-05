Project state and results (2026-01-31)

Current system state

- trade_journal rows: 1
- closed trades: 1
- win_rate: 0.00
- avg_r: -1.00
- no_trade_journal rows: 15
- signal_queue rows: 1
- review_queue rows: 0
- pending_reviews rows: 0

Recent execution details (trade_journal)

- last_trade:
  - trade_id: 1f280a53-8be2-4b5b-b0ef-c9964b4773c8
  - symbol: SPY
  - setup_name: PrevDayBreakout_D1
  - entry_ts: 2026-01-28T20:34:25.240946+00:00
  - exit_ts: 2026-01-30T14:30:29.202294+00:00
  - outcome: loss
  - r_multiple: -1.0

Backtest results available in repo (daily bars)

| symbol | setup | window | trades | win_rate | avg_r | median_r | best_r | worst_r | file |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DIA | PrevDayBreakout_D1 | 60d | 4 | 0.00 | -0.65 | -0.68 | -0.24 | -1.00 | data/backtest_DIA_PrevDayBreakout_D1_60d.csv |
| DIA | PrevDayBreakout_D1 | 90d | 15 | 0.40 | 0.07 | -0.33 | 2.00 | -1.00 | data/backtest_DIA_PrevDayBreakout_D1_90d.csv |
| DIA | TwoDayBreakout_D1 | 60d | 1 | 0.00 | -0.20 | -0.20 | -0.20 | -0.20 | data/backtest_DIA_TwoDayBreakout_D1_60d.csv |
| DIA | TwoDayBreakout_D1 | 90d | 9 | 0.33 | -0.23 | -0.21 | 0.59 | -1.00 | data/backtest_DIA_TwoDayBreakout_D1_90d.csv |
| IWM | MeanReversion_D1 | 90d | 3 | 0.33 | 0.00 | -1.00 | 2.00 | -1.00 | data/backtest_IWM_MeanReversion_D1_90d.csv |
| IWM | PrevDayBreakout_D1 | 60d | 4 | 0.25 | 0.02 | -0.46 | 2.00 | -1.00 | data/backtest_IWM_PrevDayBreakout_D1_60d.csv |
| IWM | PrevDayBreakout_D1 | 90d | 10 | 0.60 | 0.57 | 0.90 | 2.00 | -1.00 | data/backtest_IWM_PrevDayBreakout_D1_90d.csv |
| IWM | TwoDayBreakout_D1 | 60d | 4 | 0.25 | -0.24 | -0.46 | 0.99 | -1.00 | data/backtest_IWM_TwoDayBreakout_D1_60d.csv |
| IWM | TwoDayBreakout_D1 | 90d | 9 | 0.56 | 0.22 | 0.48 | 1.43 | -1.00 | data/backtest_IWM_TwoDayBreakout_D1_90d.csv |
| QQQ | MeanReversion_D1 | 90d | 1 | 0.00 | -1.00 | -1.00 | -1.00 | -1.00 | data/backtest_QQQ_MeanReversion_D1_90d.csv |
| QQQ | PrevDayBreakout_D1 | 60d | 6 | 0.50 | 0.09 | -0.16 | 2.00 | -1.00 | data/backtest_QQQ_PrevDayBreakout_D1_60d.csv |
| QQQ | PrevDayBreakout_D1 | 90d | 16 | 0.44 | -0.07 | -0.52 | 2.00 | -1.00 | data/backtest_QQQ_PrevDayBreakout_D1_90d.csv |
| QQQ | TwoDayBreakout_D1 | 60d | 5 | 0.20 | -0.39 | -0.65 | 0.78 | -1.00 | data/backtest_QQQ_TwoDayBreakout_D1_60d.csv |
| QQQ | TwoDayBreakout_D1 | 90d | 14 | 0.36 | -0.28 | -0.37 | 0.78 | -1.00 | data/backtest_QQQ_TwoDayBreakout_D1_90d.csv |
| SPY | PrevDayBreakout_D1 | 60d | 5 | 0.40 | -0.40 | -1.00 | 0.59 | -1.00 | data/backtest_SPY_PrevDayBreakout_D1_60d.csv |
| SPY | PrevDayBreakout_D1 | 90d | 15 | 0.40 | -0.29 | -1.00 | 2.00 | -1.00 | data/backtest_SPY_PrevDayBreakout_D1_90d.csv |
| SPY | TwoDayBreakout_D1 | 60d | 3 | 0.33 | -0.50 | -1.00 | 0.51 | -1.00 | data/backtest_SPY_TwoDayBreakout_D1_60d.csv |
| SPY | TwoDayBreakout_D1 | 90d | 13 | 0.38 | -0.40 | -1.00 | 0.90 | -1.00 | data/backtest_SPY_TwoDayBreakout_D1_90d.csv |
| XLB | MeanReversion_D1 | 60d | 2 | 0.50 | 0.50 | 0.50 | 2.00 | -1.00 | data/backtest_XLB_MeanReversion_D1_60d.csv |
| XLB | MeanReversion_D1 | 90d | 6 | 0.33 | 0.00 | -1.00 | 2.00 | -1.00 | data/backtest_XLB_MeanReversion_D1_90d.csv |
| XLE | MeanReversion_D1 | 90d | 8 | 0.62 | 0.88 | 2.00 | 2.00 | -1.00 | data/backtest_XLE_MeanReversion_D1_90d.csv |
| XLE | PrevDayBreakout_D1 | 90d | 3 | 0.00 | -1.00 | -1.00 | -1.00 | -1.00 | data/backtest_XLE_PrevDayBreakout_D1_90d.csv |
| XLE | TwoDayBreakout_D1 | 90d | 3 | 0.00 | -1.00 | -1.00 | -1.00 | -1.00 | data/backtest_XLE_TwoDayBreakout_D1_90d.csv |
| XLF | MeanReversion_D1 | 90d | 2 | 0.00 | -1.00 | -1.00 | -1.00 | -1.00 | data/backtest_XLF_MeanReversion_D1_90d.csv |
| XLF | PrevDayBreakout_D1 | 60d | 2 | 0.50 | -0.46 | -0.46 | 0.09 | -1.00 | data/backtest_XLF_PrevDayBreakout_D1_60d.csv |
| XLF | PrevDayBreakout_D1 | 90d | 5 | 0.20 | -0.52 | -0.46 | 0.09 | -1.00 | data/backtest_XLF_PrevDayBreakout_D1_90d.csv |
| XLF | TwoDayBreakout_D1 | 60d | 1 | 1.00 | 0.09 | 0.09 | 0.09 | 0.09 | data/backtest_XLF_TwoDayBreakout_D1_60d.csv |
| XLF | TwoDayBreakout_D1 | 90d | 4 | 0.25 | -0.39 | -0.32 | 0.09 | -1.00 | data/backtest_XLF_TwoDayBreakout_D1_90d.csv |
| XLI | MeanReversion_D1 | 90d | 3 | 0.67 | 1.00 | 2.00 | 2.00 | -1.00 | data/backtest_XLI_MeanReversion_D1_90d.csv |
| XLI | PrevDayBreakout_D1 | 60d | 5 | 0.40 | -0.16 | -0.60 | 1.13 | -1.00 | data/backtest_XLI_PrevDayBreakout_D1_60d.csv |
| XLI | PrevDayBreakout_D1 | 90d | 13 | 0.54 | 0.19 | 0.31 | 2.00 | -1.00 | data/backtest_XLI_PrevDayBreakout_D1_90d.csv |
| XLI | TwoDayBreakout_D1 | 60d | 4 | 0.50 | 0.12 | 0.09 | 0.91 | -0.60 | data/backtest_XLI_TwoDayBreakout_D1_60d.csv |
| XLI | TwoDayBreakout_D1 | 90d | 10 | 0.50 | 0.13 | 0.07 | 1.08 | -1.00 | data/backtest_XLI_TwoDayBreakout_D1_90d.csv |
| XLK | MeanReversion_D1 | 60d | 3 | 0.33 | 0.00 | -1.00 | 2.00 | -1.00 | data/backtest_XLK_MeanReversion_D1_60d.csv |
| XLK | MeanReversion_D1 | 90d | 9 | 0.33 | -0.02 | -1.00 | 2.00 | -1.00 | data/backtest_XLK_MeanReversion_D1_90d.csv |
| XLK | PrevDayBreakout_D1 | 90d | 1 | 1.00 | 2.00 | 2.00 | 2.00 | 2.00 | data/backtest_XLK_PrevDayBreakout_D1_90d.csv |
| XLK | TwoDayBreakout_D1 | 90d | 1 | 0.00 | -1.00 | -1.00 | -1.00 | -1.00 | data/backtest_XLK_TwoDayBreakout_D1_90d.csv |
| XLP | MeanReversion_D1 | 90d | 3 | 0.00 | -1.00 | -1.00 | -1.00 | -1.00 | data/backtest_XLP_MeanReversion_D1_90d.csv |
| XLP | PrevDayBreakout_D1 | 60d | 5 | 0.60 | -0.05 | 0.13 | 0.89 | -1.00 | data/backtest_XLP_PrevDayBreakout_D1_60d.csv |
| XLP | PrevDayBreakout_D1 | 90d | 14 | 0.57 | 0.15 | 0.18 | 2.00 | -1.00 | data/backtest_XLP_PrevDayBreakout_D1_90d.csv |
| XLP | TwoDayBreakout_D1 | 60d | 4 | 1.00 | 0.33 | 0.37 | 0.50 | 0.09 | data/backtest_XLP_TwoDayBreakout_D1_60d.csv |
| XLP | TwoDayBreakout_D1 | 90d | 11 | 0.73 | 0.20 | 0.26 | 1.83 | -1.00 | data/backtest_XLP_TwoDayBreakout_D1_90d.csv |
| XLRE | MeanReversion_D1 | 60d | 2 | 0.00 | -1.00 | -1.00 | -1.00 | -1.00 | data/backtest_XLRE_MeanReversion_D1_60d.csv |
| XLRE | MeanReversion_D1 | 90d | 8 | 0.50 | 0.39 | 0.06 | 2.00 | -1.00 | data/backtest_XLRE_MeanReversion_D1_90d.csv |
| XLRE | PrevDayBreakout_D1 | 60d | 1 | 1.00 | 0.28 | 0.28 | 0.28 | 0.28 | data/backtest_XLRE_PrevDayBreakout_D1_60d.csv |
| XLRE | PrevDayBreakout_D1 | 90d | 1 | 1.00 | 0.28 | 0.28 | 0.28 | 0.28 | data/backtest_XLRE_PrevDayBreakout_D1_90d.csv |
| XLRE | TwoDayBreakout_D1 | 60d | 1 | 1.00 | 0.28 | 0.28 | 0.28 | 0.28 | data/backtest_XLRE_TwoDayBreakout_D1_60d.csv |
| XLRE | TwoDayBreakout_D1 | 90d | 1 | 1.00 | 0.28 | 0.28 | 0.28 | 0.28 | data/backtest_XLRE_TwoDayBreakout_D1_90d.csv |
| XLU | MeanReversion_D1 | 60d | 1 | 1.00 | 2.00 | 2.00 | 2.00 | 2.00 | data/backtest_XLU_MeanReversion_D1_60d.csv |
| XLU | MeanReversion_D1 | 90d | 11 | 0.36 | 0.09 | -1.00 | 2.00 | -1.00 | data/backtest_XLU_MeanReversion_D1_90d.csv |
| XLV | PrevDayBreakout_D1 | 60d | 2 | 0.00 | -0.89 | -0.89 | -0.77 | -1.00 | data/backtest_XLV_PrevDayBreakout_D1_60d.csv |
| XLV | PrevDayBreakout_D1 | 90d | 8 | 0.12 | -0.68 | -0.89 | 0.05 | -1.00 | data/backtest_XLV_PrevDayBreakout_D1_90d.csv |
| XLV | TwoDayBreakout_D1 | 60d | 2 | 0.00 | -0.89 | -0.89 | -0.77 | -1.00 | data/backtest_XLV_TwoDayBreakout_D1_60d.csv |
| XLV | TwoDayBreakout_D1 | 90d | 8 | 0.12 | -0.56 | -0.57 | 0.05 | -1.00 | data/backtest_XLV_TwoDayBreakout_D1_90d.csv |
| XLY | MeanReversion_D1 | 60d | 4 | 0.50 | 0.01 | -0.48 | 2.00 | -1.00 | data/backtest_XLY_MeanReversion_D1_60d.csv |
| XLY | MeanReversion_D1 | 90d | 9 | 0.44 | -0.09 | -1.00 | 2.00 | -1.00 | data/backtest_XLY_MeanReversion_D1_90d.csv |
| recent | MeanReversion | recent | 13 | 0.23 | -0.23 | -1.00 | 2.00 | -1.00 | data/backtest_recent_MeanReversion_D1.csv |

Backtest-positive expectancy combos (avg_r > 0, as of current CSVs)

| symbol | setup | window | trades | win_rate | avg_r | file |
| --- | --- | --- | --- | --- | --- | --- |
| XLK | PrevDayBreakout_D1 | 90d | 1 | 1.00 | 2.00 | data/backtest_XLK_PrevDayBreakout_D1_90d.csv |
| XLU | MeanReversion_D1 | 60d | 1 | 1.00 | 2.00 | data/backtest_XLU_MeanReversion_D1_60d.csv |
| XLI | MeanReversion_D1 | 90d | 3 | 0.67 | 1.00 | data/backtest_XLI_MeanReversion_D1_90d.csv |
| XLE | MeanReversion_D1 | 90d | 8 | 0.62 | 0.88 | data/backtest_XLE_MeanReversion_D1_90d.csv |
| IWM | PrevDayBreakout_D1 | 90d | 10 | 0.60 | 0.57 | data/backtest_IWM_PrevDayBreakout_D1_90d.csv |
| XLB | MeanReversion_D1 | 60d | 2 | 0.50 | 0.50 | data/backtest_XLB_MeanReversion_D1_60d.csv |
| XLRE | MeanReversion_D1 | 90d | 8 | 0.50 | 0.39 | data/backtest_XLRE_MeanReversion_D1_90d.csv |
| XLP | TwoDayBreakout_D1 | 60d | 4 | 1.00 | 0.33 | data/backtest_XLP_TwoDayBreakout_D1_60d.csv |
| XLRE | PrevDayBreakout_D1 | 60d | 1 | 1.00 | 0.28 | data/backtest_XLRE_PrevDayBreakout_D1_60d.csv |
| XLRE | PrevDayBreakout_D1 | 90d | 1 | 1.00 | 0.28 | data/backtest_XLRE_PrevDayBreakout_D1_90d.csv |
| XLRE | TwoDayBreakout_D1 | 60d | 1 | 1.00 | 0.28 | data/backtest_XLRE_TwoDayBreakout_D1_60d.csv |
| XLRE | TwoDayBreakout_D1 | 90d | 1 | 1.00 | 0.28 | data/backtest_XLRE_TwoDayBreakout_D1_90d.csv |
| IWM | TwoDayBreakout_D1 | 90d | 9 | 0.56 | 0.22 | data/backtest_IWM_TwoDayBreakout_D1_90d.csv |
| XLP | TwoDayBreakout_D1 | 90d | 11 | 0.73 | 0.20 | data/backtest_XLP_TwoDayBreakout_D1_90d.csv |
| XLI | PrevDayBreakout_D1 | 90d | 13 | 0.54 | 0.19 | data/backtest_XLI_PrevDayBreakout_D1_90d.csv |
| XLP | PrevDayBreakout_D1 | 90d | 14 | 0.57 | 0.15 | data/backtest_XLP_PrevDayBreakout_D1_90d.csv |
| XLI | TwoDayBreakout_D1 | 90d | 10 | 0.50 | 0.13 | data/backtest_XLI_TwoDayBreakout_D1_90d.csv |
| XLI | TwoDayBreakout_D1 | 60d | 4 | 0.50 | 0.12 | data/backtest_XLI_TwoDayBreakout_D1_60d.csv |
| XLU | MeanReversion_D1 | 90d | 11 | 0.36 | 0.09 | data/backtest_XLU_MeanReversion_D1_90d.csv |
| QQQ | PrevDayBreakout_D1 | 60d | 6 | 0.50 | 0.09 | data/backtest_QQQ_PrevDayBreakout_D1_60d.csv |
| XLF | TwoDayBreakout_D1 | 60d | 1 | 1.00 | 0.09 | data/backtest_XLF_TwoDayBreakout_D1_60d.csv |
| DIA | PrevDayBreakout_D1 | 90d | 15 | 0.40 | 0.07 | data/backtest_DIA_PrevDayBreakout_D1_90d.csv |
| IWM | PrevDayBreakout_D1 | 60d | 4 | 0.25 | 0.02 | data/backtest_IWM_PrevDayBreakout_D1_60d.csv |
| XLY | MeanReversion_D1 | 60d | 4 | 0.50 | 0.01 | data/backtest_XLY_MeanReversion_D1_60d.csv |
