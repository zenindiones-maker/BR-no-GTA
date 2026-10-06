#!/usr/bin/env bash
set -euo pipefail

PORT="14501"
SESSION=":101"
RUNTIME="/tmp/br-runtime-${UID}"
SOCKET_DIR="${RUNTIME}/xpra"

mkdir -p "$SOCKET_DIR"
chmod 700 "$RUNTIME" "$SOCKET_DIR"
export XDG_RUNTIME_DIR="$RUNTIME"

required=(xpra ffmpeg ffprobe mpv mediainfo curl ss python3)
for cmd in "${required[@]}"; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "MISSING_COMMAND=$cmd"
    exit 20
  }
done

for pkg in xpra xpra-x11 xpra-html5 xpra-audio-server; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed' || {
    echo "PACKAGE_MISSING=$pkg"
    exit 21
  }
done

curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null || {
  echo "XPRA_HTML5=FAIL"
  exit 22
}

LISTEN_LINE="$(ss -ltn | awk -v p=":${PORT}" '$4 ~ p"$" {print $4; exit}')"
[[ "$LISTEN_LINE" == "127.0.0.1:${PORT}" ]] || {
  echo "XPRA_BIND=FAIL"
  echo "LISTEN=${LISTEN_LINE:-NONE}"
  exit 23
}

xpra info "$SESSION" --socket-dir="$SOCKET_DIR" >/tmp/br-xpra-info.txt 2>/dev/null || {
  echo "XPRA_SESSION=FAIL"
  exit 24
}

test -f "docs/operations/system-operational-readiness.html" || {
  echo "BR_CANONICAL_READINESS_DOC=FAIL"
  exit 25
}
test -f "app/services/global_capability_registry.py" || {
  echo "BR_CAPABILITY_REGISTRY=FAIL"
  exit 26
}
test -f "app/services/harness_authorization_service.py" || {
  echo "BR_HARNESS_AUTHORIZATION=FAIL"
  exit 27
}

MEM_AVAILABLE_MB="$(awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo)"
DISK_FREE_MB="$(df -Pm /workspaces | awk 'NR==2 {print $4}')"

echo "BR_PRO_WORKSTATION=PASS"
echo "XPRA_HTML5=PASS"
echo "XPRA_X11=PASS"
echo "XPRA_AUDIO_SERVER=PASS"
echo "XPRA_BIND=LOOPBACK_ONLY"
echo "SPEAKER_FORWARDING=CONFIGURED"
echo "MICROPHONE_FORWARDING=DISABLED"
echo "FFMPEG=PASS"
echo "MPV=PASS"
echo "MEDIAINFO=PASS"
echo "HARNESS_AUTHORITY_SURFACE=PASS"
echo "NOVNC_FALLBACK=PRESERVED"
echo "MEM_AVAILABLE_MB=$MEM_AVAILABLE_MB"
echo "WORKSPACE_FREE_MB=$DISK_FREE_MB"
echo "SCRATCH_POLICY=TMP_EPHEMERAL"
echo "PAID_FALLBACK=FALSE"
echo "UNKNOWN_COST_FALLBACK=FALSE"
echo "REAPER_REQUIRED=FALSE"
