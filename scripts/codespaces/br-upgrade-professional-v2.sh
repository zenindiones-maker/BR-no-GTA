#!/usr/bin/env bash
set -euo pipefail

cd /workspaces/BR-no-GTA

bash scripts/codespaces/install-xpra-stable.sh

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  iproute2 \
  mediainfo

mkdir -p /tmp/br-media-scratch /tmp/br-media-cache

bash scripts/codespaces/br-start-professional-desktop.sh
bash scripts/codespaces/br-professional-doctor.sh

echo "BR_PRO_V2_UPGRADE=PASS"
