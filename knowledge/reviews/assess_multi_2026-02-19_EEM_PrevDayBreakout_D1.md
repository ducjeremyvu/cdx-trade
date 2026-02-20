Assess multi (2026-02-19)

signal_id: 0bb7cd06-81b9-4a15-9b74-329d36d538d0
symbol: EEM
setup: PrevDayBreakout_D1

windows:
- 30d: trades=15 win_rate=0.53 avg_r=0.17 median_r=0.10 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_EEM_PrevDayBreakout_D1_30d.csv
- 90d: trades=38 win_rate=0.61 avg_r=0.39 median_r=0.26 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_EEM_PrevDayBreakout_D1_90d.csv
- 180d: trades=80 win_rate=0.62 avg_r=0.47 median_r=0.43 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_EEM_PrevDayBreakout_D1_180d.csv

thresholds:
- min_trades_30=5 min_trades_90=8 min_trades_180=20
- min_avg_r_30=0.30 min_avg_r_90=0.10 min_avg_r_180=0.10
- min_median_r_180=0.00
- max_hot_ratio=2.00 avg_r_floor=0.05

derived:
- avg_r_30=0.17 avg_r_90=0.39 avg_r_180=0.47
- median_r_180=0.43
- hot_ratio=0.36
- executed_trades=0
- executed_loss_streak=0
- recent_losses=0/4 pause_threshold=3
- closed_since_pause=0
- hot_pause_streak=2
- hot_state_path=data/hot_only_state.csv
- hot_paused=false
- hot_pause_reason=cleared by stable approve recommendation

recommendation: approve
hot_only_max_allocation: 20%

