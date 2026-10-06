#!/usr/bin/env bash
set -euo pipefail

SESSION=":101"
PORT="14501"
SCRATCH="/tmp/br-media-scratch"
CACHE="/tmp/br-media-cache"

if [[ "${CODESPACES:-}" != "true" ]]; then
  echo "BR_PRO=BLOCKED_NOT_CODESPACES"
  exit 20
fi

command -v xpra >/dev/null || {
  echo "BR_PRO=BLOCKED_XPRA_MISSING"
  exit 21
}

mkdir -p "$SCRATCH" "$CACHE"

if ! xpra list 2>/dev/null | grep -Eq "LIVE.*${SESSION}|\${SESSION}.*LIVE"; then
  xpra start-desktop "$SESSION" \
    --bind-tcp="127.0.0.1:${PORT},auth=none" \
    --html=on \
    --pulseaudio=yes \
    --speaker=on \
    --microphone=disabled \
    --webcam=no \
    --file-transfer=off \
    --open-files=off \
    --mdns=no \
    --sharing=no \
    --start-new-commands=no \
    --resize-display=1600x900 \
    --session-name="BR-no-GTA Professional" \
    --env="TMPDIR=${SCRATCH}" \
    --env="XDG_CACHE_HOME=${CACHE}" \
    --start-child="xfce4-session" \
    --exit-with-children=no \
    --daemon=yes
fi

for _ in $(seq 1 40); do
  curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null 2>&1 && break
  sleep 1
done

curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null

LISTEN_LINE="$(ss -ltn 2>/dev/null | awk -v p=":${PORT}" '$4 ~ p"$" {print $4; exit}')"
case "$LISTEN_LINE" in
  127.0.0.1:${PORT}) ;;
  *)
    echo "XPRA_BIND=FAIL"
    echo "LISTEN=${LISTEN_LINE:-NONE}"
    exit 22
    ;;
esac

echo "BR_PRO_DESKTOP=PASS"
echo "REMOTE_TRANSPORT=XPRA_HTML5"
echo "XPRA_PORT=$PORT"
echo "XPRA_BIND=LOOPBACK_ONLY"
echo "SPEAKER_FORWARDING=ENABLED"
echo "MICROPHONE_FORWARDING=DISABLED"
echo "NOVNC_FALLBACK_PORT=6081"
echo "SCRATCH_ROOT=$SCRATCH"
echo "REAPER_REQUIRED=FALSE"
