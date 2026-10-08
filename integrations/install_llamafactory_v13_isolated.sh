#!/usr/bin/env bash
# Exact official SOURCE PACKAGE and metadata only; no weights/training/GPU.
set -euo pipefail
umask 077
PIN="ce9dc9e072f80fa3abe0989d4ab90da25f083438"
REMOTE="https://github.com/hiyouga/LlamaFactory.git"
PREFIX="${BR_LLAMAFAC_PRIVATE_PREFIX:?Absolute isolated private prefix required}"
[[ "$PREFIX" = /* && ! -e "$PREFIX" && ! -L "$PREFIX" ]] || {
  echo "BR_LLAMAFAC_PRIVATE_PREFIX_INVALID"; exit 2;
}
command -v git >/dev/null
command -v python3 >/dev/null
mkdir -m 700 "$PREFIX"
trap 'rm -rf "$PREFIX"' ERR
git -c credential.helper= clone --quiet --no-checkout --filter=blob:none "$REMOTE" "$PREFIX/src"
git -C "$PREFIX/src" -c credential.helper= checkout --quiet --detach "$PIN"
READBACK="$(git -C "$PREFIX/src" rev-parse HEAD)"
test "$READBACK" = "$PIN"
test -f "$PREFIX/src/LICENSE" && test -f "$PREFIX/src/pyproject.toml"
python3 - "$PREFIX/src/pyproject.toml" <<'PY'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text(encoding="utf-8")
assert 'name = "llamafactory"' in s
assert 'license = "Apache-2.0"' in s
assert 'llamafactory-cli = "llamafactory.cli:main"' in s
assert 'requires-python = ">=3.11.0"' in s
print("BR_LLAMAFAC_ORIGINAL_PACKAGE_CONTRACT=PASS")
PY
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/python" -m pip install -q --disable-pip-version-check --no-deps -e "$PREFIX/src"
"$PREFIX/venv/bin/python" - <<'PY'
from importlib.metadata import version
installed=version("llamafactory")
assert installed
print("BR_LLAMAFAC_PACKAGE_METADATA_INSTALLED=PASS")
print("BR_LLAMAFAC_INSTALLED_PACKAGE_VERSION="+installed)
print("BR_LLAMAFAC_GPU_AND_FULL_RUNTIME_PROVEN=FALSE")
print("BR_LLAMAFAC_REAL_MODEL_FINETUNED=FALSE")
print("BR_LLAMAFAC_VOICE_BR_OWNER_V1_ACCESS=FORBIDDEN")
PY
echo "BR_LLAMAFAC_SOURCE_COMMIT_VERIFIED=$READBACK"
echo "BR_LLAMAFAC_INSTALLATION_SCOPE=EPHEMERAL_SOURCE_AND_METADATA_ONLY"
trap - ERR
