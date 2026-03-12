#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

REMOTE="${REMOTE:-}"
REMOTE_ROOT="${REMOTE_ROOT:-/srv/cdx-trade/data/server_runs}"
LOCAL_ROOT="${LOCAL_ROOT:-${REPO_ROOT}/data/server_runs_remote}"
FETCH_RETRIES="${FETCH_RETRIES:-3}"
FETCH_BACKOFF_SECONDS="${FETCH_BACKOFF_SECONDS:-5}"
FETCH_TIMEOUT_SECONDS="${FETCH_TIMEOUT_SECONDS:-60}"
TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD="gtimeout"
fi

if [[ -z "${REMOTE}" ]]; then
  echo "REMOTE is required (example: REMOTE=user@10.0.0.12)"
  exit 1
fi

mkdir -p "${LOCAL_ROOT}"

RSYNC_ERROR=""
RSYNC_STATUS="ok"
for attempt in $(seq 1 "${FETCH_RETRIES}"); do
  if ${TIMEOUT_CMD:-} ${TIMEOUT_CMD:+${FETCH_TIMEOUT_SECONDS}} rsync \
    --archive \
    --compress \
    --human-readable \
    --partial \
    --prune-empty-dirs \
    "${REMOTE}:${REMOTE_ROOT}/" \
    "${LOCAL_ROOT}/"; then
    RSYNC_STATUS="ok"
    RSYNC_ERROR=""
    break
  fi
  RSYNC_STATUS="error"
  RSYNC_ERROR="rsync failed on attempt ${attempt}"
  if [[ "${attempt}" -lt "${FETCH_RETRIES}" ]]; then
    sleep "$((FETCH_BACKOFF_SECONDS * attempt))"
  fi
done

PULL_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_COUNT="$(find "${LOCAL_ROOT}" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
LATEST_MANIFEST="$(find "${LOCAL_ROOT}" -name manifest.json | sort | tail -n 1)"
LATEST_RUN_ID=""
LATEST_SIZE_MB=""

if [[ -n "${LATEST_MANIFEST}" && -f "${LATEST_MANIFEST}" ]]; then
  LATEST_RUN_ID="$(uv run python - <<PY
import json
from pathlib import Path
path = Path("${LATEST_MANIFEST}")
data = json.loads(path.read_text())
print(data.get("run_id", ""))
PY
)"
  LATEST_SIZE_MB="$(uv run python - <<PY
import json
from pathlib import Path
path = Path("${LATEST_MANIFEST}")
data = json.loads(path.read_text())
print(data.get("size_mb", ""))
PY
)"
fi

mkdir -p "${LOCAL_ROOT}/_meta"
uv run python - <<PY
import json
from pathlib import Path

data = {
    "timestamp_utc": "${PULL_TS}",
    "remote": "${REMOTE}",
    "remote_root": "${REMOTE_ROOT}",
    "local_root": "${LOCAL_ROOT}",
    "status": "${RSYNC_STATUS}",
    "error": "${RSYNC_ERROR}",
    "run_count": ${RUN_COUNT},
    "latest_run_id": "${LATEST_RUN_ID}",
    "latest_size_mb": "${LATEST_SIZE_MB}",
}
Path("${LOCAL_ROOT}/_meta/last_fetch.json").write_text(
    json.dumps(data, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
cat >> "${LOCAL_ROOT}/_meta/pull_history.tsv" <<EOF
${PULL_TS}	${REMOTE}	${REMOTE_ROOT}	${RUN_COUNT}	${LATEST_RUN_ID}	${LATEST_SIZE_MB}
EOF

uv run python "${REPO_ROOT}/scripts/home_server/prune_runs.py" \
  --root "${LOCAL_ROOT}" \
  --keep-days "${KEEP_DAYS:-30}" \
  --keep-max-runs "${KEEP_MAX_RUNS:-120}"

if [[ "${RSYNC_STATUS}" != "ok" ]]; then
  echo "fetch_status=error"
  echo "fetch_error=${RSYNC_ERROR}"
  exit 1
fi

echo "synced_to=${LOCAL_ROOT}"
echo "pull_timestamp_utc=${PULL_TS}"
echo "run_count=${RUN_COUNT}"
echo "latest_run_id=${LATEST_RUN_ID}"
