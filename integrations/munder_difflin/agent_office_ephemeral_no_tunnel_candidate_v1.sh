#!/usr/bin/env bash
# Security research candidate only. NOT approved for production Agent Office.
# Invoked exclusively in isolated CI on the exact pinned Munder checkout.
set -euo pipefail
upstream="${1:?Usage: agent_office_ephemeral_no_tunnel_candidate_v1.sh <pinned-upstream>}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
test "${GITHUB_ACTIONS:-}" = "true"
test "${GITHUB_REPOSITORY:-}" = "zenindiones-maker/BR-no-GTA"
test "${GITHUB_REF_NAME:-}" = "work/br-agent-office-upstream-high-triage-v1"
test -d "$upstream/.git"
python3 scripts/agent_office_preflight.py --upstream-dir "$upstream" >/dev/null
test -z "$(git -C "$upstream" status --porcelain)"

# Keep before/after evidence OUTSIDE both versioned repositories.
tmp="$(mktemp -d "${RUNNER_TEMP:?}/br-agent-office-pinned-snapshot.XXXXXXXX")"
mkdir -p "$tmp/src/main"
cp "$upstream/package.json" "$upstream/package-lock.json" "$tmp/"
cp "$upstream/src/main/webhook.ts" "$upstream/src/main/slack.ts" "$tmp/src/main/"
# Candidate is the mutable ephemeral upstream checkout; never modify BR files.
python3 scripts/br_agent_office_tunnel_removal_candidate.py \
  --source "$tmp" --candidate "$upstream"

(
  cd "$upstream"
  npm pkg set 'overrides.proxy-addr=2.0.8'
  npm install --package-lock-only --ignore-scripts --no-audit --no-fund
  npm audit fix --package-lock-only --ignore-scripts --omit=dev --no-fund --no-force
  npm audit --omit=dev --json > "${RUNNER_TEMP}/br-agent-office-candidate-final-audit.json"
  python3 - <<'PY'
import json
import os
from pathlib import Path
a = json.loads((Path(os.environ["RUNNER_TEMP"]) / "br-agent-office-candidate-final-audit.json").read_text())
if not isinstance(a.get("vulnerabilities"), dict):
    raise RuntimeError("NPM_AUDIT_UNAVAILABLE")
bad = {
    n: v.get("severity") for n, v in a["vulnerabilities"].items()
    if v.get("severity") in ("high", "critical")
}
if bad:
    raise RuntimeError("AGENT_OFFICE_CANDIDATE_HAS_UNREVIEWED_HIGH_OR_CRITICAL")
print("BR_AGENT_OFFICE_CANDIDATE_HIGH=0")
print("BR_AGENT_OFFICE_CANDIDATE_CRITICAL=0")
PY
  # Never permit install lifecycle scripts or a Node/Electron agent runtime.
  npm ci --ignore-scripts --no-audit --no-fund
  npm run typecheck:node
  echo "BR_AGENT_OFFICE_PINNED_NO_TUNNEL_TYPECHECK=PASS"
)
test "$(git -C "$upstream" rev-parse HEAD)" = "6248293a7cd9dfdbf9633d12bbe857831ccfee88"
test -z "$(git -C "$repo_root" status --porcelain --untracked-files=no)"
echo "BR_AGENT_OFFICE_CANONICAL_SOURCE_UNCHANGED=TRUE"
echo "BR_AGENT_OFFICE_RUNTIME_ADMISSION=BLOCKED_INDEPENDENT_REVIEW"
