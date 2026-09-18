#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HOME}/.local/state/br-no-gta"
CONFIG_DIR="${HOME}/.config/br-no-gta"
SECRET_FILE="${CONFIG_DIR}/telegram.env"
PID_FILE="${STATE_DIR}/telegram-gateway.pid"
LOG_FILE="${STATE_DIR}/telegram-gateway.log"
MAINTENANCE_FILE="${STATE_DIR}/telegram-gateway.maintenance"
START_LOCK_DIR="${STATE_DIR}/telegram-gateway.start.lock"
PYTHON_BIN="${ROOT}/.venv/bin/python"

mkdir -p "${STATE_DIR}" "${CONFIG_DIR}"
chmod 700 "${STATE_DIR}" "${CONFIG_DIR}" 2>/dev/null || true

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python)"
fi

read_telegram_token_from_env_file() {
  local env_file="$1"
  [[ -r "${env_file}" ]] || return 0
  "${PYTHON_BIN}" - "${env_file}" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
pattern = re.compile(r"^\s*(?:export\s+)?TELEGRAM_BOT_TOKEN\s*=\s*(.*?)\s*$")
for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    match = pattern.match(raw_line)
    if not match:
        continue
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
        value = value[1:-1]
    if value:
        print(value, end="")
    break
PY
}

load_token() {
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    return 0
  fi

  if [[ -r "${SECRET_FILE}" ]]; then
    # This file is created by this script with shell-safe %q formatting.
    # shellcheck disable=SC1090
    source "${SECRET_FILE}"
  fi

  # Do not source the project's .env.local. It may contain unrelated or
  # malformed credentials. Read only the exact Telegram variable as data.
  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" && -r "${ROOT}/.env.local" ]]; then
    TELEGRAM_BOT_TOKEN="$(read_telegram_token_from_env_file "${ROOT}/.env.local")"
    export TELEGRAM_BOT_TOKEN
  fi

  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    printf 'Telegram token não está carregado nesta sessão. Cole uma única vez (não será exibido): ' >&2
    IFS= read -r -s TELEGRAM_BOT_TOKEN
    printf '\n' >&2
    export TELEGRAM_BOT_TOKEN
  fi

  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    echo "TELEGRAM_CONTROL=FAIL token vazio" >&2
    return 1
  fi

  if [[ ! -s "${SECRET_FILE}" ]]; then
    umask 077
    printf 'export TELEGRAM_BOT_TOKEN=%q\n' "${TELEGRAM_BOT_TOKEN}" > "${SECRET_FILE}"
    chmod 600 "${SECRET_FILE}"
  fi
}

configure_cloud_routing() {
  local current_branch
  current_branch="$(git -C "${ROOT}" branch --show-current 2>/dev/null || true)"
  if [[ -z "${BR_OMNIROUTE_REF:-}" && -n "${current_branch}" ]]; then
    export BR_OMNIROUTE_REF="${current_branch}"
  fi
  if [[ -z "${GITHUB_ACTIONS_RENDER_REF:-}" && -n "${current_branch}" ]]; then
    export GITHUB_ACTIONS_RENDER_REF="${current_branch}"
  fi
  export GITHUB_ACTIONS_REPOSITORY="${GITHUB_ACTIONS_REPOSITORY:-zenindiones-maker/BR-no-GTA}"

  if [[ -z "${BR_OMNIROUTE_REF:-}" ]]; then
    echo "TELEGRAM_CONTROL=FAIL não foi possível resolver BR_OMNIROUTE_REF" >&2
    return 1
  fi
}

