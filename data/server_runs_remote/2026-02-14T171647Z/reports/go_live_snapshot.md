Go-live snapshot (2026-02-14)

go_live_ready: false
closed_trades: 1
avg_r: -1.00
max_drawdown_r: -1.00
pending_reviews: 0
pending_signals: 8
max_capital_usd: 1000.00
max_total_open_risk_usd: 20.00

economics:
- projection_mode: auto_from_closed_trades
- projected_monthly_gross_usd: -3.33
- projected_monthly_net_usd: -23.33
- target_net_usd: 30.00
- monthly_total_cost_usd: 20.00

checks:
- min_trades: fail (trades=1 threshold=40)
- avg_r: fail (avg_r=-1.00 threshold=0.10)
- max_drawdown_r: pass (max_drawdown_r=-1.00 limit=-5.00)
- pending_reviews: pass (pending_reviews=0)
- capital_cap_enabled: pass (max_capital_usd=1000.00)
- risk_cap_enabled: pass (max_total_open_risk_usd=20.00)
