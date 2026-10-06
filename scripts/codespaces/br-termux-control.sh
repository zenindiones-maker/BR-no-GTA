#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

REPO="zenindiones-maker/BR-no-GTA"
BRANCH="work/zero-cost-codespaces-v1"
DISPLAY_NAME="br-no-gta-zero-cost"
MACHINE="basicLinux32gb"
PORT="6081"

die() {
  echo "$1" >&2
  exit "${2:-20}"
}

require_tools() {
  command -v gh >/dev/null 2>&1 || die "GH_CLI=MISSING"
  command -v jq >/dev/null 2>&1 || die "JQ=MISSING"
  gh auth status -h github.com >/dev/null 2>&1 || die "GITHUB_AUTH=BLOCKED"
}

resolve_cs() {
  gh codespace list \
    -R "$REPO" \
    --json name,displayName,lastUsedAt \
  | jq -r --arg d "$DISPLAY_NAME" '
      [.[] | select(.displayName==$d)]
      | sort_by(.lastUsedAt)
      | reverse
      | .[0].name // empty
    '
}

state_of() {
  gh codespace view -c "$1" --json state --jq '.state'
}

verify_identity() {
  local cs="$1" json ref machine
  json="$(gh codespace view -c "$cs" --json gitStatus,machineName)"
  ref="$(printf '%s' "$json" | jq -r '.gitStatus.ref')"
  machine="$(printf '%s' "$json" | jq -r '.machineName')"

  [ "$ref" = "$BRANCH" ] || {
    echo "BR_CODESPACE=BLOCKED_WRONG_BRANCH"
    echo "EXPECTED=$BRANCH"
    echo "ACTUAL=$ref"
    exit 21
  }

  [ "$machine" = "$MACHINE" ] || {
    echo "BR_CODESPACE=BLOCKED_WRONG_MACHINE"
    echo "EXPECTED=$MACHINE"
    echo "ACTUAL=$machine"
    exit 22
  }
}

start_cs() {
  local cs="$1" state
  state="$(state_of "$cs")"

  if [ "$state" != "Available" ]; then
    echo "BR_CODESPACE_STARTING=$cs"

    if ! gh api --method POST "/user/codespaces/$cs/start" >/dev/null; then
      die "BR_CODESPACE_START=BLOCKED" 23
    fi

    for _ in $(seq 1 120); do
      state="$(state_of "$cs")"
      echo "STATE=$state"
      [ "$state" = "Available" ] && break
      sleep 5
    done
  fi

  [ "$state" = "Available" ] || die "BR_CODESPACE=BLOCKED_STATE_$state" 24
}

ensure_private_port() {
  local cs="$1" ports url vis

  url=""
  vis=""

  for _ in $(seq 1 60); do
    ports="$(gh codespace ports -c "$cs" --json sourcePort,browseUrl,visibility 2>/dev/null || echo '[]')"
    url="$(printf '%s' "$ports" | jq -r --argjson p "$PORT" '.[] | select(.sourcePort==$p) | .browseUrl // empty' | head -n1)"
    vis="$(printf '%s' "$ports" | jq -r --argjson p "$PORT" '.[] | select(.sourcePort==$p) | .visibility // empty' | head -n1)"
    [ -n "$url" ] && break
    sleep 2
  done

  [ -n "$url" ] || die "PORT_6081=BLOCKED_NOT_FORWARDED" 25

  if [ "$vis" != "private" ]; then
    gh codespace ports visibility "$PORT:private" -c "$cs" >/dev/null
    vis="$(gh codespace ports -c "$cs" --json sourcePort,visibility --jq ".[] | select(.sourcePort==$PORT) | .visibility")"
  fi

  [ "$vis" = "private" ] || die "PORT_6081_VISIBILITY=BLOCKED_NOT_PRIVATE" 26
  printf '%s\n' "$url"
}

