#!/usr/bin/env bash
# Exact upstream prebuilt artifact. Never curl | sh, never "latest".
set -euo pipefail
VERSION="v0.4.1"
EXPECTED_SHA="aa6073ba255c0bcf09364a5503cbd4794791b832e5934a52b169a455d66101c7"
ARCHIVE="iris-x86_64-unknown-linux-musl.tar.gz"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "IRIS_UNSUPPORTED_ARCH_OR_HOST" >&2
  exit 2
fi
PREFIX="${BR_IRIS_INSTALL_PREFIX:?Set private, newly allocated install directory}"
[[ "$PREFIX" = /* ]] || { echo "IRIS_INSTALL_PREFIX_NOT_ABSOLUTE" >&2; exit 2; }
[[ ! -e "$PREFIX" ]] || { echo "IRIS_INSTALL_PREFIX_ALREADY_EXISTS" >&2; exit 2; }
umask 077
mkdir -m 700 "$PREFIX"
trap 'rm -rf "$PREFIX"' ERR
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
  --retry 2 --max-time 75 \
  "https://github.com/brijr/iris/releases/download/${VERSION}/${ARCHIVE}" \
  --output "$PREFIX/$ARCHIVE"
echo "$EXPECTED_SHA  $PREFIX/$ARCHIVE" | sha256sum --check --status
test "$(tar -tzf "$PREFIX/$ARCHIVE" | wc -l)" -eq 1
test "$(tar -tzf "$PREFIX/$ARCHIVE")" = "iris"
tar -xzf "$PREFIX/$ARCHIVE" -C "$PREFIX" --no-same-owner --no-same-permissions
chmod 700 "$PREFIX/iris"
rm "$PREFIX/$ARCHIVE"
test "$("$PREFIX/iris" --version)" = "iris 0.4.1"
echo "BR_IRIS_BINARY_SHA256=$(sha256sum "$PREFIX/iris" | cut -d' ' -f1)"
echo "BR_IRIS_PINNED_INSTALL=PASS"
trap - ERR
