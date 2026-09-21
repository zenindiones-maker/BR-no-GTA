#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAULT_ROOT="${OBSIDIAN_VAULT_ROOT:-$HOME/storage/shared/Documents/Obsidian/BR-no-GTA-Vault/BR-no-GTA}"
REPOSITORY="${GITHUB_ACTIONS_REPOSITORY:-zenindiones-maker/BR-no-GTA}"
WORKFLOW="obsidian-memory-inbox.yml"
STATE_DIR="$HOME/.local/state/br-no-gta/obsidian-inbox"
PYTHON_BIN="$ROOT/.venv/bin/python"
VIDEO_A_GOAL_ID="${OBSIDIAN_VIDEO_A_GOAL_ID:-93f99ddc-09c7-474b-8849-6981aa78d60c}"

mkdir -p "$STATE_DIR"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="$(command -v python)"

usage() {
  cat >&2 <<'EOF'
uso:
  scripts/obsidian_inbox_dispatch.sh NOTE.md [--goal-id ID] [--task-id ID] [--artifact-ref REF] [--wait]

A nota deve estar dentro de BR-no-GTA/Inbox e ter no máximo 32 KiB.
Sem --wait, o script somente faz o dispatch.
Com --wait, ele espera o workflow, baixa o envelope JSON pequeno e o materializa
deterministicamente no SQLite canônico local. Nenhum LLM/Hermes/mídia roda no A15.
EOF
  exit 2
}

[[ $# -ge 1 ]] || usage
NOTE="$1"
shift
GOAL_ID=""
TASK_ID="human-review"
ARTIFACT_REF=""
WAIT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --goal-id)
      [[ $# -ge 2 ]] || usage
      GOAL_ID="$2"
      shift 2
      ;;
    --task-id)
      [[ $# -ge 2 ]] || usage
      TASK_ID="$2"
      shift 2
      ;;
    --artifact-ref)
      [[ $# -ge 2 ]] || usage
      ARTIFACT_REF="$2"
      shift 2
      ;;
    --wait)
      WAIT=1
      shift
      ;;
    *)
      usage
      ;;
  esac
done

NOTE_ABS="$("$PYTHON_BIN" - "$NOTE" "$VAULT_ROOT" <<'PY'
from pathlib import Path
import sys
note=Path(sys.argv[1]).expanduser().resolve(strict=True)
root=Path(sys.argv[2]).expanduser().resolve(strict=True)
inbox=(root/"Inbox").resolve(strict=True)
if note.is_symlink():
    raise SystemExit("OBSIDIAN_INBOX_DISPATCH=FAIL symlink note is forbidden")
try:
    note.relative_to(inbox)
except ValueError:
    raise SystemExit("OBSIDIAN_INBOX_DISPATCH=FAIL note must be inside BR-no-GTA/Inbox")
raw=note.read_bytes()
if len(raw) > 32 * 1024:
    raise SystemExit("OBSIDIAN_INBOX_DISPATCH=FAIL note exceeds 32 KiB A15 dispatch boundary")
raw.decode("utf-8")
print(note)
PY
)"

META="$("$PYTHON_BIN" - "$NOTE_ABS" <<'PY'
from pathlib import Path
import base64, hashlib, json, re, sys
p=Path(sys.argv[1])
raw=p.read_bytes()
text=raw.decode("utf-8")
lines=text.splitlines()
if not lines or lines[0].strip() != "---":
    raise SystemExit("OBSIDIAN_INBOX_DISPATCH=FAIL frontmatter missing")
try:
    end=next(i for i,x in enumerate(lines[1:],1) if x.strip()=="---")
except StopIteration:
    raise SystemExit("OBSIDIAN_INBOX_DISPATCH=FAIL frontmatter not closed")
meta={}
for line in lines[1:end]:
    if not line.strip():
        continue
    m=re.fullmatch(r"([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*",line)
    if not m:
        raise SystemExit("OBSIDIAN_INBOX_DISPATCH=FAIL unsupported frontmatter")
    meta[m.group(1)]=m.group(2).strip().strip("'\"")
if meta.get("type","").lower()!="human_note":
    raise SystemExit("OBSIDIAN_INBOX_DISPATCH=FAIL type must be human_note")
if not meta.get("target"):
    raise SystemExit("OBSIDIAN_INBOX_DISPATCH=FAIL target missing")
print(json.dumps({
    "target":meta["target"],
    "note_b64":base64.b64encode(raw).decode("ascii"),
    "sha256":hashlib.sha256(raw).hexdigest(),
},separators=(",",":")))
PY
)"

TARGET="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.argv[1])["target"])' "$META")"
NOTE_B64="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.argv[1])["note_b64"])' "$META")"
NOTE_SHA="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.argv[1])["sha256"])' "$META")"

if [[ -z "$GOAL_ID" ]]; then
  case "${TARGET,,}" in
    video-a|video_a|videoa)
      GOAL_ID="$VIDEO_A_GOAL_ID"
      ;;
    *)
      echo "OBSIDIAN_INBOX_DISPATCH=FAIL target '$TARGET' requires --goal-id" >&2
      exit 2
      ;;
  esac
