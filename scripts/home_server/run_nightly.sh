#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

RUN_ID="${RUN_ID:-$(date -u +%Y-%m-%dT%H%M%SZ)}"
RUN_ROOT="${RUN_ROOT:-${REPO_ROOT}/data/server_runs}"
RUN_DIR="${RUN_ROOT}/${RUN_ID}"
LOG_DIR="${RUN_DIR}/logs"
REPORT_DIR="${RUN_DIR}/reports"
BACKTEST_DIR="${RUN_DIR}/backtests"
PORTFOLIO_DIR="${RUN_DIR}/portfolio"
QUEUE_DIR="${RUN_DIR}/queue"

mkdir -p "${LOG_DIR}" "${REPORT_DIR}" "${BACKTEST_DIR}" "${PORTFOLIO_DIR}" "${QUEUE_DIR}"

run_cmd() {
  local name="$1"
  shift
  echo "== ${name} =="
  "$@" | tee "${LOG_DIR}/${name}.log"
}

run_cmd "sync" uv run python main.py sync --limit 300
run_cmd "scan" uv run python main.py scan --output "${REPORT_DIR}/scan.md"
run_cmd "daily_report" uv run python main.py daily-report --output-dir "${REPORT_DIR}"
run_cmd "ops_report" uv run python main.py ops-report --output "${REPORT_DIR}/ops.md"
run_cmd "go_live_snapshot" uv run python main.py go-live-snapshot --output "${REPORT_DIR}/go_live_snapshot.md"
run_cmd "economics_check" uv run python main.py economics-check

run_cmd "signal_queue_pending" uv run python main.py signal-queue --status pending --verbose
run_cmd "signal_queue_executed" uv run python main.py signal-queue --status executed --verbose
run_cmd "signal_queue_ignored" uv run python main.py signal-queue --status ignored --verbose

uv run python - <<'PY' > "${QUEUE_DIR}/symbol_setup_pairs.tsv"
import json
from pathlib import Path

config = json.loads(Path("config.json").read_text())
setups_by_symbol = config.get("setups_by_symbol", {})
for symbol in sorted(setups_by_symbol.keys()):
    for setup in sorted(setups_by_symbol[symbol]):
        print(f"{symbol}\t{setup}")
PY

while IFS=$'\t' read -r symbol setup; do
  [[ -z "${symbol}" || -z "${setup}" ]] && continue
  for window in 30 90 180; do
    out="${BACKTEST_DIR}/backtest_${symbol}_${setup}_${window}d.csv"
    run_cmd "backtest_${symbol}_${setup}_${window}d" \
      uv run python main.py backtest \
      --symbol "${symbol}" \
      --setup "${setup}" \
      --recent-days "${window}" \
      --output "${out}"
  done
done < "${QUEUE_DIR}/symbol_setup_pairs.tsv"

run_cmd "portfolio_constrained" \
  uv run python main.py backtest-portfolio \
    --recent-days 180 \
    --rank-by trailing_blended_avg_r \
    --output-trades "${PORTFOLIO_DIR}/trades_constrained.csv" \
    --output-skips "${PORTFOLIO_DIR}/skips_constrained.csv" \
    --output-signals "${PORTFOLIO_DIR}/signals_constrained.csv"

run_cmd "portfolio_constrained_capacity3" \
  uv run python main.py backtest-portfolio \
    --recent-days 180 \
    --max-open-positions 3 \
    --rank-by trailing_avg_r \
    --output-trades "${PORTFOLIO_DIR}/trades_constrained_capacity3.csv" \
    --output-skips "${PORTFOLIO_DIR}/skips_constrained_capacity3.csv" \
    --output-signals "${PORTFOLIO_DIR}/signals_constrained_capacity3.csv"

run_cmd "portfolio_unconstrained" \
  uv run python main.py backtest-portfolio \
    --recent-days 180 \
    --max-open-positions 0 \
    --max-capital-usd 0 \
    --max-total-open-risk-usd 0 \
    --output-trades "${PORTFOLIO_DIR}/trades_unconstrained.csv" \
    --output-skips "${PORTFOLIO_DIR}/skips_unconstrained.csv" \
    --output-signals "${PORTFOLIO_DIR}/signals_unconstrained.csv"

uv run python scripts/home_server/make_manifest.py \
  --run-dir "${RUN_DIR}" \
  --run-id "${RUN_ID}" \
  --out "${RUN_DIR}/manifest.json"

uv run python scripts/home_server/prune_runs.py \
  --root "${RUN_ROOT}" \
  --keep-days "${KEEP_DAYS:-30}" \
  --keep-max-runs "${KEEP_MAX_RUNS:-120}"

echo "run_dir=${RUN_DIR}"
