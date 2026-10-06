#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

bash "$SCRIPT_DIR/install-xpra-stable.sh"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  iproute2 \
  mediainfo

mkdir -p /tmp/br-media-scratch /tmp/br-media-cache

bash "$SCRIPT_DIR/br-start-professional-desktop.sh"
bash "$SCRIPT_DIR/br-professional-doctor.sh"

echo "BR_PRO_V2_UPGRADE=PASS"
