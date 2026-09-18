#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT}/.venv/bin/python"
CONTROL="${ROOT}/scripts/telegram_termux_control.sh"
BRANCH="work/gate6f-analytics-learning"
PROOF_DIR="${ROOT}/runtime/telegram-source-proof"
PROOF_FILE="${PROOF_DIR}/real-telegram-source-proof.json"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "REAL_TELEGRAM_SOURCE_PROOF=FAIL missing ${PYTHON_BIN}" >&2
  exit 2
fi
if ! command -v git >/dev/null 2>&1 || ! command -v gh >/dev/null 2>&1; then
  echo "REAL_TELEGRAM_SOURCE_PROOF=FAIL git/gh CLI required" >&2
  exit 2
fi
if [[ ! -x "${CONTROL}" ]]; then
  echo "REAL_TELEGRAM_SOURCE_PROOF=FAIL missing ${CONTROL}" >&2
  exit 2
fi

cd "${ROOT}"
CURRENT_BRANCH="$(git branch --show-current)"
if [[ "${CURRENT_BRANCH}" != "${BRANCH}" ]]; then
  echo "REAL_TELEGRAM_SOURCE_PROOF=FAIL expected branch ${BRANCH}, got ${CURRENT_BRANCH}" >&2
  exit 3
fi

git fetch --quiet origin "${BRANCH}"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "REAL_TELEGRAM_SOURCE_PROOF=FAIL tracked worktree changes present" >&2
  exit 3
fi
if [[ -n "$(git status --porcelain --untracked-files=normal | grep -v '^?? runtime/' || true)" ]]; then
  echo "REAL_TELEGRAM_SOURCE_PROOF=FAIL untracked files outside runtime/" >&2
  exit 3
fi

LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse "origin/${BRANCH}")"
if [[ "${LOCAL_HEAD}" != "${REMOTE_HEAD}" ]]; then
  if git merge-base --is-ancestor "${LOCAL_HEAD}" "${REMOTE_HEAD}"; then
    git merge --ff-only "${REMOTE_HEAD}"
    LOCAL_HEAD="$(git rev-parse HEAD)"
  else
    echo "REAL_TELEGRAM_SOURCE_PROOF=FAIL local HEAD is not an ancestor of remote" >&2
    echo "LOCAL_HEAD=${LOCAL_HEAD}" >&2
    echo "REMOTE_HEAD=${REMOTE_HEAD}" >&2
    exit 3
  fi
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export BR_FRESH_RESEARCH_REF="${BRANCH}"
export BR_OMNIROUTE_REF="${BRANCH}"
export GITHUB_ACTIONS_REPOSITORY="${GITHUB_ACTIONS_REPOSITORY:-zenindiones-maker/BR-no-GTA}"

mkdir -p "${PROOF_DIR}"
rm -f "${PROOF_FILE}"

ARGS=(--output "${PROOF_FILE}")
if [[ $# -gt 1 ]]; then
  echo "usage: bash scripts/prove_real_telegram_source.sh [telegram_input_id]" >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  if [[ ! "$1" =~ ^[1-9][0-9]*$ ]]; then
    echo "telegram_input_id must be a positive integer" >&2
    exit 2
  fi
  ARGS+=(--input-id "$1")
fi

echo "REAL_TELEGRAM_SOURCE_HEAD=${LOCAL_HEAD}"
"${PYTHON_BIN}" scripts/process_real_telegram_source.py "${ARGS[@]}"

"${PYTHON_BIN}" - "${PROOF_FILE}" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

path=Path(sys.argv[1])
if not path.is_file():
    raise SystemExit("proof bundle was not persisted")
proof=json.loads(path.read_text(encoding="utf-8"))
required={
    "REAL_TELEGRAM_SOURCE_INPUT":"PASS",
    "INPUT_CAPTURED":"PASS",
    "SOURCE_LEARNED":"PASS",
    "SOURCE_CONTENT_RESOLVED":"PASS",
    "FRESH_RESEARCH_TRIGGERED":"PASS",
    "CLAIMS_EXTRACTED":"PASS",
    "FACT_CHECK_EXECUTED":"PASS",
    "SOURCE_HIERARCHY_ENFORCED":"PASS",
    "UNVERIFIED_CLAIM_NOT_PROMOTED":"PASS",
    "EDITORIAL_SIGNAL_CREATED":"PASS",
    "HUMAN_INPUT_LINEAGE_PRESERVED":"PASS",
}
bad={key:(expected,proof.get(key)) for key,expected in required.items() if proof.get(key)!=expected}
if bad:
    raise SystemExit(f"real Telegram source proof incomplete: {bad}")
allowed={
    "USE_FOR_VIDEO",
    "MERGE_WITH_EXISTING_GOAL",
    "STORE_FOR_FUTURE",
    "REJECT_LOW_EVIDENCE",
    "REJECT_SATURATED",
}
if proof.get("editorial_decision") not in allowed:
    raise SystemExit(f"unexpected editorial decision: {proof.get('editorial_decision')}")
print("REAL_TELEGRAM_SOURCE_CAUSAL_CHAIN=PASS")
print(f"TELEGRAM_INPUT_ID={proof['telegram_input_id']}")
print(f"SOURCE_CANDIDATE_ID={proof['source_candidate_id']}")
print(f"EDITORIAL_SIGNAL_ID={proof['editorial_signal_id']}")
print(f"EDITORIAL_DECISION={proof['editorial_decision']}")
print(f"SOURCE_STATE={proof['source_state']}")
print(f"FRESH_RESEARCH_EXECUTION_ID={proof['fresh_research_execution_id']}")
PY

bash "${CONTROL}" restart
bash "${CONTROL}" status

echo "REAL_TELEGRAM_SOURCE_PROOF=PASS"
echo "PROOF_FILE=${PROOF_FILE}"
echo "TELEGRAM_EVIDENCE_COMMAND=/evidence"
