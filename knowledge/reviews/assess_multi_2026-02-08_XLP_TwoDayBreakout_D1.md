Assess multi (2026-02-08)

signal_id: fc5d2bc7-6837-4aab-b175-7e8e66154555
symbol: XLP
setup: TwoDayBreakout_D1

windows:
- 30d: trades=12 win_rate=0.92 avg_r=0.66 median_r=0.49 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_XLP_TwoDayBreakout_D1_30d.csv
- 90d: trades=23 win_rate=0.70 avg_r=0.28 median_r=0.17 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_XLP_TwoDayBreakout_D1_90d.csv
- 180d: trades=36 win_rate=0.56 avg_r=0.02 median_r=0.12 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_XLP_TwoDayBreakout_D1_180d.csv

thresholds:
- min_trades_30=5 min_trades_90=8 min_trades_180=20
- min_avg_r_30=0.30 min_avg_r_90=0.10 min_avg_r_180=0.10
- min_median_r_180=0.00
- max_hot_ratio=2.00 avg_r_floor=0.05

derived:
- avg_r_30=0.66 avg_r_90=0.28 avg_r_180=0.02
- median_r_180=0.12
- hot_ratio=13.15
- loss_streak_30d=0
- hot_kill_streak=3

recommendation: hot-only
hot_only_max_allocation: 20%

