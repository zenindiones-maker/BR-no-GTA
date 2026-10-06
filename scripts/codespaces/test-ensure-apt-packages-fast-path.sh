#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HELPER="$SCRIPT_DIR/ensure-apt-packages.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BIN="$TMP/bin"
mkdir -p "$BIN"

cat >"$BIN/dpkg-query" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s' 'install ok installed'
SH

cat >"$BIN/sudo" <<'SH'
#!/usr/bin/env bash
echo "TEST_FAILURE=UNEXPECTED_SUDO" >&2
exit 97
SH

chmod +x "$BIN"/*

OUTPUT="$(
  PATH="$BIN:/usr/bin:/bin" \
  bash "$HELPER" alpha-package beta-package
)"

grep -Fxq "APT_PACKAGES=PASS_ALREADY_PRESENT" <<<"$OUTPUT"
grep -Fxq "APT_NETWORK_REFRESH=SKIPPED" <<<"$OUTPUT"
grep -Fxq "APT_PACKAGE_COUNT=2" <<<"$OUTPUT"

echo "APT_PACKAGE_FAST_PATH_TEST=PASS"
