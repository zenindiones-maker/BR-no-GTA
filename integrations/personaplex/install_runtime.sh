#!/usr/bin/env bash
set -euo pipefail

PERSONAPLEX_REPOSITORY="https://github.com/NVIDIA/personaplex.git"
PERSONAPLEX_REVISION="3428dfd95309a7f3c84fd93259ded0f810d1ff91"
RUNTIME_ROOT="${PERSONAPLEX_RUNTIME_ROOT:-$HOME/.local/share/br-no-gta/personaplex}"
PYTHON_BIN="${PERSONAPLEX_PYTHON:-python3.12}"

command -v git >/dev/null 2>&1 || { echo "PERSONAPLEX_INSTALL=BLOCKED GIT_MISSING"; exit 21; }
command -v pkg-config >/dev/null 2>&1 || { echo "PERSONAPLEX_INSTALL=BLOCKED PKG_CONFIG_MISSING"; exit 22; }
command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "PERSONAPLEX_INSTALL=BLOCKED PYTHON_3_12_MISSING"; exit 23; }
pkg-config --exists opus || { echo "PERSONAPLEX_INSTALL=BLOCKED LIBOPUS_DEV_MISSING"; exit 24; }

mkdir -p "$RUNTIME_ROOT"
if [[ ! -d "$RUNTIME_ROOT/src/.git" ]]; then
  git clone --filter=blob:none "$PERSONAPLEX_REPOSITORY" "$RUNTIME_ROOT/src"
fi

git -C "$RUNTIME_ROOT/src" fetch --no-tags origin "$PERSONAPLEX_REVISION"
git -C "$RUNTIME_ROOT/src" checkout --detach "$PERSONAPLEX_REVISION"
ACTUAL_REVISION="$(git -C "$RUNTIME_ROOT/src" rev-parse HEAD)"
if [[ "$ACTUAL_REVISION" != "$PERSONAPLEX_REVISION" ]]; then
  echo "PERSONAPLEX_INSTALL=FAIL REVISION_MISMATCH"
  exit 25
fi

"$PYTHON_BIN" -m venv "$RUNTIME_ROOT/.venv"
"$RUNTIME_ROOT/.venv/bin/python" -m pip install --disable-pip-version-check "$RUNTIME_ROOT/src/moshi"

mkdir -p "$RUNTIME_ROOT/private-voices" "$RUNTIME_ROOT/model-cache"

"$RUNTIME_ROOT/.venv/bin/python" - <<'PY'
import json
import pathlib
import sys
from importlib.metadata import version

root = pathlib.Path.home() / ".local/share/br-no-gta/personaplex"
configured = pathlib.Path(__import__("os").environ.get("PERSONAPLEX_RUNTIME_ROOT", root))
receipt = {
    "schema": "PersonaPlexInstallReceipt/v1",
    "code_revision": "3428dfd95309a7f3c84fd93259ded0f810d1ff91",
    "package": "moshi-personaplex",
    "package_version": version("moshi-personaplex"),
    "python": sys.version.split()[0],
    "weights_downloaded": False,
    "hf_token_persisted": False,
}
(configured / "install-receipt.json").write_text(
    json.dumps(receipt, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
print("PERSONAPLEX_CODE_INSTALL=PASS")
print("PERSONAPLEX_CODE_REVISION=3428dfd95309a7f3c84fd93259ded0f810d1ff91")
print("PERSONAPLEX_WEIGHTS_DOWNLOADED=NO")
print("PERSONAPLEX_HF_TOKEN_PERSISTED=NO")
PY
