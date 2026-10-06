#!/usr/bin/env bash
set -euo pipefail

STATE_ROOT="${HOME}/.local/state/br-no-gta-codespace"
MARKER="${STATE_ROOT}/bootstrap-v2"

mkdir -p "$STATE_ROOT"

if [[ "${CODESPACES:-}" != "true" ]]; then
  echo "BR_CODESPACE=BLOCKED_NOT_CODESPACES"
  exit 20
fi

if [[ ! -f "$MARKER" ]]; then
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends     ffmpeg     mpv     jq     curl     ca-certificates     python3-venv     xfce4     xfce4-terminal     tigervnc-standalone-server     novnc     websockify     dbus-x11

  mkdir -p "$HOME/.vnc"

  cat > "$HOME/.vnc/xstartup-br" <<'XSTART'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec dbus-launch --exit-with-session startxfce4
XSTART

  chmod 700 "$HOME/.vnc/xstartup-br"
  touch "$MARKER"
  sudo apt-get clean
fi

echo "BR_CODESPACE_BOOTSTRAP=PASS"
echo "BOOTSTRAP_VERSION=2"
echo "FFMPEG=$(command -v ffmpeg)"
echo "PAID_FALLBACK=FALSE"
echo "UNKNOWN_COST_FALLBACK=FALSE"
echo "REAPER_REQUIRED=FALSE"
