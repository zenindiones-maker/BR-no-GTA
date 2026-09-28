#!/usr/bin/env bash
# Install only the pinned Superpowers DSH provider declared by BR-no-GTA.
set -euo pipefail

profile="${1:-headless}"
[[ "$(uname -s)" = Linux && -z "${TERMUX_VERSION:-}" && "${PREFIX:-}" != *com.termux* ]] || {
  echo "Superpowers DSH bootstrap is cloud/CI only; Termux is forbidden." >&2
  exit 2
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
manifest="$repo_root/config/agent_skill_pack_v1.json"
test -f "$manifest"

mapfile -t meta < <(
  python3 - "$manifest" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
entries = [item for item in manifest["skills"] if item["skill_id"] == "superpowers"]
if len(entries) != 1:
    raise SystemExit("expected exactly one superpowers manifest entry")
entry = entries[0]
if manifest.get("superpowers_bootstrap_global") is not False:
    raise SystemExit("global Superpowers bootstrap must remain disabled")
if entry.get("authority") != "NONE":
    raise SystemExit("Superpowers provider authority must remain NONE")
source = entry["source"]
print(source["repository"])
print(source["commit"])
print(entry["provider_id"])
PY
)

source_repo="${meta[0]}"
source_commit="${meta[1]}"
provider_id="${meta[2]}"
[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Invalid Superpowers source pin" >&2
  exit 2
}
test "$provider_id" = "superpowers-dsh"

tooling_root="${BR_AGENT_TOOLING_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/br-agent-tooling}"
mkdir -p "$tooling_root"
source_dir="$tooling_root/superpowers-dsh-$source_commit"

if [[ ! -d "$source_dir/.git" ]]; then
  git clone --no-checkout "https://github.com/${source_repo}.git" "$source_dir"
fi

git -C "$source_dir" fetch origin "$source_commit"
git -C "$source_dir" checkout --detach "$source_commit"
test "$(git -C "$source_dir" rev-parse HEAD)" = "$source_commit"
test -z "$(git -C "$source_dir" status --porcelain)"

python3 - "$source_dir/package.json" <<'PY'
import json
import sys
from pathlib import Path

package = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert package["name"] == "superpowers-dsh"
assert package["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
PY

dsh_version="${DSH_VERSION:-0.1.7-rc.2}"
npx --yes "@deepseek-ai/dsh@${dsh_version}" \
  plugin --profile "$profile" add "$source_dir"

plugin_list="$(npx --yes "@deepseek-ai/dsh@${dsh_version}" plugin --profile "$profile" list)"
printf '%s\n' "$plugin_list"
grep -q 'superpowers-dsh' <<<"$plugin_list"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    echo "BR_SUPERPOWERS_DSH_SOURCE=$source_dir"
    echo "BR_SUPERPOWERS_DSH_COMMIT=$source_commit"
  } >> "$GITHUB_ENV"
fi

echo "SUPERPOWERS_PROVIDER_INSTALL=PASS"
echo "SUPERPOWERS_BOOTSTRAP_GLOBAL=OFF"
