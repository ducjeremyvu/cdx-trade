Go-live snapshot (2026-02-24)

go_live_ready: false
closed_trades: 3
avg_r: -0.67
max_drawdown_r: -2.45
pending_reviews: 0
pending_signals: 0
max_capital_usd: 1000.00
max_total_open_risk_usd: 20.00

economics:
- projection_mode: auto_from_closed_trades
- projected_monthly_gross_usd: -6.73
- projected_monthly_net_usd: -26.73
- target_net_usd: 30.00
- monthly_total_cost_usd: 20.00

checks:
- min_trades: fail (trades=3 threshold=40)
- avg_r: fail (avg_r=-0.67 threshold=0.10)
- max_drawdown_r: pass (max_drawdown_r=-2.45 limit=-5.00)
- pending_reviews: pass (pending_reviews=0)
- capital_cap_enabled: pass (max_capital_usd=1000.00)
- risk_cap_enabled: pass (max_total_open_risk_usd=20.00)
