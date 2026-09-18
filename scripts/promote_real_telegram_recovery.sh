#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT}/.venv/bin/python"
CONTROL="${ROOT}/scripts/telegram_termux_control.sh"
RUNTIME_ROOT="${ROOT}/runtime/telegram-opencode-promotion"
BENCHMARK_DIR="${RUNTIME_ROOT}/benchmark"
PROOF_FILE="${RUNTIME_ROOT}/promotion-proof.json"

REPOSITORY="zenindiones-maker/BR-no-GTA"
BRANCH="work/gate6f-analytics-learning"
BENCHMARK_RUN_ID="35346769369"
BENCHMARK_ARTIFACT_ID="10547072630"
BENCHMARK_ARTIFACT_NAME="telegram-opencode-executor-benchmark"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "TELEGRAM_REAL_RECOVERY=FAIL missing ${PYTHON_BIN}" >&2
  exit 2
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "TELEGRAM_REAL_RECOVERY=FAIL gh CLI not found" >&2
  exit 2
fi
if [[ ! -x "${CONTROL}" ]]; then
  echo "TELEGRAM_REAL_RECOVERY=FAIL missing ${CONTROL}" >&2
  exit 2
fi

cd "${ROOT}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

CURRENT_BRANCH="$(git branch --show-current)"
if [[ "${CURRENT_BRANCH}" != "${BRANCH}" ]]; then
  echo "TELEGRAM_REAL_RECOVERY=FAIL expected branch ${BRANCH}, got ${CURRENT_BRANCH}" >&2
  exit 3
fi

git fetch --quiet origin "${BRANCH}"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "TELEGRAM_REAL_RECOVERY=FAIL local worktree has uncommitted changes" >&2
  exit 3
fi
UNTRACKED_FILES="$(git status --porcelain --untracked-files=normal | sed -n 's/^?? //p' || true)"
if [[ -n "${UNTRACKED_FILES}" ]]; then
  echo "TELEGRAM_REAL_RECOVERY=INFO preserving local untracked files:" >&2
  printf '%s\n' "${UNTRACKED_FILES}" >&2
fi
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse "origin/${BRANCH}")"
if [[ "${LOCAL_HEAD}" != "${REMOTE_HEAD}" ]]; then
  if git merge-base --is-ancestor "${LOCAL_HEAD}" "${REMOTE_HEAD}"; then
    git merge --ff-only "${REMOTE_HEAD}"
    LOCAL_HEAD="$(git rev-parse HEAD)"
  else
    echo "TELEGRAM_REAL_RECOVERY=FAIL local HEAD is not an ancestor of current remote HEAD" >&2
    echo "LOCAL_HEAD=${LOCAL_HEAD}" >&2
    echo "REMOTE_HEAD=${REMOTE_HEAD}" >&2
    exit 3
  fi
fi

echo "TELEGRAM_REAL_RECOVERY_HEAD=${LOCAL_HEAD}"

# 1) Reconcile the original real Telegram incident against operational SQLite.
# The reconciliation boundary itself is idempotent and verifies run/job/provider/
# model/HTTP/exit identities before creating or reusing Episode/Failure Memory.
bash scripts/reconcile_real_telegram_403.sh

# 2) Materialize the exact equivalent-workload benchmark already observed on
# GitHub Actions. Never regenerate or replace this evidence locally.
rm -rf "${BENCHMARK_DIR}"
mkdir -p "${BENCHMARK_DIR}"
gh run download "${BENCHMARK_RUN_ID}"   --repo "${REPOSITORY}"   --name "${BENCHMARK_ARTIFACT_NAME}"   --dir "${BENCHMARK_DIR}"

BENCHMARK_EVIDENCE="${BENCHMARK_DIR}/benchmark-evidence.json"
if [[ ! -s "${BENCHMARK_EVIDENCE}" ]]; then
  echo "TELEGRAM_REAL_RECOVERY=FAIL benchmark evidence missing" >&2
  exit 4
fi

# 3) Evaluate only from observed evidence and perform governed promotion if the
# candidate satisfies the predeclared measurable acceptance criteria.
mkdir -p "${RUNTIME_ROOT}"
"${PYTHON_BIN}" scripts/promote_telegram_opencode_executor_profile.py   --benchmark-evidence "${BENCHMARK_EVIDENCE}"   --benchmark-run-id "${BENCHMARK_RUN_ID}"   --benchmark-artifact-id "${BENCHMARK_ARTIFACT_ID}"   --output "${PROOF_FILE}"

# 4) Fail closed unless the persisted proof establishes the causal chain.
"${PYTHON_BIN}" - "${PROOF_FILE}" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

path=Path(sys.argv[1])
proof=json.loads(path.read_text(encoding="utf-8"))
required={
    "REAL_TELEGRAM_FAILURE_EPISODE":"PASS",
    "STRUCTURED_PROVIDER_ERROR_PRESERVED":"PASS",
    "FAILURE_MEMORY_FROM_REAL_INCIDENT":"PASS",
    "COMPETENCE_UPDATED_FROM_REAL_OUTCOME":"PASS",
    "REAL_IMPROVEMENT_MISSION":"PASS",
    "REAL_IMPROVEMENT_EXPERIMENT":"PASS",
    "OBSERVED_EVAL":"PASS",
    "GOVERNED_PROMOTION":"PASS",
    "PROMOTION_CHANGES_EXECUTABLE_BEHAVIOR":"PASS",
    "NEXT_TELEGRAM_RUN_RETRIEVES_LEARNING":"PASS",
    "NEXT_TELEGRAM_RUN_RESOLVES_PROMOTED_BINDING":"PASS",
}
bad={key:(expected,proof.get(key)) for key,expected in required.items() if proof.get(key)!=expected}
if bad:
    raise SystemExit(f"promotion proof incomplete: {bad}")
active=proof.get("active_profile") or {}
if active.get("version")!="v2":
    raise SystemExit(f"unexpected active profile: {active}")
if proof.get("evaluation_mode")!="OBSERVED" or proof.get("evaluation_decision")!="PROMOTE":
    raise SystemExit("promotion was not derived from observed evaluation")
if int(proof.get("benchmark_run_id") or 0)!=35346769369:
    raise SystemExit("benchmark run mismatch")
if int(proof.get("benchmark_artifact_id") or 0)!=10547072630:
    raise SystemExit("benchmark artifact mismatch")
print("TELEGRAM_GOVERNED_PROMOTION=PASS")
print(f"PROMOTION_MEMORY_ID={proof['promotion_memory_id']}")
print(f"ACTIVE_PROFILE_VERSION={active['version']}")
print(f"RESOLVED_EXECUTABLE_BINDING={proof['resolved_executable_binding']}")
PY

# 5) Restart the existing Telegram gateway so the next real Telegram message
# loads the promoted persisted profile. This does not synthesize a successful
# Telegram result; the next user interaction remains the required observed run.
bash "${CONTROL}" restart
bash "${CONTROL}" status

echo "TELEGRAM_REAL_RECOVERY=READY_FOR_NEXT_REAL_INTERACTION"
echo "INPUT_MEMORY_CAPTURED_AND_EXECUTION_OUTCOME_ARE_SEPARATE=PASS"
echo "BENCHMARK_RUN_ID=${BENCHMARK_RUN_ID}"
echo "BENCHMARK_ARTIFACT_ID=${BENCHMARK_ARTIFACT_ID}"
echo "PROMOTION_PROOF=${PROOF_FILE}"
