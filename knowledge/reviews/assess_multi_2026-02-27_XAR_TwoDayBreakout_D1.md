Assess multi (2026-02-27)

signal_id: d683f57f-6595-4f61-abc5-c60ebf8025b4
symbol: XAR
setup: TwoDayBreakout_D1

windows:
- 30d: trades=7 win_rate=0.43 avg_r=-0.28 median_r=-0.14 best_r=0.63 worst_r=-1.00 trades_path=data/backtest_assess_XAR_TwoDayBreakout_D1_30d.csv
- 90d: trades=29 win_rate=0.52 avg_r=0.10 median_r=0.03 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_XAR_TwoDayBreakout_D1_90d.csv
- 180d: trades=61 win_rate=0.57 avg_r=0.25 median_r=0.04 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_XAR_TwoDayBreakout_D1_180d.csv

thresholds:
- min_trades_30=5 min_trades_90=8 min_trades_180=20
- min_avg_r_30=0.30 min_avg_r_90=0.10 min_avg_r_180=0.10
- min_median_r_180=0.00
- max_hot_ratio=2.00 avg_r_floor=0.05

derived:
- avg_r_30=-0.28 avg_r_90=0.10 avg_r_180=0.25
- median_r_180=0.04
- hot_ratio=-1.11
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