fi

SOURCE_REF="Inbox/$(basename "$NOTE_ABS")"
BRANCH="$(git -C "$ROOT" branch --show-current)"
[[ -n "$BRANCH" ]] || { echo "OBSIDIAN_INBOX_DISPATCH=FAIL detached HEAD" >&2; exit 1; }
DISPATCH_ID="a15-$(date -u +%Y%m%dT%H%M%SZ)-${NOTE_SHA:0:12}"

gh auth status >/dev/null
gh workflow run "$WORKFLOW"   --repo "$REPOSITORY"   --ref "$BRANCH"   -f "dispatch_id=$DISPATCH_ID"   -f "note_b64=$NOTE_B64"   -f "source_ref=$SOURCE_REF"   -f "goal_id=$GOAL_ID"   -f "task_id=$TASK_ID"   -f "artifact_ref=$ARTIFACT_REF"

printf 'OBSIDIAN_INBOX_DISPATCH=PASS\n'
printf 'DISPATCH_ID=%s\n' "$DISPATCH_ID"
printf 'SOURCE_REF=%s\n' "$SOURCE_REF"
printf 'GOAL_ID=%s\n' "$GOAL_ID"
printf 'TERMUX_HEAVY_PROCESSING=NO\n'

[[ "$WAIT" -eq 1 ]] || exit 0

RUN_ID=""
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  RUN_ID="$(gh run list     --repo "$REPOSITORY"     --workflow "$WORKFLOW"     --branch "$BRANCH"     --limit 30     --json databaseId,displayTitle     --jq ".[] | select(.displayTitle == \"Obsidian Inbox $DISPATCH_ID\") | .databaseId"     | head -n 1)"
  [[ -n "$RUN_ID" ]] && break
  sleep 2
done
[[ -n "$RUN_ID" ]] || { echo "OBSIDIAN_INBOX_DISPATCH=FAIL workflow run not found" >&2; exit 1; }

gh run watch "$RUN_ID" --repo "$REPOSITORY" --exit-status

DEST="$STATE_DIR/$DISPATCH_ID"
rm -rf "$DEST"
mkdir -p "$DEST"
gh run download "$RUN_ID"   --repo "$REPOSITORY"   --name "obsidian-inbox-$DISPATCH_ID"   --dir "$DEST"

ENVELOPE="$DEST/canonical-memory-envelope.json"
[[ -s "$ENVELOPE" ]] || { echo "OBSIDIAN_INBOX_DISPATCH=FAIL memory envelope missing" >&2; exit 1; }

"$PYTHON_BIN" "$ROOT/scripts/obsidian_apply_memory_envelope.py"   "$ENVELOPE"   --receipt "$DEST/materialization-receipt.json"

printf 'OBSIDIAN_INBOX_RUN_ID=%s\n' "$RUN_ID"
printf 'OBSIDIAN_MEMORY_ENVELOPE_APPLIED=PASS\n'
printf 'SINGLE_CANONICAL_MEMORY_PLANE=PASS\n'
printf 'TERMUX_HEAVY_PROCESSING=NO\n'
