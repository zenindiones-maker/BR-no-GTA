#!/usr/bin/env bash
# One-command acceptance for the bounded BR REA investigation route.
# Do not run on Termux/A15; only the existing BR Codespace or GitHub CI.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != "true" ]]; then
  [[ "${CODESPACES:-}" == "true" ]] || {
    echo "BR_REA_ACCEPTANCE=BLOCKED_UNAUTHORIZED_HOST" >&2
    exit 2
  }
  [[ "${CODESPACE_NAME:-}" == "br-v23-recovery-gxp67g5g7wphwxjw" ]] || {
    echo "BR_REA_ACCEPTANCE=BLOCKED_WRONG_CODESPACE" >&2
    exit 2
  }
fi

repo="$(git rev-parse --show-toplevel)"
remote="$(git -C "$repo" remote get-url origin)"
case "$remote" in
  https://github.com/zenindiones-maker/BR-no-GTA|https://github.com/zenindiones-maker/BR-no-GTA.git|git@github.com:zenindiones-maker/BR-no-GTA.git|git@github.com:zenindiones-maker/BR-no-GTA)
    ;;
  *)
    echo "BR_REA_ACCEPTANCE=BLOCKED_WRONG_REPOSITORY" >&2
    exit 2
    ;;
esac
cd "$repo"
export PYTHONPATH="$repo${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1

python3 -m py_compile app/services/br_rea_investigation_executor.py \
    app/services/owner_voice_dubbing_reference_policy.py \
    tests/test_owner_voice_dubbing_reference_policy.py
python3 -m unittest discover -s tests -p test_br_rea_investigation_executor.py -v
python3 -m pytest -q tests/test_owner_voice_dubbing_reference_policy.py
python3 -m unittest discover -s tests -p test_br_system_static_surface_audit.py -v
python3 scripts/br_system_static_surface_audit.py
python3 scripts/br_rea_investigation_harness_e2e.py
echo "BR_REA_ACCEPTANCE=PASS"
