#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SRC="$ROOT/.runtime/generative-media/ace-step/src"

test -d "$SRC/.git" || { echo "STOP_SOURCE_NOT_BOOTSTRAPPED"; exit 20; }
test "$(git -C "$SRC" rev-parse HEAD)" = "dce621408bee8c31b4fcf4811682eb9359e1bc94"

if [[ -n "${TERMUX_VERSION:-}" ]] || [[ "$(uname -o 2>/dev/null || true)" == "Android" ]]; then
  echo "ACE_STEP_INSTALLATION=BLOCKED_CONTROL_HOST_TERMUX"
  echo "REQUIRES=isolated supported Linux/macOS executor; do not install heavy ML stack on BR control device"
  exit 30
fi

command -v uv >/dev/null || { echo "STOP_UV_REQUIRED"; exit 31; }

cd "$SRC"
uv sync --frozen

uv run python - <<'PY'
import importlib.metadata
print("ACE_STEP_IMPORT_SMOKE=PASS")
print("ACE_STEP_DISTRIBUTION_VERSION=" + importlib.metadata.version("ace-step"))
PY

uv run acestep --help >/dev/null
uv run acestep-api --help >/dev/null
uv run acestep-download --help >/dev/null

echo "ACE_STEP_SOURCE_PIN_VERIFIED=YES"
echo "ACE_STEP_INSTALLATION=PASS"
echo "ACE_STEP_WEIGHTS_DOWNLOADED=NO"
echo "ACE_STEP_REAL_GENERATION_SMOKE=NOT_RUN"
