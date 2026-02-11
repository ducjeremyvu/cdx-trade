Go-live scorecard (V0)

Purpose
- Define exact gates that must pass before deploying live capital.
- Keep paper and live as separate operating modes under one workflow.

Modes
- Research (paper): build or modify strategy logic.
- Validation (paper-live): execute exactly like live; no discretionary overrides.
- Live-small: minimal risk and strict kill switches.
- Live-scale: increase size only after sustained metrics pass.
- Regression (paper): any strategy change goes back to paper validation.

Initial live goals
- Closed trades >= 40.
- Average R >= 0.10.
- Max drawdown >= -5.00R.
- Pending reviews = 0.
- Capital cap enabled and set to intended budget (current target: 1000 USD).
- Total open risk cap enabled and enforced (current target: 20 USD).
- Economic readiness: projected monthly net >= target monthly net.

Economic readiness inputs (config.json)
- monthly_ai_cost_usd
- monthly_ops_cost_usd
- target_net_usd
- projected_monthly_gross_usd

Target staging
- Near-term validation target: 30 USD net/month.
- Stretch target after stable execution: 100 USD net/month.

Operational policy
- Core setups require stable 30/90/180 behavior.
- Hot-only setups use reduced size and pause/reactivate rules.
- New strategy variants are paper-only until they pass the same gates.

Command
- Run readiness check:
  - `uv run python main.py go-live-check`
- Optional stricter check (no pending signals):
  - `uv run python main.py go-live-check --require-no-pending-signals`
- Include economic gate in go-live check:
  - `uv run python main.py go-live-check --require-economic-ready`
- Run economics-only check:
  - `uv run python main.py economics-check`
- Prune stale pending signals:
  - `uv run python main.py prune-stale-signals --max-age-days 2`
- Write machine-checked snapshot:
  - `uv run python main.py go-live-snapshot --require-no-pending-signals --require-economic-ready`
- Write daily operations report:
  - `uv run python main.py ops-report --require-no-pending-signals --require-economic-ready`

When to step back to paper
- New setup logic or material parameter changes.
- Drawdown breach or kill switch hit.
- Expectancy degradation over rolling windows.
