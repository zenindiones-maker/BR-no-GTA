#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

REPO="zenindiones-maker/BR-no-GTA"
BRANCH="work/zero-cost-workstation-v3"
DISPLAY_NAME="br-no-gta-zero-cost"
MACHINE="basicLinux32gb"
PRIMARY_PORT="14501"
FALLBACK_PORT="6081"

die() {
  echo "$1" >&2
  exit "${2:-20}"
}

require_tools() {
  command -v gh >/dev/null 2>&1 || die "GH_CLI=MISSING"
  command -v jq >/dev/null 2>&1 || die "JQ=MISSING"
  gh auth status -h github.com >/dev/null 2>&1 || die "GITHUB_AUTH=BLOCKED"
}

matching_json() {
  gh codespace list -R "$REPO" --json name,displayName,state,lastUsedAt
}

guard_singleton() {
  local json count
  json="$(matching_json)"
  count="$(printf '%s' "$json" | jq -r --arg d "$DISPLAY_NAME" '[.[]|select(.displayName==$d)]|length')"
  [ "$count" -le 1 ] || {
    printf '%s
' "$json" | jq --arg d "$DISPLAY_NAME" '[.[]|select(.displayName==$d)]'
    die "BR_CODESPACE=BLOCKED_DUPLICATE_WORKSTATIONS" 30
  }
}

resolve_cs() {
  matching_json | jq -r --arg d "$DISPLAY_NAME" '
    [.[] | select(.displayName==$d)]
    | sort_by(.lastUsedAt)
    | reverse
    | .[0].name // empty
  '
}

state_of() {
  gh codespace view -c "$1" --json state --jq '.state'
}

verify_machine_only() {
  local cs="$1" machine
  machine="$(gh codespace view -c "$cs" --json machineName --jq '.machineName')"
  [ "$machine" = "$MACHINE" ] || {
    echo "BR_CODESPACE=BLOCKED_WRONG_MACHINE"
    echo "EXPECTED=$MACHINE"
    echo "ACTUAL=$machine"
    exit 22
  }
}

verify_identity() {
  local cs="$1" ref
  verify_machine_only "$cs"
  ref="$(gh codespace view -c "$cs" --json gitStatus --jq '.gitStatus.ref')"
  [ "$ref" = "$BRANCH" ] || {
    echo "BR_CODESPACE=BLOCKED_WRONG_BRANCH"
    echo "EXPECTED=$BRANCH"
    echo "ACTUAL=$ref"
    exit 21
  }
}

start_cs() {
  local cs="$1" state
  state="$(state_of "$cs")"

  if [ "$state" != "Available" ]; then
    echo "BR=STARTING"
    gh api --method POST "/user/codespaces/$cs/start" >/dev/null || die "BR_START=BLOCKED" 23
    for _ in $(seq 1 120); do
      state="$(state_of "$cs")"
      echo "STATE=$state"
      [ "$state" = "Available" ] && break
      sleep 5
    done
  fi

  [ "$state" = "Available" ] || die "BR=BLOCKED_STATE_$state" 24
}

port_record() {
  local cs="$1" port="$2"
  gh codespace ports -c "$cs" --json sourcePort,browseUrl,visibility,label 2>/dev/null |
    jq -c --argjson p "$port" 'first(.[]|select(.sourcePort==$p)) // empty'
}

ensure_private_url() {
  local cs="$1" port="$2" record url vis
  for _ in $(seq 1 45); do
    record="$(port_record "$cs" "$port" || true)"
    [ -n "$record" ] && break
    sleep 2
  done

  [ -n "$record" ] || return 1

  url="$(printf '%s' "$record" | jq -r '.browseUrl // empty')"
  vis="$(printf '%s' "$record" | jq -r '.visibility // empty')"

  if [ "$vis" != "private" ]; then
    gh codespace ports visibility "$port:private" -c "$cs" >/dev/null
    record="$(port_record "$cs" "$port")"
    vis="$(printf '%s' "$record" | jq -r '.visibility')"
  fi

  [ "$vis" = "private" ] || die "PORT_${port}_VISIBILITY=BLOCKED_NOT_PRIVATE" 25
  [ -n "$url" ] || return 1
  printf '%s
' "$url"
}

