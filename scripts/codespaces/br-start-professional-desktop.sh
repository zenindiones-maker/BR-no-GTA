#!/usr/bin/env bash
set -euo pipefail

SESSION=":101"
PORT="14501"
STATE_ROOT="${HOME}/.local/state/br-no-gta-codespace"
SCRATCH="/tmp/br-media-scratch"
CACHE="/tmp/br-media-cache"
RUNTIME="/tmp/br-runtime-${UID}"
SOCKET_DIR="${RUNTIME}/xpra"
LOG_FILE="${STATE_ROOT}/xpra-professional.log"

if [[ "${CODESPACES:-}" != "true" ]]; then
  echo "BR_PRO=BLOCKED_NOT_CODESPACES"
  exit 20
fi

for cmd in xpra curl ss xfce4-session ffmpeg ffprobe mpv mediainfo; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "BR_PRO=BLOCKED_MISSING_$cmd"
    exit 21
  }
done

for pkg in xpra-x11 xpra-html5 xpra-audio-server; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed' || {
    echo "BR_PRO=BLOCKED_PACKAGE_$pkg"
    exit 22
  }
done

mkdir -p "$STATE_ROOT" "$SCRATCH" "$CACHE" "$SOCKET_DIR"
chmod 700 "$RUNTIME" "$SOCKET_DIR"
export XDG_RUNTIME_DIR="$RUNTIME"

session_live() {
  xpra list --socket-dir="$SOCKET_DIR" 2>/dev/null |
    grep -Eq "LIVE.*${SESSION}|${SESSION}.*LIVE"
}

http_live() {
  curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null 2>&1
}

if session_live && ! http_live; then
  echo "XPRA_SESSION=STALE_RECOVERY"
  xpra stop "$SESSION" --socket-dir="$SOCKET_DIR" >/dev/null 2>&1 || true
  sleep 2
fi

if ! session_live; then
  xpra start-desktop "$SESSION" \
    --socket-dir="$SOCKET_DIR" \
    --bind-tcp="127.0.0.1:${PORT},auth=none" \
    --html=on \
    --pulseaudio=yes \
    --speaker=on \
    --microphone=disabled \
    --webcam=no \
    --file-transfer=off \
    --open-files=off \
    --printing=no \
    --mdns=no \
    --sharing=no \
    --start-new-commands=no \
    --systemd-run=no \
    --resize-display=1920x1080 \
    --dpi=96 \
    --session-name="BR-no-GTA Media / Video QA" \
    --env="TMPDIR=${SCRATCH}" \
    --env="XDG_CACHE_HOME=${CACHE}" \
    --start="xfce4-session" \
    --exit-with-children=no \
    --log-file="$LOG_FILE" \
    --daemon=yes
fi

for _ in $(seq 1 60); do
  http_live && break
  sleep 1
done

if ! http_live; then
  echo "XPRA_HTML5=FAIL"
  tail -n 80 "$LOG_FILE" 2>/dev/null || true
  exit 23
fi

LISTEN_LINE="$(ss -ltn 2>/dev/null | awk -v p=":${PORT}" '$4 ~ p"$" {print $4; exit}')"
[[ "$LISTEN_LINE" == "127.0.0.1:${PORT}" ]] || {
  echo "XPRA_BIND=FAIL"
  echo "LISTEN=${LISTEN_LINE:-NONE}"
  exit 24
}

echo "BR_PRO_DESKTOP=PASS"
echo "WORKSTATION_ROLE=MEDIA_VIDEO_QA"
echo "MASTER_FINAL_TARGET=1920x1080_30_H264_AAC"
echo "REMOTE_TRANSPORT=XPRA_HTML5"
echo "XPRA_PORT=$PORT"
echo "XPRA_BIND=LOOPBACK_ONLY"
echo "DESKTOP_TARGET=1920x1080"
echo "SPEAKER_FORWARDING=CONFIGURED"
echo "MICROPHONE_FORWARDING=DISABLED"
echo "FILE_TRANSFER=DISABLED"
echo "PRINTING=DISABLED"
echo "NOVNC_FALLBACK_PORT=6081"
echo "SCRATCH_ROOT=$SCRATCH"
echo "CACHE_ROOT=$CACHE"
echo "REAPER_REQUIRED=FALSE"
echo "AUTOFORWARD_HINT=http://localhost:${PORT}/"
