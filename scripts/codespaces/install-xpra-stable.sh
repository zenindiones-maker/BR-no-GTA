#!/usr/bin/env bash
set -euo pipefail

EXPECTED_FPR="B4993B57323148E37977E5D873254CAD17978FAF"
KEY_URL="https://xpra.org/xpra.asc"
KEYRING="/usr/share/keyrings/xpra.asc"
SOURCE_FILE="/etc/apt/sources.list.d/xpra.sources"

XPRA_PACKAGES=(
  xpra
  xpra-x11
  xpra-html5
  xpra-audio-server
  pulseaudio
  pulseaudio-utils
  xserver-xorg-video-dummy
  gstreamer1.0-tools
  gstreamer1.0-plugins-base
  gstreamer1.0-plugins-good
  gstreamer1.0-pulseaudio
)

if [[ "${CODESPACES:-}" != "true" ]]; then
  echo "XPRA_INSTALL=BLOCKED_NOT_CODESPACES"
  exit 20
fi

xpra_runtime_ready() {
  local pkg cmd

  for pkg in "${XPRA_PACKAGES[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null |
      grep -q 'install ok installed' || return 1
  done

  for cmd in xpra gst-inspect-1.0 pactl; do
    command -v "$cmd" >/dev/null 2>&1 || return 1
  done

  gst-inspect-1.0 pulsesrc >/dev/null 2>&1 || return 1
  gst-inspect-1.0 opusenc >/dev/null 2>&1 || return 1
}

emit_runtime_receipt() {
  local xpra_version x11_version html5_version audio_version

  xpra_version="$(xpra --version 2>&1 | sed -n '1p')"
  x11_version="$(dpkg-query -W -f='${Version}' xpra-x11)"
  html5_version="$(dpkg-query -W -f='${Version}' xpra-html5)"
  audio_version="$(dpkg-query -W -f='${Version}' xpra-audio-server)"

  echo "XPRA_VERSION=$xpra_version"
  echo "XPRA_X11_VERSION=$x11_version"
  echo "XPRA_HTML5_VERSION=$html5_version"
  echo "XPRA_AUDIO_SERVER_VERSION=$audio_version"
  echo "XPRA_AUDIO_CAPTURE_PLUGIN=PASS"
  echo "XPRA_AUDIO_CODEC_OPUS=PASS"
  echo "XPRA_CHANNEL=STABLE"
  echo "XPRA_DESKTOP_BACKEND=PASS"
}

if xpra_runtime_ready; then
  echo "XPRA_INSTALL=PASS_ALREADY_PRESENT"
  echo "XPRA_NETWORK_REFRESH=SKIPPED"
  echo "XPRA_AUTO_UPGRADE=FALSE"
  emit_runtime_receipt
  exit 0
fi

echo "XPRA_INSTALL=REPAIR_OR_INITIAL_INSTALL"
echo "XPRA_NETWORK_REFRESH=REQUIRED"

TMP_KEY="$(mktemp)"
trap 'rm -f "$TMP_KEY"' EXIT

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends   apt-transport-https   ca-certificates   curl   gnupg   software-properties-common

curl   --proto '=https'   --tlsv1.2   --fail   --location   "$KEY_URL"   --output "$TMP_KEY"

ACTUAL_FPR="$(
  gpg --batch --show-keys --with-colons "$TMP_KEY" 2>/dev/null |
    awk -F: '$1=="fpr" && !found {print $10; found=1}'
)"

if [[ "$ACTUAL_FPR" != "$EXPECTED_FPR" ]]; then
  echo "XPRA_SIGNING_KEY=FAIL"
  echo "EXPECTED_FPR=$EXPECTED_FPR"
  echo "ACTUAL_FPR=$ACTUAL_FPR"
  exit 21
fi

sudo install -m 0644 "$TMP_KEY" "$KEYRING"

cat <<'SOURCES' | sudo tee "$SOURCE_FILE" >/dev/null
Types: deb
URIs: https://xpra.org
Suites: noble
Components: main
Signed-By: /usr/share/keyrings/xpra.asc
SOURCES

grep -q '^URIs: https://xpra.org$' "$SOURCE_FILE"
grep -q '^Suites: noble$' "$SOURCE_FILE"
grep -q '^Signed-By: /usr/share/keyrings/xpra.asc$' "$SOURCE_FILE"

sudo apt-get update

sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends   "${XPRA_PACKAGES[@]}"

xpra_runtime_ready || {
  echo "XPRA_INSTALL=FAIL_RUNTIME_INCOMPLETE"
  exit 22
}

sudo apt-get clean

echo "XPRA_INSTALL=PASS"
echo "XPRA_SIGNING_KEY=PASS"
echo "XPRA_SIGNING_FPR=$ACTUAL_FPR"
echo "XPRA_AUTO_UPGRADE=FALSE_AFTER_INSTALL"
emit_runtime_receipt