cmd_status() {
  local cs
  guard_singleton
  cs="$(resolve_cs)"

  if [ -z "$cs" ]; then
    echo "BR_CODESPACE=NOT_CREATED"
    return 0
  fi

  verify_identity "$cs"

  gh codespace view -c "$cs"     --json name,displayName,state,machineName,machineDisplayName,gitStatus,idleTimeoutMinutes,retentionExpiresAt

  if [ "$(state_of "$cs")" = "Available" ]; then
    echo
    gh codespace ports -c "$cs" --json sourcePort,label,visibility,browseUrl || true
  fi
}

cmd_open() {
  local cs url transport
  guard_singleton
  cs="$(resolve_cs)"
  [ -n "$cs" ] || die "BR_CODESPACE=NOT_CREATED; RUN=brcreate" 27

  verify_identity "$cs"
  start_cs "$cs"

  echo "BR_CODESPACE=AVAILABLE"
  echo "CODESPACE=$cs"

  transport="XPRA_HTML5"
  gh codespace ssh -c "$cs" -- 'cd /workspaces/BR-no-GTA && bash scripts/codespaces/br-start-professional-desktop.sh' ||
    die "BR_XPRA=BLOCKED_START_FAILED" 28

  url="$(ensure_private_url "$cs" "$PRIMARY_PORT" || true)"
  [ -n "$url" ] || die "BR_XPRA=BLOCKED_NO_PRIVATE_PORT" 29

  echo "REMOTE_TRANSPORT=$transport"
  echo "DESKTOP_VISIBILITY=PRIVATE"
  echo "BR_WORKSTATION_READY=PASS"
  echo "XPRA_REQUIRED=TRUE"
  echo "WORKSTATION_ROLE=MEDIA_VIDEO_QA"
  echo "MASTER_FINAL_TARGET=1920x1080_30_H264_AAC"
  echo "ZERO_COST_MODE=INCLUDED_USAGE_ONLY"
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
  guard_singleton
  cs="$(resolve_cs)"
  [ -n "$cs" ] || die "BR_CODESPACE=NOT_CREATED" 27

  verify_identity "$cs"
  state="$(state_of "$cs")"

  if [ "$state" != "Available" ]; then
    echo "BR_CODESPACE_STATE=$state"
    echo "DOCTOR=WAIT_CODESPACE_STOPPED"
    return 0
  fi

  gh codespace ssh -c "$cs" -- bash -lc '
    set -euo pipefail
    cd /workspaces/BR-no-GTA
    echo "BRANCH=$(git branch --show-current)"
    echo "HEAD=$(git rev-parse HEAD)"
    if [ -f scripts/codespaces/br-professional-doctor.sh ]; then
      bash scripts/codespaces/br-professional-doctor.sh
    else
      bash scripts/codespaces/br-doctor.sh
    fi
  '

  echo
  gh codespace ports -c "$cs" --json sourcePort,label,visibility,browseUrl
}

cmd_sync() {
  local cs
  guard_singleton
  cs="$(resolve_cs)"
  [ -n "$cs" ] || die "BR_CODESPACE=NOT_CREATED" 27

  verify_machine_only "$cs"
  start_cs "$cs"

  gh codespace ssh -c "$cs" -- bash -lc '
    set -euo pipefail
    cd /workspaces/BR-no-GTA

    if [ -n "$(git status --porcelain)" ]; then
      echo "WORKTREE=BLOCKED_DIRTY_PRESERVE_WIP"
      git status --short --branch
      exit 41
    fi

    git fetch origin work/zero-cost-workstation-v3

    if git show-ref --verify --quiet refs/heads/work/zero-cost-workstation-v3; then
      git switch work/zero-cost-workstation-v3
    else
      git switch --track -c work/zero-cost-workstation-v3 origin/work/zero-cost-workstation-v3
    fi

    git pull --ff-only origin work/zero-cost-workstation-v3

    HEAD_NOW="$(git rev-parse HEAD)"
    REMOTE_NOW="$(git rev-parse origin/work/zero-cost-workstation-v3)"
    [ "$HEAD_NOW" = "$REMOTE_NOW" ] || {
      echo "SYNC=BLOCKED_NOT_EXACT_REMOTE"
      exit 42
    }

    echo "SYNC=PASS"
    echo "BRANCH=$(git branch --show-current)"
    echo "HEAD=$HEAD_NOW"

    bash scripts/codespaces/br-upgrade-professional-v2.sh
  '

  verify_identity "$cs"
  echo "BR_V3_SYNC=PASS"
  echo "XPRA_REQUIRED=TRUE"
  echo "PAID_FALLBACK=FALSE"
}

