#!/usr/bin/env bash
# Development tooling only. Does not dispatch production or run generation.
set -euo pipefail
mode="${1:-all}"
case "$mode" in all|codex|higgsfield) ;; *) echo 'Usage: bootstrap.sh [all|codex|higgsfield]' >&2; exit 2;; esac
[[ "$(uname -s)" = Linux && -z "${TERMUX_VERSION:-}" ]] || { echo 'Use a Linux cloud agent, not Termux.' >&2; exit 2; }
command -v git >/dev/null
command -v npm >/dev/null
node -e 'if (Number(process.versions.node.split(".")[0]) < 24) process.exit(1)'
# This directory contains only reproducible packages/source, never authentication.
tooling_root="${BR_AGENT_TOOLING_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/br-agent-tooling}"
mkdir -p "$tooling_root"
tooling_root="$(cd "$tooling_root" && pwd)"
export PATH="$tooling_root/bin:$PATH"
if [[ -n "${GITHUB_PATH:-}" ]]; then printf '%s\n' "$tooling_root/bin" >> "$GITHUB_PATH"; fi
checkout_revision() {
  local url="$1" sha="$2" destination="$3"
  if [[ ! -d "$destination/.git" ]]; then git clone --no-checkout "$url" "$destination"; fi
  git -C "$destination" fetch origin "$sha"
  git -C "$destination" checkout --detach "$sha"
  test "$(git -C "$destination" rev-parse HEAD)" = "$sha"
  test -z "$(git -C "$destination" status --porcelain)"
}
if [[ "$mode" = all || "$mode" = codex ]]; then
  npm install --global --prefix "$tooling_root" @openai/codex@0.154.0
  addy_sha=be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39
  addy_source="$tooling_root/addy-$addy_sha"
  checkout_revision https://github.com/addyosmani/agent-skills.git "$addy_sha" "$addy_source"
  # Explicit compatibility view: all companion files retained; Claude hooks and
  # Chrome DevTools-dependent skill excluded. Never mutate the upstream checkout.
  addy_view="$tooling_root/addy-codex-$addy_sha"
  mkdir -p "$addy_view"
  git -C "$addy_source" archive "$addy_sha" | tar -x -C "$addy_view" \
    --exclude=hooks --exclude=skills/browser-testing-with-devtools
  test "$(find "$addy_view/skills" -name SKILL.md | wc -l)" -eq 24
  test ! -e "$addy_view/hooks"
  codex plugin marketplace add "$addy_view"
  codex plugin add agent-skills@agent-skills
  codex plugin list | awk '/agent-skills@agent-skills/ {print; found=1} END {exit !found}'
fi
if [[ "$mode" = all || "$mode" = higgsfield ]]; then
  npm install --global --prefix "$tooling_root" @higgsfield/cli@1.1.24 skills@1.5.26
  higgs_sha=d071406147a37b835bed09543d85ab3e9bd85c7d
  higgs_source="$tooling_root/higgsfield-$higgs_sha"
  checkout_revision https://github.com/higgsfield-ai/skills.git "$higgs_sha" "$higgs_source"
  skills add "$higgs_source" --agent codex --global --copy -y \
    --skill higgsfield-generate --skill higgsfield-youtube-thumbnail \
    --skill higgsfield-brandkit --skill higgsfield-video-explainer
  skills list --global --agent codex
  higgsfield version
  higgsfield --help >/dev/null
  # Bootstrap never starts login or prints account/session data in CI.
  higgsfield auth --help >/dev/null
fi
printf 'Bootstrap complete. Start a new Codex session. PATH prefix: %s/bin\n' "$tooling_root"
