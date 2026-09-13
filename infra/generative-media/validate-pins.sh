#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
RUNTIME="$ROOT/.runtime/generative-media"

test "$(git -C "$RUNTIME/hunyuanvideo-i2v/src" rev-parse HEAD)" = \
  "c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949"
test "$(git -C "$RUNTIME/ace-step/src" rev-parse HEAD)" = \
  "dce621408bee8c31b4fcf4811682eb9359e1bc94"

grep -F 'model_snapshot_revision = "3914f209367854b5e470f062c33159d5ab139e1e"' \
  infra/generative-media/runtime-pins.toml >/dev/null
grep -F 'model_snapshot_revision = "19671f406d603126926c1b7e2adc169acbcade22"' \
  infra/generative-media/runtime-pins.toml >/dev/null

echo "SOURCE_PINS=PASS"
echo "MODEL_SNAPSHOT_PINS=PASS_METADATA_ONLY"
echo "MODEL_WEIGHTS_DOWNLOADED=NO"
