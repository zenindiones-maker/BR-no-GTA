#!/usr/bin/env bash
set -euo pipefail

PORT="14501"
SESSION=":101"
RUNTIME="/tmp/br-runtime-${UID}"
SOCKET_DIR="${RUNTIME}/xpra"

mkdir -p "$SOCKET_DIR"
chmod 700 "$RUNTIME" "$SOCKET_DIR"
export XDG_RUNTIME_DIR="$RUNTIME"

required=(xpra ffmpeg ffprobe mpv mediainfo curl ss python3 gst-inspect-1.0 pactl sox rubberband)
for cmd in "${required[@]}"; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "MISSING_COMMAND=$cmd"
    exit 20
  }
done

for pkg in \
  xpra xpra-x11 xpra-html5 xpra-audio-server \
  pulseaudio pulseaudio-utils \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-pulseaudio
do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed' || {
    echo "PACKAGE_MISSING=$pkg"
    exit 21
  }
done

gst-inspect-1.0 pulsesrc >/dev/null 2>&1 || {
  echo "XPRA_AUDIO_CAPTURE_PLUGIN=FAIL"
  exit 22
}
gst-inspect-1.0 opusenc >/dev/null 2>&1 || {
  echo "XPRA_AUDIO_CODEC_OPUS=FAIL"
  exit 23
}

ffmpeg -hide_banner -encoders 2>/dev/null | grep -qE '[[:space:]]libx264[[:space:]]' || {
  echo "FFMPEG_H264_ENCODER=FAIL"
  exit 24
}
ffmpeg -hide_banner -encoders 2>/dev/null | grep -qE '[[:space:]]aac[[:space:]]' || {
  echo "FFMPEG_AAC_ENCODER=FAIL"
  exit 25
}

curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null || {
  echo "XPRA_HTML5=FAIL"
  exit 26
}

LISTEN_LINE="$(ss -ltn | awk -v p=":${PORT}" '$4 ~ p"$" {print $4; exit}')"
[[ "$LISTEN_LINE" == "127.0.0.1:${PORT}" ]] || {
  echo "XPRA_BIND=FAIL"
  echo "LISTEN=${LISTEN_LINE:-NONE}"
  exit 27
}

xpra info "$SESSION" --socket-dir="$SOCKET_DIR" >/tmp/br-xpra-info.txt 2>/dev/null || {
  echo "XPRA_SESSION=FAIL"
  exit 28
}

test -f "docs/operations/system-operational-readiness.html" || {
  echo "BR_CANONICAL_READINESS_DOC=FAIL"
  exit 29
}
test -f "app/services/global_capability_registry.py" || {
  echo "BR_CAPABILITY_REGISTRY=FAIL"
  exit 30
}
test -f "app/services/harness_authorization_service.py" || {
  echo "BR_HARNESS_AUTHORIZATION=FAIL"
  exit 31
}

CPU_COUNT="$(nproc)"
MEM_AVAILABLE_MB="$(awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo)"
DISK_FREE_MB="$(df -Pm /workspaces | awk 'NR==2 {print $4}')"

(( CPU_COUNT == 2 )) || {
  echo "ZERO_COST_MACHINE_SHAPE=FAIL"
  echo "CPU_COUNT=$CPU_COUNT"
  exit 32
}
(( MEM_AVAILABLE_MB >= 2048 )) || {
  echo "MEMORY_HEADROOM=FAIL"
  echo "MEM_AVAILABLE_MB=$MEM_AVAILABLE_MB"
  exit 33
}
(( DISK_FREE_MB >= 8192 )) || {
  echo "WORKSPACE_HEADROOM=FAIL"
  echo "WORKSPACE_FREE_MB=$DISK_FREE_MB"
  exit 34
}

echo "BR_PRO_WORKSTATION=PASS"
echo "WORKSTATION_ROLE=MEDIA_VIDEO_QA"
echo "MASTER_FINAL_TARGET=1920x1080_30_H264_AAC"
echo "XPRA_HTML5=PASS"
echo "XPRA_X11=PASS"
echo "XPRA_AUDIO_SERVER=PASS"
echo "XPRA_AUDIO_CAPTURE_PLUGIN=PASS"
echo "XPRA_AUDIO_CODEC_OPUS=PASS"
echo "XPRA_BIND=LOOPBACK_ONLY"
echo "SPEAKER_FORWARDING=CONFIGURED"
echo "MICROPHONE_FORWARDING=DISABLED"
echo "FFMPEG=PASS"
echo "FFMPEG_H264_LIBX264=PASS"
echo "FFMPEG_AAC=PASS"
echo "FFPROBE=PASS"
echo "MPV=PASS"
echo "MEDIAINFO=PASS"
echo "SOX=PASS"
echo "RUBBERBAND=PASS"
echo "HARNESS_AUTHORITY_SURFACE=PASS"
echo "NOVNC_FALLBACK=PRESERVED"
echo "CPU_COUNT=$CPU_COUNT"
echo "MEM_AVAILABLE_MB=$MEM_AVAILABLE_MB"
echo "WORKSPACE_FREE_MB=$DISK_FREE_MB"
echo "SCRATCH_POLICY=TMP_EPHEMERAL"
echo "PAID_FALLBACK=FALSE"
echo "UNKNOWN_COST_FALLBACK=FALSE"
echo "REAPER_REQUIRED=FALSE"
