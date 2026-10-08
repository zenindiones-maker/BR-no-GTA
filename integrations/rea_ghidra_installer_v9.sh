#!/usr/bin/env bash
# Reproducible official Ghidra 12.1.4 installation. No agent setup/MCP mutation.
set -euo pipefail
umask 077
ARCHIVE_NAME="ghidra_12.1.4_PUBLIC_20260921.zip"
DOWNLOAD="https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/$ARCHIVE_NAME"
EXPECTED_SHA="ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db"
PREFIX="${BR_GHIDRA_PRIVATE_PREFIX:?Set newly allocated private prefix}"
[[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]] || { echo "GHIDRA_HOST_NOT_SUPPORTED"; exit 2; }
[[ "$PREFIX" = /* && ! -e "$PREFIX" && ! -L "$PREFIX" ]] || { echo "GHIDRA_PREFIX_UNSAFE"; exit 2; }
command -v curl >/dev/null && command -v unzip >/dev/null && command -v sha256sum >/dev/null
test -x "${JAVA_HOME:?JDK21_JAVA_HOME_REQUIRED}/bin/java"
test -x "$JAVA_HOME/bin/javac"
"$JAVA_HOME/bin/java" -version 2>&1 | grep -E 'version "21|version "2[2-9]' >/dev/null || {
  echo "GHIDRA_JDK_TOO_OLD_OR_MISSING"; exit 2;
}
"$JAVA_HOME/bin/javac" -version 2>&1 | grep -E 'javac (21|2[2-9])' >/dev/null || {
  echo "GHIDRA_JDK_COMPILER_MISSING"; exit 2;
}
mkdir -m 700 "$PREFIX"
trap 'rm -rf "$PREFIX"' ERR
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
  --retry 2 --retry-delay 2 --max-time 480 "$DOWNLOAD" -o "$PREFIX/$ARCHIVE_NAME"
echo "$EXPECTED_SHA  $PREFIX/$ARCHIVE_NAME" | sha256sum -c --status
python3 - "$PREFIX/$ARCHIVE_NAME" <<'PY'
import sys, zipfile
from pathlib import PurePosixPath
file=sys.argv[1]
with zipfile.ZipFile(file) as z:
    for member in z.infolist():
        p=PurePosixPath(member.filename)
        if (p.is_absolute() or ".." in p.parts or not p.parts
            or p.parts[0] != "ghidra_12.1.4_PUBLIC"):
            raise SystemExit("GHIDRA_ARCHIVE_MEMBER_SCOPE_INVALID")
print("BR_NATIVE_GHIDRA_ZIP_SCOPE=PASS")
PY
unzip -q "$PREFIX/$ARCHIVE_NAME" -d "$PREFIX"
rm -f "$PREFIX/$ARCHIVE_NAME"
GHIDRA="$PREFIX/ghidra_12.1.4_PUBLIC"
test -f "$GHIDRA/support/analyzeHeadless"
test -f "$GHIDRA/ghidraRun"
echo "BR_NATIVE_GHIDRA_RELEASE_SHA256=VERIFIED"
echo "BR_NATIVE_GHIDRA_PATH=$GHIDRA"
echo "BR_NATIVE_MCP_CONFIG_CHANGED=FALSE"
trap - ERR
