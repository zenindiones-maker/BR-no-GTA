#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "TELEGRAM_INCIDENT_RECONCILIATION=FAIL missing ${PYTHON_BIN}" >&2
  exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "TELEGRAM_INCIDENT_RECONCILIATION=FAIL gh CLI not found" >&2
  exit 2
fi

cd "${ROOT}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

exec "${PYTHON_BIN}" scripts/reconcile_telegram_reasoning_incident.py \
  --repository zenindiones-maker/BR-no-GTA \
  --run-id 35340487375 \
  --job-id 105585029658 \
  --provider opencode \
  --model oc/big-pickle \
  --http-status 403 \
  --exit-code 1