cmd_proof() {
  local cs
  cmd_sync
  guard_singleton
  cs="$(resolve_cs)"
  [ -n "$cs" ] || die "BR_CODESPACE=NOT_CREATED" 27
  verify_identity "$cs"

  gh codespace ssh -c "$cs" -- bash -lc '
    set -euo pipefail
    cd /workspaces/BR-no-GTA
    bash scripts/codespaces/br-runtime-proof.sh
  '

  ensure_private_url "$cs" "$PRIMARY_PORT" >/dev/null ||
    die "BR_PROOF=BLOCKED_PRIVATE_PORT_UNPROVEN" 43

  echo "BR_RUNTIME_PROOF=PASS_AUTOMATED_BOUNDARY"
  echo "XPRA_REQUIRED=TRUE"
  echo "PORT_VISIBILITY=PRIVATE"
  echo "PAID_FALLBACK=FALSE"
  echo "UNKNOWN_COST_FALLBACK=FALSE"
}

cmd_close() {
  local cs state
  guard_singleton
  cs="$(resolve_cs)"

  if [ -z "$cs" ]; then
    echo "BR_CODESPACE=NOT_CREATED"
    return 0
  fi

  verify_machine_only "$cs"
  state="$(state_of "$cs")"

  if [ "$state" = "Available" ]; then
    gh codespace stop -c "$cs"
  fi

  echo "BR_CODESPACE_STOP=PASS"
  echo "CODESPACE=$cs"
  echo "CODESPACE_DELETED=FALSE"
}

cmd_create() {
  local cs machine_json cpus private
  guard_singleton
  cs="$(resolve_cs)"

  if [ -n "$cs" ]; then
    verify_machine_only "$cs"
    echo "BR_CODESPACE_ALREADY_EXISTS=$cs"
    echo "EXISTING_CODESPACE_REUSE=TRUE"
    echo "RUN_NEXT=brctl sync"
    return 0
  fi

  private="$(gh api "repos/$REPO" --jq '.private')"
  [ "$private" = "false" ] || die "BR_CREATE=BLOCKED_REPOSITORY_NOT_PUBLIC" 28

  machine_json="$(gh api --method GET "repos/$REPO/codespaces/machines" -f ref="$BRANCH")"
  cpus="$(printf '%s' "$machine_json" | jq -r --arg m "$MACHINE" '.machines[]|select(.name==$m)|.cpus')"
  [ "$cpus" = "2" ] || die "BR_CREATE=BLOCKED_MACHINE_NOT_2_CORE" 29

  echo "MACHINE_SIZE=PASS_2_CORE"
  echo "WORKSTATION_ROLE=MEDIA_VIDEO_QA"
  echo "ZERO_COST_MODE=INCLUDED_USAGE_ONLY"
  echo "REPOSITORY_VISIBILITY=PUBLIC"
  echo "PAID_FALLBACK=FALSE"

  gh codespace create     -R "$REPO"     -b "$BRANCH"     --devcontainer-path ".devcontainer/devcontainer.json"     -m "$MACHINE"     -d "$DISPLAY_NAME"     --idle-timeout 20m     --retention-period 24h     --status
}

require_tools

case "${1:-status}" in
  open) cmd_open ;;
  status) cmd_status ;;
  sync) cmd_sync ;;
  proof) cmd_proof ;;
  doctor) cmd_doctor ;;
  close|stop) cmd_close ;;
  create) cmd_create ;;
  *) echo "usage: brctl {open|status|sync|proof|doctor|close|create}"; exit 2 ;;
esac
