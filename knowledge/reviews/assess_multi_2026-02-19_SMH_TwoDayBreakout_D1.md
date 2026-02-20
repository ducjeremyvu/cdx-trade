Assess multi (2026-02-19)

signal_id: ba87225e-b697-4b78-8c8b-149371493c7e
symbol: SMH
setup: TwoDayBreakout_D1

windows:
- 30d: trades=8 win_rate=0.38 avg_r=-0.03 median_r=-0.07 best_r=1.32 worst_r=-1.00 trades_path=data/backtest_assess_SMH_TwoDayBreakout_D1_30d.csv
- 90d: trades=29 win_rate=0.59 avg_r=0.10 median_r=0.28 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_SMH_TwoDayBreakout_D1_90d.csv
- 180d: trades=63 win_rate=0.59 avg_r=0.07 median_r=0.23 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_SMH_TwoDayBreakout_D1_180d.csv

thresholds:
- min_trades_30=5 min_trades_90=8 min_trades_180=20
- min_avg_r_30=0.30 min_avg_r_90=0.10 min_avg_r_180=0.10
- min_median_r_180=0.00
- max_hot_ratio=2.00 avg_r_floor=0.05

derived:
- avg_r_30=-0.03 avg_r_90=0.10 avg_r_180=0.07
- median_r_180=0.23
- hot_ratio=-0.49
- executed_trades=0
- executed_loss_streak=0
- recent_losses=0/4 pause_threshold=3
- closed_since_pause=0
- hot_pause_streak=2
- hot_state_path=data/hot_only_state.csv
- hot_paused=false
- hot_pause_reason=none

recommendation: reject
hot_only_max_allocation: 20%

