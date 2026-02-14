#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

REMOTE="${REMOTE:-}"
REMOTE_ROOT="${REMOTE_ROOT:-/srv/cdx-trade/data/server_runs}"
LOCAL_ROOT="${LOCAL_ROOT:-${REPO_ROOT}/data/server_runs_remote}"

if [[ -z "${REMOTE}" ]]; then
  echo "REMOTE is required (example: REMOTE=user@10.0.0.12)"
  exit 1
fi

mkdir -p "${LOCAL_ROOT}"

rsync \
  --archive \
  --compress \
  --human-readable \
  --partial \
  --prune-empty-dirs \
  "${REMOTE}:${REMOTE_ROOT}/" \
  "${LOCAL_ROOT}/"

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
cat >> "${LOCAL_ROOT}/_meta/pull_history.tsv" <<EOF
${PULL_TS}	${REMOTE}	${REMOTE_ROOT}	${RUN_COUNT}	${LATEST_RUN_ID}	${LATEST_SIZE_MB}
EOF

uv run python "${REPO_ROOT}/scripts/home_server/prune_runs.py" \
  --root "${LOCAL_ROOT}" \
  --keep-days "${KEEP_DAYS:-30}" \
  --keep-max-runs "${KEEP_MAX_RUNS:-120}"

echo "synced_to=${LOCAL_ROOT}"
echo "pull_timestamp_utc=${PULL_TS}"
echo "run_count=${RUN_COUNT}"
echo "latest_run_id=${LATEST_RUN_ID}"
