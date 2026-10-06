#!/usr/bin/env bash
set -euo pipefail

EXPECTED_FPR="B4993B57323148E37977E5D873254CAD17978FAF"
KEY_URL="https://xpra.org/xpra.asc"
KEYRING="/usr/share/keyrings/xpra.asc"
SOURCE_FILE="/etc/apt/sources.list.d/xpra.sources"
TMP_KEY="$(mktemp)"
trap 'rm -f "$TMP_KEY"' EXIT

if [[ "${CODESPACES:-}" != "true" ]]; then
  echo "XPRA_INSTALL=BLOCKED_NOT_CODESPACES"
  exit 20
fi

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends   ca-certificates   curl   gnupg

curl -fsSL "$KEY_URL" -o "$TMP_KEY"

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

XPRA_PACKAGES=(
  xpra
  xpra-x11
  xpra-html5
  xpra-audio-server
  pulseaudio
  xserver-xorg-video-dummy
)

sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends   "${XPRA_PACKAGES[@]}"

for pkg in "${XPRA_PACKAGES[@]}"; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed' || {
    echo "XPRA_PACKAGE_MISSING=$pkg"
    exit 22
  }
done

command -v xpra >/dev/null

XPRA_VERSION="$(xpra --version 2>&1 | head -n1)"
XPRA_X11_VERSION="$(dpkg-query -W -f='${Version}' xpra-x11)"
XPRA_HTML5_VERSION="$(dpkg-query -W -f='${Version}' xpra-html5)"
XPRA_AUDIO_VERSION="$(dpkg-query -W -f='${Version}' xpra-audio-server)"

sudo apt-get clean

echo "XPRA_INSTALL=PASS"
echo "XPRA_SIGNING_KEY=PASS"
echo "XPRA_SIGNING_FPR=$ACTUAL_FPR"
echo "XPRA_VERSION=$XPRA_VERSION"
echo "XPRA_X11_VERSION=$XPRA_X11_VERSION"
echo "XPRA_HTML5_VERSION=$XPRA_HTML5_VERSION"
echo "XPRA_AUDIO_SERVER_VERSION=$XPRA_AUDIO_VERSION"
echo "XPRA_CHANNEL=STABLE"
echo "XPRA_DESKTOP_BACKEND=PASS"
