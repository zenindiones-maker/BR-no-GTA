#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

bash "$SCRIPT_DIR/install-xpra-stable.sh"

bash "$SCRIPT_DIR/ensure-apt-packages.sh" \
  iproute2 \
  mediainfo \
  sox \
  libsox-fmt-all \
  rubberband-cli

mkdir -p /tmp/br-media-scratch /tmp/br-media-cache
chmod 700 /tmp/br-media-scratch /tmp/br-media-cache

bash "$SCRIPT_DIR/br-start-professional-desktop.sh"
bash "$SCRIPT_DIR/br-professional-doctor.sh"

echo "BR_PRO_V3_UPGRADE=PASS"
echo "WORKSTATION_ROLE=MEDIA_VIDEO_QA"
echo "MASTER_FINAL_TARGET=1920x1080_30_H264_AAC"
echo "PAID_FALLBACK=FALSE"
echo "UNKNOWN_COST_FALLBACK=FALSE"
echo "REAPER_REQUIRED=FALSE"
