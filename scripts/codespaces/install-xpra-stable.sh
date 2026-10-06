#!/usr/bin/env bash
set -euo pipefail

EXPECTED_FPR="B4993B57323148E37977E5D873254CAD17978FAF"
XPRA_SOURCES_URL="https://raw.githubusercontent.com/Xpra-org/xpra/v6.5.3/packaging/repos/noble/xpra.sources"
TMP_KEY="$(mktemp)"
trap 'rm -f "$TMP_KEY"' EXIT

if [[ "${CODESPACES:-}" != "true" ]]; then
  echo "XPRA_INSTALL=BLOCKED_NOT_CODESPACES"
  exit 20
fi

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  ca-certificates \
  gnupg \
  wget \
  apt-transport-https \
  software-properties-common

wget -qO "$TMP_KEY" https://xpra.org/xpra.asc

ACTUAL_FPR="$(
  gpg --batch --show-keys --with-colons "$TMP_KEY" 2>/dev/null |
  awk -F: '$1=="fpr" {print $10; exit}'
)"

if [[ "$ACTUAL_FPR" != "$EXPECTED_FPR" ]]; then
  echo "XPRA_SIGNING_KEY=FAIL"
  echo "EXPECTED_FPR=$EXPECTED_FPR"
  echo "ACTUAL_FPR=$ACTUAL_FPR"
  exit 21
fi

sudo install -m 0644 "$TMP_KEY" /usr/share/keyrings/xpra.asc
sudo wget -qO /etc/apt/sources.list.d/xpra.sources "$XPRA_SOURCES_URL"

grep -q '^URIs: https://xpra.org$' /etc/apt/sources.list.d/xpra.sources
grep -q '^Suites: noble$' /etc/apt/sources.list.d/xpra.sources
grep -q '^Signed-By: /usr/share/keyrings/xpra.asc$' /etc/apt/sources.list.d/xpra.sources

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends xpra pulseaudio

command -v xpra >/dev/null
XPRA_VERSION="$(xpra --version 2>&1 | head -n1)"

echo "XPRA_INSTALL=PASS"
echo "XPRA_SIGNING_KEY=PASS"
echo "XPRA_SIGNING_FPR=$ACTUAL_FPR"
echo "XPRA_VERSION=$XPRA_VERSION"
echo "XPRA_CHANNEL=STABLE"
