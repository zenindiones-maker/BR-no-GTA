#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HOME}/.local/state/br-no-gta"
CONFIG_DIR="${HOME}/.config/br-no-gta"
BOOT_DIR="${HOME}/.termux/boot"
SUPERVISOR="${CONFIG_DIR}/telegram-supervisor.sh"
SUPERVISOR_PID="${STATE_DIR}/telegram-supervisor.pid"
SUPERVISOR_LOG="${STATE_DIR}/telegram-supervisor.log"
MAINTENANCE_FILE="${STATE_DIR}/telegram-gateway.maintenance"
BOOT_SCRIPT="${BOOT_DIR}/br-no-gta-telegram.sh"
CONTROL="${ROOT}/scripts/telegram_termux_control.sh"

mkdir -p "${STATE_DIR}" "${CONFIG_DIR}" "${BOOT_DIR}"
chmod 700 "${STATE_DIR}" "${CONFIG_DIR}" "${BOOT_DIR}" 2>/dev/null || true

if [[ ! -f "${CONTROL}" ]]; then
  echo "TELEGRAM_PERSISTENCE=FAIL missing ${CONTROL}" >&2
  exit 1
fi

shell_quote() {
  printf '%q' "$1"
}

ROOT_Q="$(shell_quote "${ROOT}")"
CONTROL_Q="$(shell_quote "${CONTROL}")"
STATE_DIR_Q="$(shell_quote "${STATE_DIR}")"
SUPERVISOR_PID_Q="$(shell_quote "${SUPERVISOR_PID}")"
SUPERVISOR_LOG_Q="$(shell_quote "${SUPERVISOR_LOG}")"
MAINTENANCE_FILE_Q="$(shell_quote "${MAINTENANCE_FILE}")"
SUPERVISOR_Q="$(shell_quote "${SUPERVISOR}")"

cat >"${SUPERVISOR}" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -u
ROOT=${ROOT_Q}
CONTROL=${CONTROL_Q}
STATE_DIR=${STATE_DIR_Q}
PID_FILE=${SUPERVISOR_PID_Q}
LOG_FILE=${SUPERVISOR_LOG_Q}
MAINTENANCE_FILE=${MAINTENANCE_FILE_Q}
mkdir -p "\${STATE_DIR}"
printf '%s\n' "\$\$" > "\${PID_FILE}"
trap 'rm -f "\${PID_FILE}"' EXIT INT TERM

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock >/dev/null 2>&1 || true
fi

while true; do
  if [[ -e "\${MAINTENANCE_FILE}" ]]; then
    sleep 1
    continue
  fi
  if ! bash "\${CONTROL}" status >/dev/null 2>&1; then
    printf '%s TELEGRAM_SUPERVISOR=RECONCILING_GATEWAY\n' "\$(date -Iseconds 2>/dev/null || date)" >>"\${LOG_FILE}"
    # Remote/local/runtime drift must be repaired by ff-only reconcile, not by adopting a stale local process.\n    bash "\${CONTROL}" reconcile >>"\${LOG_FILE}" 2>&1 || true
  fi
  sleep 30
done
EOF
chmod 700 "${SUPERVISOR}"

cat >"${BOOT_SCRIPT}" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -u
STATE_DIR=${STATE_DIR_Q}
PID_FILE=${SUPERVISOR_PID_Q}
LOG_FILE=${SUPERVISOR_LOG_Q}
SUPERVISOR=${SUPERVISOR_Q}
mkdir -p "\${STATE_DIR}"
sleep 15
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock >/dev/null 2>&1 || true
fi
if [[ -s "\${PID_FILE}" ]]; then
  pid="\$(cat "\${PID_FILE}" 2>/dev/null || true)"
  if [[ "\${pid}" =~ ^[0-9]+$ ]] && kill -0 "\${pid}" 2>/dev/null; then
    exit 0
  fi
fi
nohup bash "\${SUPERVISOR}" >>"\${LOG_FILE}" 2>&1 </dev/null &
EOF
chmod 700 "${BOOT_SCRIPT}"

supervisor_running=false
if [[ -s "${SUPERVISOR_PID}" ]]; then
  pid="$(cat "${SUPERVISOR_PID}" 2>/dev/null || true)"
  if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
    supervisor_running=true
  fi
fi

# Regenerate and restart the supervisor so changes to its control contract
# (including the maintenance lock) take effect immediately.
if [[ "${supervisor_running}" == true ]]; then
  kill "$(cat "${SUPERVISOR_PID}")" 2>/dev/null || true
  sleep 1
fi
rm -f "${SUPERVISOR_PID}"
nohup bash "${SUPERVISOR}" >>"${SUPERVISOR_LOG}" 2>&1 </dev/null &
sleep 1

if bash "${CONTROL}" status >/dev/null 2>&1; then
  gateway_state="RUNNING"
else
  # Installation/upgrade must converge runtime + local HEAD + remote HEAD.
  # start alone can legitimately adopt a process that matches an old local HEAD.
  bash "${CONTROL}" reconcile >>"${SUPERVISOR_LOG}" 2>&1 || true
  if bash "${CONTROL}" status >/dev/null 2>&1; then
    gateway_state="RUNNING"
  else
    gateway_state="NOT_RUNNING"
  fi
fi

boot_state="UNKNOWN"
if command -v cmd >/dev/null 2>&1; then
  if cmd package list packages 2>/dev/null | grep -qE '(^|:)com\.termux\.boot$'; then
    boot_state="DETECTED"
  else
    boot_state="NOT_DETECTED"
  fi
fi

printf 'TELEGRAM_PERSISTENCE=INSTALLED\n'
printf 'TELEGRAM_GATEWAY=%s\n' "${gateway_state}"
if [[ -s "${SUPERVISOR_PID}" ]]; then
  printf 'TELEGRAM_SUPERVISOR=RUNNING PID=%s\n' "$(cat "${SUPERVISOR_PID}")"
else
  printf 'TELEGRAM_SUPERVISOR=UNKNOWN\n'
fi
printf 'TERMUX_BOOT_APP=%s\n' "${boot_state}"
printf 'TERMUX_BOOT_SCRIPT=%s\n' "${BOOT_SCRIPT}"
printf 'TELEGRAM_SUPERVISOR_LOG=%s\n' "${SUPERVISOR_LOG}"
printf 'NOTE=Supervisor checks every 30s and reconciles ff-only to the remote branch before restarting stale Telegram runtime. Reboot autostart requires the Termux:Boot companion app to be installed and opened once.\n'