cmd_status() {
  local cs state
  cs="$(resolve_cs)"

  if [ -z "$cs" ]; then
    echo "BR_CODESPACE=NOT_CREATED"
    return 0
  fi

  verify_identity "$cs"

  gh codespace view -c "$cs" \
    --json name,displayName,state,machineName,machineDisplayName,gitStatus,idleTimeoutMinutes,retentionExpiresAt

  state="$(state_of "$cs")"
  if [ "$state" = "Available" ]; then
    echo
    gh codespace ports -c "$cs" --json sourcePort,label,visibility,browseUrl || true
  fi
}

cmd_open() {
  local cs url
  cs="$(resolve_cs)"
  [ -n "$cs" ] || die "BR_CODESPACE=NOT_CREATED; RUN=brcreate" 27

  verify_identity "$cs"
  start_cs "$cs"

  echo "BR_CODESPACE=AVAILABLE"
  echo "CODESPACE=$cs"

  gh codespace ssh -c "$cs" -- \
    'cd /workspaces/BR-no-GTA && bash scripts/codespaces/br-start-desktop.sh'

  url="$(ensure_private_port "$cs")"

  echo "PORT_6081=PASS"
  echo "PORT_6081_VISIBILITY=PRIVATE"
  echo "BR_WORKSTATION_READY=PASS"
  echo "PAID_FALLBACK=FALSE"
  echo "REAPER_REQUIRED=FALSE"

  if command -v termux-open-url >/dev/null 2>&1; then
    termux-open-url "$url"
  else
    echo "DESKTOP_URL=$url"
  fi
}

cmd_doctor() {
  local cs state
  cs="$(resolve_cs)"
  [ -n "$cs" ] || die "BR_CODESPACE=NOT_CREATED" 27

  verify_identity "$cs"
  state="$(state_of "$cs")"

  if [ "$state" != "Available" ]; then
    echo "BR_CODESPACE_STATE=$state"
    echo "DOCTOR=WAIT_CODESPACE_STOPPED"
    return 0
  fi

  gh codespace ssh -c "$cs" -- \
    'cd /workspaces/BR-no-GTA &&
     echo "BRANCH=$(git branch --show-current)" &&
     echo "HEAD=$(git rev-parse HEAD)" &&
     bash scripts/codespaces/br-doctor.sh'

  echo
  gh codespace ports -c "$cs" --json sourcePort,label,visibility,browseUrl
}

cmd_close() {
  local cs state
  cs="$(resolve_cs)"

  if [ -z "$cs" ]; then
    echo "BR_CODESPACE=NOT_CREATED"
    return 0
  fi

  verify_identity "$cs"
  state="$(state_of "$cs")"

  if [ "$state" = "Available" ]; then
    gh codespace stop -c "$cs"
  fi

  echo "BR_CODESPACE_STOP=PASS"
  echo "CODESPACE=$cs"
  echo "CODESPACE_DELETED=FALSE"
}

cmd_create() {
  local cs machine_json cpus

  cs="$(resolve_cs)"
  if [ -n "$cs" ]; then
    echo "BR_CODESPACE_ALREADY_EXISTS=$cs"
    return 0
  fi

  machine_json="$(gh api --method GET "repos/$REPO/codespaces/machines" -f ref="$BRANCH")"
  cpus="$(printf '%s' "$machine_json" | jq -r --arg m "$MACHINE" '.machines[] | select(.name==$m) | .cpus')"

  [ "$cpus" = "2" ] || die "BR_CREATE=BLOCKED_MACHINE_NOT_2_CORE" 28

  echo "MACHINE_SIZE=PASS_2_CORE"
  echo "PAID_FALLBACK=FALSE"

  gh codespace create \
    -R "$REPO" \
    -b "$BRANCH" \
    --devcontainer-path ".devcontainer/devcontainer.json" \
    -m "$MACHINE" \
    -d "$DISPLAY_NAME" \
    --idle-timeout 30m \
    --retention-period 24h \
    --status
}

require_tools

case "${1:-status}" in
  open) cmd_open ;;
  status) cmd_status ;;
  doctor) cmd_doctor ;;
  close|stop) cmd_close ;;
  create) cmd_create ;;
  *)
    echo "usage: brctl {open|status|doctor|close|create}"
    exit 2
    ;;
esac
