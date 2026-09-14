#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
RUNTIME="$ROOT/.runtime/generative-media"

if [[ -n "${TERMUX_VERSION:-}" ]] || [[ "$(uname -o 2>/dev/null || true)" == "Android" ]]; then
  echo "MODEL_MATERIALIZATION=BLOCKED_CONTROL_HOST_TERMUX"
  exit 30
fi

command -v huggingface-cli >/dev/null || {
  echo "STOP_HUGGINGFACE_CLI_REQUIRED"
  exit 31
}

download_snapshot() {
  local repo="$1" revision="$2" destination="$3" marker="$4"
  mkdir -p "$destination"
  huggingface-cli download \
    "$repo" \
    --revision "$revision" \
    --local-dir "$destination"
  printf '%s\n' "$revision" > "$marker"
}

HUNYUAN_MODELS="$RUNTIME/hunyuanvideo-i2v/models"
ACE_MODELS="$RUNTIME/ace-step/models"

download_snapshot \
  tencent/HunyuanVideo-I2V \
  3914f209367854b5e470f062c33159d5ab139e1e \
  "$HUNYUAN_MODELS/ckpts" \
  "$HUNYUAN_MODELS/hunyuanvideo-i2v.snapshot"

download_snapshot \
  xtuner/llava-llama-3-8b-v1_1-transformers \
  57be3132de24c7add61292c3bfbfc7c9d56f37ce \
  "$HUNYUAN_MODELS/ckpts/text_encoder_i2v" \
  "$HUNYUAN_MODELS/llava.snapshot"

download_snapshot \
  openai/clip-vit-large-patch14 \
  e9c2a4fe1a4c98286816d3c7392c89c9c9b4865a \
  "$HUNYUAN_MODELS/ckpts/text_encoder_2" \
  "$HUNYUAN_MODELS/clip.snapshot"

download_snapshot \
  ACE-Step/Ace-Step1.5 \
  19671f406d603126926c1b7e2adc169acbcade22 \
  "$ACE_MODELS/checkpoint" \
  "$ACE_MODELS/ace-step.snapshot"

echo "MODEL_SNAPSHOT_MATERIALIZATION=PASS"
echo "MODEL_REVISIONS=PINNED_IMMUTABLE"
