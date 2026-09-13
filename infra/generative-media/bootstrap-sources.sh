#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

RUNTIME="$ROOT/.runtime/generative-media"
mkdir -p "$RUNTIME"

clone_pin() {
  local url="$1" dest="$2" pin="$3"
  if [[ ! -d "$dest/.git" ]]; then
    git clone --filter=blob:none "$url" "$dest"
  fi
  git -C "$dest" fetch --tags origin
  git -C "$dest" checkout --detach "$pin"
  test "$(git -C "$dest" rev-parse HEAD)" = "$pin"
  test -z "$(git -C "$dest" status --porcelain)"
}

clone_pin \
  https://github.com/Tencent-Hunyuan/HunyuanVideo-I2V.git \
  "$RUNTIME/hunyuanvideo-i2v/src" \
  c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949

clone_pin \
  https://github.com/ace-step/ACE-Step-1.5.git \
  "$RUNTIME/ace-step/src" \
  dce621408bee8c31b4fcf4811682eb9359e1bc94

echo "HUNYUAN_SOURCE_PIN=$(git -C "$RUNTIME/hunyuanvideo-i2v/src" rev-parse HEAD)"
echo "ACE_STEP_SOURCE_PIN=$(git -C "$RUNTIME/ace-step/src" rev-parse HEAD)"
echo "MODEL_WEIGHTS_DOWNLOADED=NO"
