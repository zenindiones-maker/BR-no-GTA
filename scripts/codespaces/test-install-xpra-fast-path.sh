#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="$SCRIPT_DIR/install-xpra-stable.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BIN="$TMP/bin"
mkdir -p "$BIN"

cat >"$BIN/dpkg-query" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
args="$*"
if [[ "$args" == *"${Status}"* ]]; then
  printf '%s' 'install ok installed'
elif [[ "$args" == *"${Version}"* ]]; then
  printf '%s' '6.5.4-test'
else
  exit 2
fi
SH

cat >"$BIN/xpra" <<'SH'
#!/usr/bin/env bash
echo "xpra v6.5.4-test"
SH

cat >"$BIN/gst-inspect-1.0" <<'SH'
#!/usr/bin/env bash
exit 0
SH

cat >"$BIN/pactl" <<'SH'
#!/usr/bin/env bash
exit 0
SH

cat >"$BIN/sudo" <<'SH'
#!/usr/bin/env bash
echo "TEST_FAILURE=UNEXPECTED_SUDO" >&2
exit 97
SH

cat >"$BIN/curl" <<'SH'
#!/usr/bin/env bash
echo "TEST_FAILURE=UNEXPECTED_NETWORK" >&2
exit 98
SH

chmod +x "$BIN"/*

OUTPUT="$(
  PATH="$BIN:/usr/bin:/bin"   CODESPACES=true   bash "$INSTALLER"
)"

grep -Fxq "XPRA_INSTALL=PASS_ALREADY_PRESENT" <<<"$OUTPUT"
grep -Fxq "XPRA_NETWORK_REFRESH=SKIPPED" <<<"$OUTPUT"
grep -Fxq "XPRA_AUDIO_CAPTURE_PLUGIN=PASS" <<<"$OUTPUT"
grep -Fxq "XPRA_AUDIO_CODEC_OPUS=PASS" <<<"$OUTPUT"

echo "XPRA_FAST_PATH_TEST=PASS"
