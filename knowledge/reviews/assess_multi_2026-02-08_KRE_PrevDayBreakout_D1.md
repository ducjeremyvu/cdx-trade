Assess multi (2026-02-08)

signal_id: cf5a862b-7306-419b-9f52-90ec7ccbb510
symbol: KRE
setup: PrevDayBreakout_D1

windows:
- 30d: trades=9 win_rate=0.56 avg_r=0.34 median_r=0.10 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_KRE_PrevDayBreakout_D1_30d.csv
- 90d: trades=25 win_rate=0.60 avg_r=0.37 median_r=0.41 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_KRE_PrevDayBreakout_D1_90d.csv
- 180d: trades=52 win_rate=0.52 avg_r=0.21 median_r=0.07 best_r=2.00 worst_r=-1.00 trades_path=data/backtest_assess_KRE_PrevDayBreakout_D1_180d.csv

thresholds:
- min_trades_30=5 min_trades_90=8 min_trades_180=20
- min_avg_r_30=0.30 min_avg_r_90=0.10 min_avg_r_180=0.10
- min_median_r_180=0.00
- max_hot_ratio=2.00 avg_r_floor=0.05

derived:
- avg_r_30=0.34 avg_r_90=0.37 avg_r_180=0.21
- median_r_180=0.07
- hot_ratio=1.64
- loss_streak_30d=0
- hot_kill_streak=3

recommendation: approve
hot_only_max_allocation: 20%

