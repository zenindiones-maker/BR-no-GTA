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
UNSAFE_UNTRACKED="$(
  git status --porcelain --untracked-files=normal     | grep '^?? '     | grep -Ev '^\?\? (runtime/|data/database/br_no_gta\.db\.backup-[0-9]{8}-[0-9]{6}$)'     || true
)"
if [[ -n "${UNSAFE_UNTRACKED}" ]]; then
  echo "REAL_TELEGRAM_PRESENTATION_PROOF=FAIL unsafe untracked files present" >&2
  printf '%s\n' "${UNSAFE_UNTRACKED}" >&2
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
if [[ -n "${3:-}" ]]; then ARGS+=(--failure-input-id "$3"); fi

"${PYTHON_BIN}" scripts/prove_real_telegram_presentation.py "${ARGS[@]}"

echo "REAL_TELEGRAM_PRESENTATION_PROOF=PASS"
echo "PROOF_FILE=${PROOF_FILE}"
echo "REQUIRED_REAL_SUCCESS_MESSAGE=Responda apenas: TESTE_OK"
echo "REQUIRED_REAL_URL_NEWS_MESSAGE=<uma URL real que resolva e gere EditorialSignal>"
echo "REQUIRED_REAL_EVIDENCE_COMMAND=/evidence <source_input_id>"
echo "REQUIRED_REAL_FAIL_MESSAGE=https://example.invalid/br-no-gta-action-first-proof"
