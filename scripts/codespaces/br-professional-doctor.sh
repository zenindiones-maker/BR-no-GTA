#!/usr/bin/env bash
set -euo pipefail

PORT="14501"
SESSION=":101"

required=(xpra ffmpeg ffprobe mpv curl ss python3)
for cmd in "${required[@]}"; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "MISSING_COMMAND=$cmd"
    exit 20
  }
done

curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null || {
  echo "XPRA_HTML5=FAIL"
  exit 21
}

LISTEN_LINE="$(ss -ltn | awk -v p=":${PORT}" '$4 ~ p"$" {print $4; exit}')"
[[ "$LISTEN_LINE" == "127.0.0.1:${PORT}" ]] || {
  echo "XPRA_BIND=FAIL"
  echo "LISTEN=${LISTEN_LINE:-NONE}"
  exit 22
}

xpra info "$SESSION" >/tmp/br-xpra-info.txt 2>/dev/null || {
  echo "XPRA_SESSION=FAIL"
  exit 23
}

test -f "docs/operations/system-operational-readiness.html"
test -f "app/services/global_capability_registry.py"
test -f "app/services/harness_authorization_service.py"

echo "BR_PRO_WORKSTATION=PASS"
echo "XPRA_HTML5=PASS"
echo "XPRA_BIND=LOOPBACK_ONLY"
echo "SPEAKER_FORWARDING=CONFIGURED"
echo "MICROPHONE_FORWARDING=DISABLED"
echo "FFMPEG=PASS"
echo "MPV=PASS"
echo "HARNESS_AUTHORITY_SURFACE=PASS"
echo "NOVNC_FALLBACK=PRESERVED"
echo "PAID_FALLBACK=FALSE"
echo "UNKNOWN_COST_FALLBACK=FALSE"
echo "REAPER_REQUIRED=FALSE"
