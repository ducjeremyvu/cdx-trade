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

CONFIG_PATH="${CONFIG_PATH:-configs/etf_core_1k.json}"
RUN_ID="${RUN_ID:-$(date -u +%Y-%m-%dT%H%M%SZ)}"
RUN_ROOT="${RUN_ROOT:-${REPO_ROOT}/data/server_runs}"
RUN_DIR="${RUN_ROOT}/${RUN_ID}"
LOG_DIR="${RUN_DIR}/logs"
REPORT_DIR="${RUN_DIR}/reports"
BACKTEST_DIR="${RUN_DIR}/backtests"
PORTFOLIO_DIR="${RUN_DIR}/portfolio"
QUEUE_DIR="${RUN_DIR}/queue"

mkdir -p "${LOG_DIR}" "${REPORT_DIR}" "${BACKTEST_DIR}" "${PORTFOLIO_DIR}" "${QUEUE_DIR}"

MAIN_CMD=(uv run python main.py --config "${CONFIG_PATH}")
CURRENT_STEP="bootstrap"
PIPELINE_STATUS="ok"

notify_pipeline() {
  local rc="$1"
  if [[ "${rc}" -ne 0 ]]; then
    PIPELINE_STATUS="error"
  fi
  uv run python scripts/home_server/send_notification.py \
    --run-dir "${RUN_DIR}" \
    --run-id "${RUN_ID}" \
    --status "${PIPELINE_STATUS}" \
    --failed-step "${CURRENT_STEP}" || true
}

trap 'notify_pipeline "$?"' EXIT

run_cmd() {
  local name="$1"
  shift
  CURRENT_STEP="${name}"
  echo "== ${name} =="
  "$@" | tee "${LOG_DIR}/${name}.log"
}

run_cmd "sync" "${MAIN_CMD[@]}" sync --limit 300
run_cmd "scan" "${MAIN_CMD[@]}" scan --output "${REPORT_DIR}/scan.md"

uv run python - <<'PY' > "${QUEUE_DIR}/symbol_setup_pairs.tsv"
import json
import os
from pathlib import Path

config_path = Path(os.environ["CONFIG_PATH"])
config = json.loads(config_path.read_text())
setups_by_symbol = config.get("setups_by_symbol", {})
for symbol in sorted(setups_by_symbol.keys()):
    for setup in sorted(setups_by_symbol[symbol]):
        print(f"{symbol}\t{setup}")
PY

while IFS=$'\t' read -r symbol _setup; do
  [[ -z "${symbol}" ]] && continue
  run_cmd "signal_${symbol}" "${MAIN_CMD[@]}" signal --symbol "${symbol}"
done < "${QUEUE_DIR}/symbol_setup_pairs.tsv"

run_cmd "prioritize_pending" \
  "${MAIN_CMD[@]}" prioritize-pending \
  --max-keep "${MAX_PENDING_KEEP:-1}" \
  --min-score "${MIN_PENDING_SCORE:-0.0}" \
  --lookback-days "${PENDING_SCORE_LOOKBACK_DAYS:-180}"

TOP_PENDING_ID="$("${MAIN_CMD[@]}" signal-queue --status pending | awk '/^signal_id=/{print $1}' | head -n1 | cut -d= -f2)"
if [[ -n "${TOP_PENDING_ID}" ]]; then
  run_cmd "approve_signal_top" \
    "${MAIN_CMD[@]}" approve-signal \
    --signal-id "${TOP_PENDING_ID}" \
    --reason "auto nightly top pending after prioritize"
else
  echo "== approve_signal_top =="
  echo "no pending signals to approve"
fi

run_cmd "time_stop_close" "${MAIN_CMD[@]}" time-stop-close --execute
run_cmd "momentum_close" "${MAIN_CMD[@]}" momentum-close --execute
run_cmd "daily_report" "${MAIN_CMD[@]}" daily-report --output-dir "${REPORT_DIR}"
run_cmd "ops_report" "${MAIN_CMD[@]}" ops-report --output "${REPORT_DIR}/ops.md"
run_cmd "go_live_snapshot" "${MAIN_CMD[@]}" go-live-snapshot --output "${REPORT_DIR}/go_live_snapshot.md"
run_cmd "economics_check" "${MAIN_CMD[@]}" economics-check
run_cmd "decision_quality" "${MAIN_CMD[@]}" decision-quality --lookback-days 30
run_cmd "weekly_profile_compare" "${MAIN_CMD[@]}" weekly-profile-compare --root "${RUN_ROOT}" --days 7

run_cmd "signal_queue_pending" "${MAIN_CMD[@]}" signal-queue --status pending --verbose
run_cmd "signal_queue_executed" "${MAIN_CMD[@]}" signal-queue --status executed --verbose
run_cmd "signal_queue_ignored" "${MAIN_CMD[@]}" signal-queue --status ignored --verbose

while IFS=$'\t' read -r symbol setup; do
  [[ -z "${symbol}" || -z "${setup}" ]] && continue
  for window in 30 90 180; do
    out="${BACKTEST_DIR}/backtest_${symbol}_${setup}_${window}d.csv"
    run_cmd "backtest_${symbol}_${setup}_${window}d" \
      "${MAIN_CMD[@]}" backtest \
      --symbol "${symbol}" \
      --setup "${setup}" \
      --recent-days "${window}" \
      --output "${out}"
  done
done < "${QUEUE_DIR}/symbol_setup_pairs.tsv"

run_cmd "portfolio_constrained" \
  "${MAIN_CMD[@]}" backtest-portfolio \
    --recent-days 180 \
    --rank-by trailing_blended_avg_r \
    --output-trades "${PORTFOLIO_DIR}/trades_constrained.csv" \
    --output-skips "${PORTFOLIO_DIR}/skips_constrained.csv" \
    --output-signals "${PORTFOLIO_DIR}/signals_constrained.csv"

run_cmd "portfolio_constrained_capacity3" \
  "${MAIN_CMD[@]}" backtest-portfolio \
    --recent-days 180 \
    --max-open-positions 3 \
    --rank-by trailing_avg_r \
    --output-trades "${PORTFOLIO_DIR}/trades_constrained_capacity3.csv" \
    --output-skips "${PORTFOLIO_DIR}/skips_constrained_capacity3.csv" \
    --output-signals "${PORTFOLIO_DIR}/signals_constrained_capacity3.csv"

run_cmd "portfolio_unconstrained" \
  "${MAIN_CMD[@]}" backtest-portfolio \
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

CURRENT_STEP="complete"
echo "run_dir=${RUN_DIR}"
