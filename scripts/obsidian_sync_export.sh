#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAULT_ROOT="${OBSIDIAN_VAULT_ROOT:-$HOME/storage/shared/Documents/Obsidian/BR-no-GTA-Vault/BR-no-GTA}"
REPOSITORY="${GITHUB_ACTIONS_REPOSITORY:-zenindiones-maker/BR-no-GTA}"
STATE_DIR="$HOME/.local/state/br-no-gta/obsidian-export"
PYTHON_BIN="$ROOT/.venv/bin/python"

[[ $# -eq 1 ]] || {
  echo "uso: scripts/obsidian_sync_export.sh RUN_ID" >&2
  exit 2
}
RUN_ID="$1"
[[ "$RUN_ID" =~ ^[0-9]+$ ]] || {
  echo "OBSIDIAN_EXPORT_SYNC=FAIL RUN_ID inválido" >&2
  exit 2
}
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="$(command -v python)"
mkdir -p "$STATE_DIR" "$VAULT_ROOT"

DEST="$STATE_DIR/$RUN_ID"
rm -rf "$DEST"
mkdir -p "$DEST"

gh auth status >/dev/null
gh run download "$RUN_ID"   --repo "$REPOSITORY"   --name "obsidian-memory-export-$RUN_ID"   --dir "$DEST"

if [[ -f "$DEST/manifest.json" ]]; then
  EXPORT_ROOT="$DEST"
elif [[ -f "$DEST/obsidian-memory-export/manifest.json" ]]; then
  EXPORT_ROOT="$DEST/obsidian-memory-export"
else
  echo "OBSIDIAN_EXPORT_SYNC=FAIL manifest.json ausente" >&2
  exit 1
fi

"$PYTHON_BIN" - "$EXPORT_ROOT" "$VAULT_ROOT" "$RUN_ID" <<'PY'
from pathlib import Path
import json
import shutil
import sys

source=Path(sys.argv[1]).resolve(strict=True)
target=Path(sys.argv[2]).resolve(strict=True)
manifest=json.loads((source/"manifest.json").read_text(encoding="utf-8"))
if manifest.get("schema")!="obsidian-memory-export/v1":
    raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL schema inválido")
if manifest.get("canonical_source")!="BR SQLite Learning Plane":
    raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL origem canônica inválida")
if manifest.get("obsidian_role")!="PROJECTION_ONLY":
    raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL artifact tentou virar memória canônica")
if manifest.get("OBSIDIAN_CANONICAL_MEMORY")!="NO":
    raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL canonical-memory boundary violado")
if manifest.get("TERMUX_HEAVY_PROCESSING")!="NO":
    raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL A15 boundary violado")

files=manifest.get("files") or []
if not isinstance(files,list) or len(files)>500:
    raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL file count fora do limite")
total=0
validated=[]
for relative in files:
    if not isinstance(relative,str) or not relative.endswith(".md"):
        raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL somente Markdown publicado é aceito")
    rel=Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL path traversal")
    src=(source/rel).resolve(strict=True)
    try:
        src.relative_to(source)
    except ValueError:
        raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL arquivo escapou do artifact")
    if src.is_symlink() or not src.is_file():
        raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL symlink/non-file recusado")
    size=src.stat().st_size
    if size>96*1024:
        raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL Markdown excede 96 KiB")
    total+=size
    if total>5*1024*1024:
        raise SystemExit("OBSIDIAN_EXPORT_SYNC=FAIL pacote excede 5 MiB")
    validated.append((src,rel))

for src,rel in validated:
    dst=target/rel
    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(src,dst)

receipt={
    "status":"PASS",
    "run_id":sys.argv[3],
    "files_copied":len(validated),
    "bytes_copied":total,
    "canonical_source":"BR SQLite Learning Plane",
    "obsidian_role":"PROJECTION_ONLY",
    "TERMUX_HEAVY_PROCESSING":"NO",
    "OBSIDIAN_CANONICAL_MEMORY":"NO",
}
(target/"00-System"/"Last-Memory-Sync.json").parent.mkdir(parents=True,exist_ok=True)
(target/"00-System"/"Last-Memory-Sync.json").write_text(
    json.dumps(receipt,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
    encoding="utf-8",
)
print(f"OBSIDIAN_EXPORT_SYNC=PASS FILES={len(validated)} BYTES={total}")
print("OBSIDIAN_CANONICAL_MEMORY=NO")
print("TERMUX_HEAVY_PROCESSING=NO")
PY
