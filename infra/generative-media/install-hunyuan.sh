#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SRC="$ROOT/.runtime/generative-media/hunyuanvideo-i2v/src"
ENV="$ROOT/.runtime/generative-media/hunyuanvideo-i2v/venv"
CLIP_PIN="d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"

test -d "$SRC/.git" || { echo "STOP_SOURCE_NOT_BOOTSTRAPPED"; exit 20; }
test "$(git -C "$SRC" rev-parse HEAD)" = "c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949"

if [[ -n "${TERMUX_VERSION:-}" ]] || [[ "$(uname -o 2>/dev/null || true)" == "Android" ]]; then
  echo "HUNYUAN_INSTALLATION=BLOCKED_UNSUPPORTED_TERMUX_ANDROID_HOST"
  echo "REQUIRES=Linux executor with Python 3.11 and NVIDIA/CUDA-compatible runtime"
  exit 30
fi

test "$(uname -s)" = "Linux" || { echo "STOP_LINUX_REQUIRED"; exit 31; }
command -v python3.11 >/dev/null || { echo "STOP_PYTHON_3_11_REQUIRED"; exit 32; }

python3.11 -m venv "$ENV"
"$ENV/bin/python" -m pip install --upgrade pip

"$ENV/bin/python" -m pip install \
  torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 \
  --index-url https://download.pytorch.org/whl/cu124

REQ="$ROOT/.runtime/generative-media/hunyuanvideo-i2v/requirements.pinned.txt"
sed \
  "s#git+https://github.com/openai/CLIP.git#git+https://github.com/openai/CLIP.git@${CLIP_PIN}#" \
  "$SRC/requirements.txt" > "$REQ"

grep -F "git+https://github.com/openai/CLIP.git@${CLIP_PIN}" "$REQ" >/dev/null

"$ENV/bin/python" -m pip install -r "$REQ"
"$ENV/bin/python" -m pip install ninja
"$ENV/bin/python" -m pip install \
  git+https://github.com/Dao-AILab/flash-attention.git@v2.6.3
"$ENV/bin/python" -m pip install xfuser==0.4.0

"$ENV/bin/python" - <<'PY'
import torch
import diffusers
import transformers
import deepspeed
import xfuser
print("HUNYUAN_IMPORT_SMOKE=PASS")
print("TORCH_VERSION=" + torch.__version__)
print("CUDA_AVAILABLE=" + str(torch.cuda.is_available()))
PY

test -f "$SRC/sample_image2video.py"
echo "HUNYUAN_SOURCE_PIN_VERIFIED=YES"
echo "HUNYUAN_INSTALLATION=PASS"
echo "HUNYUAN_WEIGHTS_DOWNLOADED=NO"
echo "HUNYUAN_REAL_GENERATION_SMOKE=NOT_RUN"
