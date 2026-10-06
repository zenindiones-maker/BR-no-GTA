#!/usr/bin/env bash
set -euo pipefail

BRANCH="work/zero-cost-workstation-v3"
REPO_ROOT="/workspaces/BR-no-GTA"
STATE_ROOT="${HOME}/.local/state/br-no-gta-codespace/runtime-proof"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$STATE_ROOT/$STAMP"
RECEIPT="$OUT_DIR/receipt.txt"

mkdir -p "$OUT_DIR"
exec > >(tee "$RECEIPT") 2>&1

echo "PROJECT=BR-NO-GTA"
echo "WORKSTATION_ROLE=MEDIA_VIDEO_QA"
echo "PROOF_STARTED_UTC=$STAMP"

[[ "${CODESPACES:-}" == "true" ]] || {
  echo "RUNTIME_INSIDE_CODESPACE=BLOCKED_NOT_CODESPACES"
  exit 20
}

cd "$REPO_ROOT"

ACTUAL_BRANCH="$(git branch --show-current)"
ACTUAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse "origin/$BRANCH")"

echo "BRANCH=$ACTUAL_BRANCH"
echo "HEAD=$ACTUAL_HEAD"
echo "REMOTE_HEAD=$REMOTE_HEAD"

[[ "$ACTUAL_BRANCH" == "$BRANCH" ]] || {
  echo "BRANCH_PROOF=FAIL"
  exit 21
}
[[ "$ACTUAL_HEAD" == "$REMOTE_HEAD" ]] || {
  echo "HEAD_EXACT_REMOTE=FAIL"
  exit 22
}

CPU_COUNT="$(nproc)"
MEM_AVAILABLE_MB="$(awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo)"
DISK_FREE_MB="$(df -Pm /workspaces | awk 'NR==2 {print $4}')"
echo "CPU_COUNT=$CPU_COUNT"
echo "MEM_AVAILABLE_MB=$MEM_AVAILABLE_MB"
echo "WORKSPACE_FREE_MB=$DISK_FREE_MB"

[[ "$CPU_COUNT" == "2" ]] || {
  echo "MACHINE_SHAPE_RUNTIME=FAIL"
  exit 23
}

START_NS="$(date +%s%N)"
bash scripts/codespaces/br-start-professional-desktop.sh
START_END_NS="$(date +%s%N)"
STARTUP_MS="$(((START_END_NS - START_NS) / 1000000))"
echo "XPRA_STARTUP_MS=$STARTUP_MS"

bash scripts/codespaces/br-professional-doctor.sh
bash scripts/codespaces/br-media-smoke.sh "$OUT_DIR/media-smoke"

MASTER="$OUT_DIR/media-smoke/master-final.mp4"
PREVIEW="$OUT_DIR/media-smoke/fast-preview.mp4"

timeout 15 mpv   --no-config   --vo=null   --ao=null   --frames=30   --really-quiet   "$PREVIEW"
echo "MPV_PREVIEW_DECODE=PASS"

timeout 15 mpv   --no-config   --vo=null   --ao=pulse   --really-quiet   "$MASTER"
echo "MPV_PULSE_PLAYBACK=PASS"

mediainfo "$MASTER" >"$OUT_DIR/master-mediainfo.txt"
ffprobe -v error -show_streams -show_format "$MASTER" >"$OUT_DIR/master-ffprobe.txt"

xpra info :101 --socket-dir="/tmp/br-runtime-${UID}/xpra"   >"$OUT_DIR/xpra-info.txt"

echo "FAST_PREVIEW=PASS"
echo "MASTER_FINAL_CODEC_SMOKE=PASS"
echo "VIDEO_PLAYBACK=PASS"
echo "DESKTOP_TARGET=1920x1080"
echo "XPRA_REQUIRED=TRUE"
echo "REAPER_REQUIRED=FALSE"
echo "PAID_FALLBACK=FALSE"
echo "UNKNOWN_COST_FALLBACK=FALSE"
echo "RUNTIME_INSIDE_CODESPACE=PASS_AUTOMATED_BOUNDARY"

RECEIPT_SHA256="$(sha256sum "$RECEIPT" | awk '{print $1}')"
echo "RECEIPT=$RECEIPT"
echo "RECEIPT_SHA256=$RECEIPT_SHA256"