gateway_pids() {
  "${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

TARGETS = (
    "scripts/telegram_harness_gateway_v2.py",
    "scripts/telegram_harness_gateway.py",
)

for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    pid = int(entry.name)
    if pid == os.getpid():
        continue
    try:
        raw = (entry / "cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    if any(any(arg.endswith(target) for target in TARGETS) for arg in argv):
        print(pid)
PY
}

current_gateway_pids() {
  "${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

TARGET = "scripts/telegram_harness_gateway_v2.py"
for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    pid = int(entry.name)
    if pid == os.getpid():
        continue
    try:
        raw = (entry / "cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    if any(arg.endswith(TARGET) for arg in argv):
        print(pid)
PY
}

pid_is_current_gateway() {
  local wanted="$1"
  local pid
  while IFS= read -r pid; do
    [[ "${pid}" == "${wanted}" ]] && return 0
  done < <(current_gateway_pids)
  return 1
}

acquire_start_lock() {
  local owner=""
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if mkdir "${START_LOCK_DIR}" 2>/dev/null; then
      printf '%s\n' "$$" > "${START_LOCK_DIR}/owner.pid"
      return 0
    fi
    owner="$(cat "${START_LOCK_DIR}/owner.pid" 2>/dev/null || true)"
    if [[ ! "${owner}" =~ ^[0-9]+$ ]] || ! kill -0 "${owner}" 2>/dev/null; then
      rm -rf "${START_LOCK_DIR}" 2>/dev/null || true
      continue
    fi
    sleep 1
  done
  return 1
}

release_start_lock() {
  rm -rf "${START_LOCK_DIR}" 2>/dev/null || true
}

terminate_gateway_pids() {
  local -a pids=("$@")
  local pid
  [[ ${#pids[@]} -gt 0 ]] || return 0

  for pid in "${pids[@]}"; do
    [[ "${pid}" =~ ^[0-9]+$ ]] || continue
    kill "${pid}" 2>/dev/null || true
  done

  for _ in 1 2 3 4 5; do
    local alive=0
    for pid in "${pids[@]}"; do
      if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
        alive=1
      fi
    done
    [[ "${alive}" -eq 0 ]] && break
    sleep 1
  done

  for pid in "${pids[@]}"; do
    if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
      kill -9 "${pid}" 2>/dev/null || true
    fi
  done
}

is_running() {
  [[ -s "${PID_FILE}" ]] || return 1
  local pid
  pid="$(cat "${PID_FILE}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  pid_is_current_gateway "${pid}"
}

start_gateway() {
  if is_running; then
    echo "TELEGRAM_GATEWAY=ALREADY_RUNNING PID=$(cat "${PID_FILE}")"
    return 0
  fi

  if ! acquire_start_lock; then
    if is_running; then
      echo "TELEGRAM_GATEWAY=ALREADY_RUNNING PID=$(cat "${PID_FILE}")"
      return 0
    fi
    echo "TELEGRAM_GATEWAY=FAIL could not acquire singleton start lock" >&2
    return 1
  fi

  if is_running; then
    echo "TELEGRAM_GATEWAY=ALREADY_RUNNING PID=$(cat "${PID_FILE}")"
    release_start_lock
    return 0
  fi

  local -a all_pids=()
  local -a current_pids=()
  mapfile -t all_pids < <(gateway_pids)
  mapfile -t current_pids < <(current_gateway_pids)

  if [[ ${#all_pids[@]} -eq 1 && ${#current_pids[@]} -eq 1 && "${all_pids[0]}" == "${current_pids[0]}" ]]; then
    printf '%s\n' "${current_pids[0]}" > "${PID_FILE}"
    echo "TELEGRAM_GATEWAY=ADOPTED_EXISTING PID=${current_pids[0]}"
    release_start_lock
    return 0
  fi

  if [[ ${#all_pids[@]} -gt 0 ]]; then
    echo "TELEGRAM_GATEWAY_SINGLETON=RECONCILING STALE_OR_DUPLICATE_COUNT=${#all_pids[@]}"
    terminate_gateway_pids "${all_pids[@]}"
    rm -f "${PID_FILE}"
  fi

  load_token
  configure_cloud_routing
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  export TELEGRAM_CONTROL_STATE_FILE="${STATE_DIR}/telegram-control.json"

  if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock >/dev/null 2>&1 || true
  fi

  cd "${ROOT}"
  nohup "${PYTHON_BIN}" -u scripts/telegram_harness_gateway_v2.py \
    >>"${LOG_FILE}" 2>&1 </dev/null &
  local pid=$!
  printf '%s\n' "${pid}" > "${PID_FILE}"
  sleep 2

  if kill -0 "${pid}" 2>/dev/null && pid_is_current_gateway "${pid}"; then
    echo "TELEGRAM_GATEWAY=STARTED PID=${pid}"
    echo "TELEGRAM_LOG=${LOG_FILE}"
    echo "BR_OMNIROUTE_REF=${BR_OMNIROUTE_REF}"
    release_start_lock
    tail -n 20 "${LOG_FILE}" || true
  else
    echo "TELEGRAM_GATEWAY=FAIL"
    tail -n 80 "${LOG_FILE}" || true
    rm -f "${PID_FILE}"
    release_start_lock
    return 1
  fi
}

stop_gateway() {
  local -a pids=()
  mapfile -t pids < <(gateway_pids)

  if [[ ${#pids[@]} -eq 0 ]]; then
    rm -f "${PID_FILE}"
    release_start_lock
    echo "TELEGRAM_GATEWAY=STOPPED"
    return 0
  fi

  terminate_gateway_pids "${pids[@]}"
  rm -f "${PID_FILE}"
  release_start_lock
  if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock >/dev/null 2>&1 || true
  fi
  echo "TELEGRAM_GATEWAY=STOPPED KILLED_INSTANCES=${#pids[@]}"
}

status_gateway() {
  if is_running; then
    local -a pids=()
    mapfile -t pids < <(gateway_pids)
    if [[ ${#pids[@]} -ne 1 ]]; then
      echo "TELEGRAM_GATEWAY=CONFLICT INSTANCES=${#pids[@]} TRACKED_PID=$(cat "${PID_FILE}")"
      return 2
    fi
    echo "TELEGRAM_GATEWAY=RUNNING PID=$(cat "${PID_FILE}") INSTANCES=1"
  else
    local -a pids=()
    mapfile -t pids < <(gateway_pids)
    if [[ ${#pids[@]} -gt 0 ]]; then
      echo "TELEGRAM_GATEWAY=UNTRACKED INSTANCES=${#pids[@]} PIDS=${pids[*]}"
      return 2
    fi
    echo "TELEGRAM_GATEWAY=NOT_RUNNING"
    return 1
  fi
}

foreground_gateway() {
  local -a pids=()
  mapfile -t pids < <(gateway_pids)
  if [[ ${#pids[@]} -gt 0 ]]; then
    echo "TELEGRAM_GATEWAY=FAIL foreground refused while another gateway instance exists: ${pids[*]}" >&2
    return 1
  fi
  load_token
  configure_cloud_routing
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  export TELEGRAM_CONTROL_STATE_FILE="${STATE_DIR}/telegram-control.json"
  cd "${ROOT}"
  exec "${PYTHON_BIN}" -u scripts/telegram_harness_gateway_v2.py
}

restart_gateway() {
  # Prevent the persistence supervisor from racing the intentional stop/start.
  : > "${MAINTENANCE_FILE}"
  trap 'rm -f "${MAINTENANCE_FILE}" "${START_LOCK_DIR}"' EXIT INT TERM
  stop_gateway
  start_gateway
  rm -f "${MAINTENANCE_FILE}"
  trap - EXIT INT TERM
}

case "${1:-start}" in
  start)
    start_gateway
    ;;
  stop)
    stop_gateway
    ;;
  restart)
    restart_gateway
    ;;
  status)
    status_gateway
    ;;
  logs)
    tail -n "${2:-80}" "${LOG_FILE}" 2>/dev/null || true
    ;;
  foreground)
    foreground_gateway
    ;;
  *)
    echo "uso: $0 {start|stop|restart|status|logs [N]|foreground}" >&2
    exit 2
    ;;
esac
