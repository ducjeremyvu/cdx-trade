Go-live snapshot (2026-02-11)

go_live_ready: false
closed_trades: 0
avg_r: 0.00
max_drawdown_r: 0.00
pending_reviews: 0
pending_signals: 0
max_capital_usd: 1000.00
max_total_open_risk_usd: 20.00

economics:
- projection_mode: manual_config
- projected_monthly_gross_usd: 0.00
- projected_monthly_net_usd: -175.00
- target_net_usd: 100.00
- monthly_total_cost_usd: 175.00

checks:
- min_trades: fail (trades=0 threshold=40)
- avg_r: fail (avg_r=0.00 threshold=0.10)
- max_drawdown_r: pass (max_drawdown_r=0.00 limit=-5.00)
- pending_reviews: pass (pending_reviews=0)
- capital_cap_enabled: pass (max_capital_usd=1000.00)
- risk_cap_enabled: pass (max_total_open_risk_usd=20.00)
- pending_signals: pass (pending_signals=0)
- economic_ready: fail (projected_net=-175.00 target=100.00)
