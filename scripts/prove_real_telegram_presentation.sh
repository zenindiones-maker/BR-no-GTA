#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT}/.venv/bin/python"
CONTROL="${ROOT}/scripts/telegram_termux_control.sh"
BRANCH="work/gate6f-analytics-learning"
PROOF_DIR="${ROOT}/runtime/telegram-presentation-proof"
PROOF_FILE="${PROOF_DIR}/real-telegram-presentation-proof.json"

cd "${ROOT}"
git fetch --quiet origin "${BRANCH}"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "REAL_TELEGRAM_PRESENTATION_PROOF=FAIL tracked worktree changes present" >&2
  exit 3
fi
if [[ -n "$(git status --porcelain --untracked-files=normal | grep -v '^?? runtime/' || true)" ]]; then
  echo "REAL_TELEGRAM_PRESENTATION_PROOF=FAIL untracked files outside runtime/" >&2
  exit 3
fi
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse "origin/${BRANCH}")"
if [[ "${LOCAL_HEAD}" != "${REMOTE_HEAD}" ]]; then
  if git merge-base --is-ancestor "${LOCAL_HEAD}" "${REMOTE_HEAD}"; then
    git merge --ff-only "${REMOTE_HEAD}"
  else
    echo "REAL_TELEGRAM_PRESENTATION_PROOF=FAIL local HEAD diverged from remote" >&2
    exit 3
  fi
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
bash "${CONTROL}" restart

mkdir -p "${PROOF_DIR}"
ARGS=(--output "${PROOF_FILE}")
if [[ -n "${1:-}" ]]; then ARGS+=(--test-input-id "$1"); fi
if [[ -n "${2:-}" ]]; then ARGS+=(--source-input-id "$2"); fi

"${PYTHON_BIN}" scripts/prove_real_telegram_presentation.py "${ARGS[@]}"

echo "REAL_TELEGRAM_PRESENTATION_PROOF=PASS"
echo "PROOF_FILE=${PROOF_FILE}"
echo "NEXT_REAL_TEST_MESSAGE=Responda apenas: TESTE_OK"
echo "EVIDENCE_COMMAND=/evidence [telegram_input_id]"
