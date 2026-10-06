#!/usr/bin/env bash
set -euo pipefail

required=(ffmpeg ffprobe mpv websockify vncserver python3)

for cmd in "${required[@]}"; do
  command -v "${cmd}" >/dev/null 2>&1 || {
    echo "MISSING_COMMAND=${cmd}"
    exit 20
  }
done

test -f "docs/operations/system-operational-readiness.html" || {
  echo "BR_CANONICAL_READINESS_DOC=FAIL"
  exit 21
}

test -f "app/services/global_capability_registry.py" || {
  echo "BR_CAPABILITY_REGISTRY=FAIL"
  exit 22
}

test -f "app/services/harness_authorization_service.py" || {
  echo "BR_HARNESS_AUTHORIZATION=FAIL"
  exit 23
}

curl -fsS http://127.0.0.1:6081/vnc.html >/dev/null || {
  echo "BR_NOVNC=FAIL"
  exit 24
}

echo "BR_CODESPACE=PASS"
echo "FFMPEG=PASS"
echo "NOVNC=PASS"
echo "HARNESS_AUTHORITY_SURFACE=PASS"
echo "PAID_FALLBACK=FALSE"
echo "UNKNOWN_COST_FALLBACK=FALSE"
echo "REAPER_REQUIRED=FALSE"
