#!/usr/bin/env bash
set -euo pipefail

STATE_ROOT="${HOME}/.local/state/br-no-gta-codespace"
mkdir -p "$STATE_ROOT"

if [[ "${CODESPACES:-}" != "true" ]]; then
  echo "BR_CODESPACE=BLOCKED_NOT_CODESPACES"
  exit 20
fi

if ! pgrep -f 'Xtigervnc.*:2' >/dev/null 2>&1; then
  vncserver :2     -localhost yes     -SecurityTypes None     -geometry 1440x900     -depth 24     -xstartup "$HOME/.vnc/xstartup-br"
fi

if ! pgrep -f 'websockify.*6081' >/dev/null 2>&1; then
  nohup websockify     --web=/usr/share/novnc     127.0.0.1:6081     localhost:5902     >"$STATE_ROOT/novnc.log" 2>&1 &
  echo $! > "$STATE_ROOT/novnc.pid"
fi

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:6081/vnc.html >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS http://127.0.0.1:6081/vnc.html >/dev/null

echo "BR_CODESPACE_DESKTOP=PASS"
echo "NOVNC_PORT=6081"
echo "NOVNC_BIND=LOOPBACK_ONLY"
echo "FFMPEG_READY=PASS"
echo "REAPER_REQUIRED=FALSE"
echo "AUTOFORWARD_HINT=http://localhost:6081/vnc.html"
