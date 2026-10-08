#!/usr/bin/env bash
# REA is a subordinate, on-demand investigation tool; never the harness authority.
set -euo pipefail
REA_VERSION="6.0.0"
MODE="${1:---dry-run}"
if [[ "$MODE" != "--dry-run" && "$MODE" != "--install" ]]; then
  echo "USAGE: $0 [--dry-run|--install]" >&2
  exit 2
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "REA_PREFLIGHT=BLOCKED_NODE_OR_NPM_MISSING" >&2
  exit 2
fi
if ! node -e '
const v=process.versions.node.split(".").map(Number);
const valid=(v[0]===22&&v[1]>=19)||(v[0]===24&&v[1]>=11)||(v[0]>=26&&v[0]%2===0);
if(!valid)process.exit(1);
'; then
  echo "REA_PREFLIGHT=BLOCKED_UNSUPPORTED_NODE_VERSION" >&2
  exit 2
fi

PREFIX="${BR_REA_INSTALL_PREFIX:-$HOME/.local/share/br-no-gta/rea-$REA_VERSION}"
if [[ -L "$PREFIX" || "$PREFIX" == "/" || "$PREFIX" == "$HOME" ]]; then
  echo "REA_PREFLIGHT=BLOCKED_UNSAFE_INSTALL_PREFIX" >&2
  exit 2
fi
echo "REA_SOURCE=https://github.com/morluto/rea"
echo "REA_VERSION_PIN=$REA_VERSION"
echo "REA_INSTALL_PREFIX=$PREFIX"
echo "REA_AGENT_CONFIGURATION_MUTATION=FORBIDDEN"
echo "REA_BINARY_PROVIDER_INSTALL=FORBIDDEN"
if [[ "$MODE" == "--dry-run" ]]; then
  echo "REA_INSTALL_STATUS=DRY_RUN"
  exit 0
fi
mkdir -p "$PREFIX"
chmod 700 "$PREFIX"
npm install --prefix "$PREFIX" --no-audit --no-fund --no-save --ignore-scripts "rea-agents@$REA_VERSION"
BIN="$PREFIX/node_modules/.bin/rea"
if [[ ! -x "$BIN" ]]; then
  echo "REA_INSTALL_STATUS=FAIL_BINARY_NOT_FOUND" >&2
  exit 3
fi
"$BIN" --version
"$BIN" capabilities --json > "$PREFIX/rea-capabilities.json"
set +e
"$BIN" doctor --json > "$PREFIX/rea-doctor.json"
DOCTOR_EXIT=$?
set -e
echo "REA_PACKAGE_INSTALL=PASS"
echo "REA_CAPABILITIES_PATH=$PREFIX/rea-capabilities.json"
echo "REA_DOCTOR_EXIT=$DOCTOR_EXIT"
echo "REA_NATIVE_PROVIDER_STATUS=REVIEW_DOCTOR_JSON"
echo "REA_MCP_REGISTRATION=NOT_ATTEMPTED"
