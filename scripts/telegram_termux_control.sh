#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HOME}/.local/state/br-no-gta"
CONFIG_DIR="${HOME}/.config/br-no-gta"
SECRET_FILE="${CONFIG_DIR}/telegram.env"
PID_FILE="${STATE_DIR}/telegram-gateway.pid"
LOG_FILE="${STATE_DIR}/telegram-gateway.log"
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

is_running() {
  [[ -s "${PID_FILE}" ]] || return 1
  local pid
  pid="$(cat "${PID_FILE}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null
}

start_gateway() {
  if is_running; then
    echo "TELEGRAM_GATEWAY=ALREADY_RUNNING PID=$(cat "${PID_FILE}")"
    return 0
  fi

  load_token
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  export TELEGRAM_CONTROL_STATE_FILE="${STATE_DIR}/telegram-control.json"

  if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock >/dev/null 2>&1 || true
  fi

  cd "${ROOT}"
  nohup "${PYTHON_BIN}" -u scripts/telegram_harness_gateway.py \
    >>"${LOG_FILE}" 2>&1 </dev/null &
  local pid=$!
  printf '%s\n' "${pid}" > "${PID_FILE}"
  sleep 2

  if kill -0 "${pid}" 2>/dev/null; then
    echo "TELEGRAM_GATEWAY=STARTED PID=${pid}"
    echo "TELEGRAM_LOG=${LOG_FILE}"
    tail -n 20 "${LOG_FILE}" || true
  else
    echo "TELEGRAM_GATEWAY=FAIL"
    tail -n 80 "${LOG_FILE}" || true
    rm -f "${PID_FILE}"
    return 1
  fi
}

stop_gateway() {
  if ! is_running; then
    rm -f "${PID_FILE}"
    echo "TELEGRAM_GATEWAY=STOPPED"
    return 0
  fi
  local pid
  pid="$(cat "${PID_FILE}")"
  kill "${pid}" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if kill -0 "${pid}" 2>/dev/null; then
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -f "${PID_FILE}"
  if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock >/dev/null 2>&1 || true
  fi
  echo "TELEGRAM_GATEWAY=STOPPED"
}

status_gateway() {
  if is_running; then
    echo "TELEGRAM_GATEWAY=RUNNING PID=$(cat "${PID_FILE}")"
  else
    echo "TELEGRAM_GATEWAY=NOT_RUNNING"
    return 1
  fi
}

foreground_gateway() {
  load_token
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  export TELEGRAM_CONTROL_STATE_FILE="${STATE_DIR}/telegram-control.json"
  cd "${ROOT}"
  exec "${PYTHON_BIN}" -u scripts/telegram_harness_gateway.py
}

case "${1:-start}" in
  start)
    start_gateway
    ;;
  stop)
    stop_gateway
    ;;
  restart)
    stop_gateway
    start_gateway
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
