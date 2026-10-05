#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HOME}/.local/state/br-no-gta"
CONFIG_DIR="${HOME}/.config/br-no-gta"
SECRET_FILE="${CONFIG_DIR}/telegram.env"
PID_FILE="${STATE_DIR}/telegram-gateway.pid"
LOG_FILE="${STATE_DIR}/telegram-gateway.log"
REVISION_FILE="${STATE_DIR}/telegram-gateway.revision"
READY_FILE="${STATE_DIR}/telegram-gateway.ready"
MAINTENANCE_FILE="${STATE_DIR}/telegram-gateway.maintenance"
START_LOCK_DIR="${STATE_DIR}/telegram-gateway.start.lock"
SUPERVISOR_PID_FILE="${STATE_DIR}/telegram-supervisor.pid"
CANONICAL_BRANCH="${BR_CANONICAL_BRANCH:-work/gate6f-analytics-learning}"
RUNTIME_RELEASE_SHA="${BR_TELEGRAM_RUNTIME_RELEASE_SHA:-$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || true)}"
DEPLOY_ENV_BASE="${HOME}/.local/share/br-no-gta/deploy/envs"
RUNTIME_ENV_ROOT="${BR_TELEGRAM_RUNTIME_ENV_ROOT:-${DEPLOY_ENV_BASE}/${RUNTIME_RELEASE_SHA}}"
PYTHON_BIN="${RUNTIME_ENV_ROOT}/bin/python"

mkdir -p "${STATE_DIR}" "${CONFIG_DIR}"
chmod 700 "${STATE_DIR}" "${CONFIG_DIR}" 2>/dev/null || true

ensure_gateway_python_runtime() {
  if [[ -x "${PYTHON_BIN}" ]]; then
    return 0
  fi
  local bootstrap_python
  bootstrap_python="$(command -v python 2>/dev/null || true)"
  if [[ -z "${bootstrap_python}" ]]; then
    echo "TELEGRAM_RUNTIME_PYTHON=FAIL no bootstrap python available" >&2
    return 1
  fi
  echo "TELEGRAM_RUNTIME_PYTHON=RECONCILING VENV=${RUNTIME_ENV_ROOT}"
  mkdir -p "${DEPLOY_ENV_BASE}"
  "${bootstrap_python}" -m venv "${RUNTIME_ENV_ROOT}"
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "TELEGRAM_RUNTIME_PYTHON=FAIL venv python unavailable after reconciliation" >&2
    return 1
  fi
}

A15_RUNTIME_DEPENDENCY_PROFILE="a15-telegram-v1"
A15_REQUIREMENTS_FILE="${ROOT}/requirements/a15-telegram.txt"

runtime_dependency_probe() {
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  "${PYTHON_BIN}" - <<'PY' >/dev/null || return $?
import sqlite3
import tempfile
from pathlib import Path

import dotenv  # noqa: F401
import apscheduler  # noqa: F401

from app.services.telegram_obsidian_attachment_bridge_service import (
    _safe_html_text_fallback,
)
import scripts.telegram_harness_gateway_v2  # noqa: F401

connection = sqlite3.connect(":memory:")
connection.execute("CREATE TABLE readiness_probe(value INTEGER NOT NULL)")
connection.execute("INSERT INTO readiness_probe(value) VALUES (1)")
value = connection.execute("SELECT value FROM readiness_probe").fetchone()[0]
connection.close()
if value != 1:
    raise SystemExit("sqlite readiness probe failed")

with tempfile.TemporaryDirectory() as temporary:
    path = Path(temporary) / "probe.html"
    path.write_text(
        "<html><body><h1>A15_RUNTIME_PROBE</h1></body></html>",
        encoding="utf-8",
    )
    if "A15_RUNTIME_PROBE" not in _safe_html_text_fallback(path):
        raise SystemExit("stdlib html normalizer readiness probe failed")
PY
  return 0
}

runtime_dependency_readiness() {
  ensure_gateway_python_runtime || return $?
  if ! runtime_dependency_probe; then
    echo "TELEGRAM_RUNTIME_DEPENDENCIES=RECONCILING PROFILE=${A15_RUNTIME_DEPENDENCY_PROFILE}"
    "${PYTHON_BIN}" -m pip install -r "${A15_REQUIREMENTS_FILE}" || return $?
    runtime_dependency_probe || return $?
  fi

  echo "GATEWAY_PYTHON=$(readlink -f "${PYTHON_BIN}" 2>/dev/null || printf '%s' "${PYTHON_BIN}")"
  echo "PYTHON_BIN=$(readlink -f "${PYTHON_BIN}" 2>/dev/null || printf '%s' "${PYTHON_BIN}")"
  echo "A15_RUNTIME_DEPENDENCY_PROFILE=${A15_RUNTIME_DEPENDENCY_PROFILE}"
  echo "A15_REQUIRED_DEPENDENCIES=PASS"
  echo "A15_LOCAL_TEXT_NORMALIZER=PASS"
  "${PYTHON_BIN}" - <<'PY'
from importlib.metadata import PackageNotFoundError, version
try:
    import markitdown  # noqa: F401
except Exception:
    print("MARKITDOWN_AVAILABLE=NO")
else:
    try:
        installed = version("markitdown")
    except PackageNotFoundError:
        installed = "unknown"
    print("MARKITDOWN_AVAILABLE=YES")
    print(f"MARKITDOWN_VERSION={installed}")
print("RICH_DOCUMENT_NORMALIZATION_ROUTE=CLOUD_REQUIRED")
PY
  echo "A15_PROFILE_CHECK=PASS"
}

candidate_runtime_preflight() {
  runtime_dependency_readiness || return $?
  load_token || return $?
  configure_cloud_routing || return $?
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  cd "${ROOT}"
  "${PYTHON_BIN}" - <<'PY' || return $?
from app.main import initialize_application
import scripts.telegram_harness_gateway_v2  # noqa: F401

initialize_application()
print("TELEGRAM_CANDIDATE_IMPORTS=PASS")
print("TELEGRAM_CANDIDATE_DB_SCHEMA=PASS")
PY
  echo "TELEGRAM_CANDIDATE_PREFLIGHT=PASS"
}

ensure_gateway_python_runtime

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
  if [[ -z "${BR_OMNIROUTE_REF:-}" ]]; then
    export BR_OMNIROUTE_REF="${CANONICAL_BRANCH}"
  fi
  if [[ -z "${GITHUB_ACTIONS_RENDER_REF:-}" ]]; then
    export GITHUB_ACTIONS_RENDER_REF="${CANONICAL_BRANCH}"
  fi
  export GITHUB_ACTIONS_REPOSITORY="${GITHUB_ACTIONS_REPOSITORY:-zenindiones-maker/BR-no-GTA}"
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
MODULES = {
    "scripts.telegram_harness_gateway_v2",
    "scripts.telegram_harness_gateway",
}

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
    file_style = any(any(arg.endswith(target) for target in TARGETS) for arg in argv)
    module_style = any(arg in MODULES for arg in argv)
    if file_style or module_style:
        print(pid)
PY
}

current_gateway_pids() {
  "${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

TARGET = "scripts/telegram_harness_gateway_v2.py"
MODULE = "scripts.telegram_harness_gateway_v2"
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
    if any(arg.endswith(TARGET) for arg in argv) or MODULE in argv:
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

current_repo_revision() {
  local head
  head="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || true)"
  [[ -n "${head}" ]] || return 1
  if ! git -C "${ROOT}" diff --quiet --ignore-submodules -- 2>/dev/null; then
    printf '%s-dirty\n' "${head}"
    return 0
  fi
  printf '%s\n' "${head}"
}

current_branch() {
  git -C "${ROOT}" branch --show-current 2>/dev/null || true
}

remote_repo_revision() {
  local branch remote
  branch="${CANONICAL_BRANCH}"
  remote="$(git -C "${ROOT}" ls-remote --heads origin "refs/heads/${branch}" 2>/dev/null | awk 'NR==1 {print $1}')"
  [[ -n "${remote}" ]] || return 1
  printf '%s\n' "${remote}"
}

loaded_runtime_revision() {
  [[ -s "${REVISION_FILE}" ]] || return 1
  local runtime_pid runtime_revision
  read -r runtime_pid runtime_revision < "${REVISION_FILE}" || return 1
  [[ -n "${runtime_revision}" ]] || return 1
  printf '%s\n' "${runtime_revision}"
}

reconcile_gateway() {
  echo "TELEGRAM_DEPLOY=FAIL immutable release control cannot self-update; use telegram_a15_immutable_deploy.sh" >&2
  return 2
}

runtime_revision_report() {
  local local_head remote_head loaded pid
  local -a pids=()
  local_head="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || true)"
  remote_head="$(remote_repo_revision 2>/dev/null || true)"
  loaded="$(loaded_runtime_revision 2>/dev/null || true)"
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  mapfile -t pids < <(gateway_pids)
  echo "RUNNING_GATEWAY_PID=${pid:-NONE}"
  echo "RUNNING_GATEWAY_INSTANCES=${#pids[@]}"
  echo "RUNNING_GATEWAY_PIDS=${pids[*]:-NONE}"
  echo "RUNNING_GATEWAY_REVISION=${loaded:-MISSING}"
  echo "LOCAL_HEAD=${local_head:-UNKNOWN}"
  echo "REMOTE_HEAD=${remote_head:-UNAVAILABLE}"
  if [[ "${#pids[@]}" -eq 1 && -n "${local_head}" && -n "${remote_head}" && -n "${loaded}" && "${local_head}" == "${remote_head}" && "${loaded}" == "${local_head}" ]] && runtime_ready_matches; then
    echo "TELEGRAM_RUNTIME_REVISION_MATCHES_HEAD=PASS"
    echo "TELEGRAM_GATEWAY_SINGLETON=PASS"
    echo "TELEGRAM_GATEWAY_READY=PASS"
    return 0
  fi
  echo "TELEGRAM_RUNTIME_REVISION_MATCHES_HEAD=FAIL"
  echo "TELEGRAM_GATEWAY_SINGLETON=FAIL"
  echo "TELEGRAM_GATEWAY_READY=FAIL"
  return 2
}

runtime_revision_matches() {
  [[ -s "${REVISION_FILE}" ]] || return 1
  [[ -s "${PID_FILE}" ]] || return 1
  local expected runtime_pid runtime_revision tracked_pid

  # The revision proof is a commit identity, not a working-tree cleanliness
  # probe.  A live gateway may legitimately materialize runtime state after
  # launch; using current_repo_revision() here can therefore turn the expected
  # value into "<sha>-dirty" after the child has already written the immutable
  # launch SHA.  Prefer the launch-pinned revision and fall back to HEAD when
  # adopting an already-running gateway from a fresh control shell.
  expected="${BR_TELEGRAM_GATEWAY_REVISION:-}"
  if [[ -z "${expected}" ]]; then
    expected="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || true)"
  fi
  [[ -n "${expected}" ]] || return 1

  tracked_pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  read -r runtime_pid runtime_revision < "${REVISION_FILE}" || return 1
  [[ "${tracked_pid}" =~ ^[0-9]+$ ]] || return 1
  [[ "${runtime_pid}" == "${tracked_pid}" ]] || return 1
  [[ "${runtime_revision}" == "${expected}" ]]
}

runtime_ready_matches() {
  [[ -s "${READY_FILE}" ]] || return 1
  [[ -s "${PID_FILE}" ]] || return 1
  local expected ready_pid ready_revision tracked_pid
  expected="${BR_TELEGRAM_GATEWAY_REVISION:-}"
  if [[ -z "${expected}" ]]; then
    expected="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || true)"
  fi
  [[ -n "${expected}" ]] || return 1

  tracked_pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  read -r ready_pid ready_revision < "${READY_FILE}" || return 1
  [[ "${tracked_pid}" =~ ^[0-9]+$ ]] || return 1
  [[ "${ready_pid}" == "${tracked_pid}" ]] || return 1
  [[ "${ready_revision}" == "${expected}" ]]
}

runtime_identity_attest() {
  local expected="${BR_TELEGRAM_RUNTIME_RELEASE_SHA:-${BR_TELEGRAM_GATEWAY_REVISION:-}}"
  local expected_tree="${BR_TELEGRAM_EXPECTED_TREE_SHA:-}"
  local local_head local_tree tracked_pid
  local -a pids=()

  [[ "${expected}" =~ ^[0-9a-f]{40}$ ]] || {
    echo "TELEGRAM_RUNTIME_EXACT_ATTESTATION=FAIL invalid expected revision" >&2
    return 2
  }
  local_head="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || true)"
  [[ "${local_head}" == "${expected}" ]] || {
    echo "TELEGRAM_RUNTIME_EXACT_ATTESTATION=FAIL local revision mismatch" >&2
    return 2
  }
  if [[ -n "${expected_tree}" ]]; then
    [[ "${expected_tree}" =~ ^[0-9a-f]{40}$ ]] || return 2
    local_tree="$(git -C "${ROOT}" rev-parse HEAD^{tree} 2>/dev/null || true)"
    [[ "${local_tree}" == "${expected_tree}" ]] || {
      echo "TELEGRAM_RUNTIME_EXACT_ATTESTATION=FAIL tree mismatch" >&2
      return 2
    }
  fi

  mapfile -t pids < <(gateway_pids)
  [[ "${#pids[@]}" -eq 1 ]] || return 2
  tracked_pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  [[ "${tracked_pid}" =~ ^[0-9]+$ ]] || return 2
  [[ "${pids[0]}" == "${tracked_pid}" ]] || return 2
  kill -0 "${tracked_pid}" 2>/dev/null || return 2

  local BR_TELEGRAM_GATEWAY_REVISION="${expected}"
  runtime_revision_matches || return 2
  runtime_ready_matches || return 2
  echo "TELEGRAM_RUNTIME_EXACT_ATTESTATION=PASS"
}

wait_for_runtime_ready() {
  local pid="$1"
  local wait_seconds="${TELEGRAM_GATEWAY_STARTUP_WAIT_SECONDS:-45}"
  local deadline=$((SECONDS + wait_seconds))

  while true; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      return 2
    fi
    if runtime_revision_matches && runtime_ready_matches; then
      return 0
    fi
    if (( SECONDS >= deadline )); then
      return 1
    fi
    sleep 1
  done
}

publish_runtime_status() {
  command -v gh >/dev/null 2>&1 || return 0
  gh auth status >/dev/null 2>&1 || return 0
  configure_cloud_routing >/dev/null 2>&1 || return 0

  local local_head remote_head loaded pid state description repo
  local -a pids=()
  local_head="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || true)"
  remote_head="$(remote_repo_revision 2>/dev/null || true)"
  loaded="$(loaded_runtime_revision 2>/dev/null || true)"
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  repo="${GITHUB_ACTIONS_REPOSITORY:-zenindiones-maker/BR-no-GTA}"
  mapfile -t pids < <(gateway_pids)

  [[ -n "${remote_head}" ]] || return 0
  state="error"
  if [[ "${#pids[@]}" -eq 1 && -n "${local_head}" && -n "${loaded}" && "${local_head}" == "${remote_head}" && "${loaded}" == "${local_head}" ]] && runtime_ready_matches; then
    if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null; then
      state="success"
    fi
  fi
  description="pid=${pid:-none} instances=${#pids[@]} sha=${loaded:-missing} local=${local_head:0:12} runtime=${loaded:0:12} remote=${remote_head:0:12}"
  gh api     --method POST     -H "Accept: application/vnd.github+json"     "repos/${repo}/statuses/${remote_head}"     -f "state=${state}"     -f "context=telegram-a15-runtime"     -f "description=${description}"     >/dev/null 2>&1 || true
}

publish_semantic_lineage_statuses() {
  command -v gh >/dev/null 2>&1 || return 0
  gh auth status >/dev/null 2>&1 || return 0
  configure_cloud_routing >/dev/null 2>&1 || return 0
  runtime_revision_matches || return 0
  runtime_ready_matches || return 0

  local remote_head repo line context state description
  remote_head="$(remote_repo_revision 2>/dev/null || true)"
  [[ -n "${remote_head}" ]] || return 0
  repo="${GITHUB_ACTIONS_REPOSITORY:-zenindiones-maker/BR-no-GTA}"

  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  cd "${ROOT}"
  while IFS='|' read -r context state description; do
    [[ -n "${context}" ]] || continue
    [[ "${state}" == "success" || "${state}" == "failure" || "${state}" == "error" || "${state}" == "pending" ]] || state="error"
    gh api \
      --method POST \
      -H "Accept: application/vnd.github+json" \
      "repos/${repo}/statuses/${remote_head}" \
      -f "state=${state}" \
      -f "context=${context}" \
      -f "description=${description}" \
      >/dev/null 2>&1 || true
  done < <("${PYTHON_BIN}" scripts/telegram_semantic_lineage_attestation.py 2>/dev/null || true)
}

heartbeat_gateway() {
  local status=0
  runtime_revision_report || status=$?
  publish_runtime_status
  if [[ "${status}" -eq 0 ]]; then
    publish_semantic_lineage_statuses
  fi
  return "${status}"
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

reap_untracked_legacy_supervisors() {
  local tracked="" pid
  tracked="$(cat "${SUPERVISOR_PID_FILE}" 2>/dev/null || true)"
  while IFS= read -r pid; do
    [[ "${pid}" =~ ^[0-9]+$ ]] || continue
    [[ "${pid}" == "$" || "${pid}" == "${PPID}" || "${pid}" == "${tracked}" ]] && continue
    echo "TELEGRAM_SUPERVISOR=REAPING_UNTRACKED PID=${pid}"
    kill "${pid}" 2>/dev/null || true
  done < <(
    "${PYTHON_BIN}" - <<'PY'
from pathlib import Path
import os
for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    pid = int(entry.name)
    if pid == os.getpid():
        continue
    try:
        argv = [
            part.decode("utf-8", errors="replace")
            for part in (entry / "cmdline").read_bytes().split(b"\0")
            if part
        ]
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if any(arg.endswith("/telegram-supervisor.sh") for arg in argv):
        print(pid)
PY
  )
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

handoff_owner_voice_references() {
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  export TELEGRAM_CONTROL_STATE_FILE="${STATE_DIR}/telegram-control.json"
  export BR_GITHUB_REPOSITORY="zenindiones-maker/BR-no-GTA"
  export BR_GITHUB_BRANCH
  BR_GITHUB_BRANCH="${CANONICAL_BRANCH}"
  export BR_OWNER_VOICE_HANDOFF_STATE_FILE="${STATE_DIR}/owner-voice-reference-handoff.json"
  cd "${ROOT}"
  "${PYTHON_BIN}" scripts/owner_voice_reference_handoff.py
}


is_running() {
  [[ -s "${PID_FILE}" ]] || return 1
  local pid
  pid="$(cat "${PID_FILE}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  pid_is_current_gateway "${pid}" || return 1
  runtime_revision_matches && runtime_ready_matches
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
    if runtime_revision_matches && runtime_ready_matches; then
      echo "TELEGRAM_GATEWAY=ADOPTED_EXISTING PID=${current_pids[0]} REVISION=$(current_repo_revision)"
      release_start_lock
      return 0
    fi
    echo "TELEGRAM_GATEWAY=STALE_CODE refusing to adopt PID=${current_pids[0]}"
    rm -f "${PID_FILE}"
  fi

  if [[ ${#all_pids[@]} -gt 0 ]]; then
    echo "TELEGRAM_GATEWAY_SINGLETON=RECONCILING STALE_OR_DUPLICATE_COUNT=${#all_pids[@]}"
    terminate_gateway_pids "${all_pids[@]}"
    rm -f "${PID_FILE}" "${REVISION_FILE}" "${READY_FILE}"
  fi

  if ! runtime_dependency_readiness; then
    release_start_lock
    return 1
  fi
  if ! load_token; then
    release_start_lock
    return 1
  fi
  if ! configure_cloud_routing; then
    release_start_lock
    return 1
  fi
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  export TELEGRAM_CONTROL_STATE_FILE="${STATE_DIR}/telegram-control.json"
  export TELEGRAM_GATEWAY_REVISION_FILE="${REVISION_FILE}"
  export TELEGRAM_GATEWAY_READY_FILE="${READY_FILE}"
  export BR_TELEGRAM_GATEWAY_REVISION
  BR_TELEGRAM_GATEWAY_REVISION="$(current_repo_revision)"
  rm -f "${REVISION_FILE}" "${READY_FILE}"

  if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock >/dev/null 2>&1 || true
  fi

  cd "${ROOT}"
  nohup "${PYTHON_BIN}" -u scripts/telegram_harness_gateway_v2.py \
    >>"${LOG_FILE}" 2>&1 </dev/null &
  local pid=$!
  printf '%s\n' "${pid}" > "${PID_FILE}"

  if kill -0 "${pid}" 2>/dev/null && pid_is_current_gateway "${pid}"; then
    if ! wait_for_runtime_ready "${pid}"; then
      echo "TELEGRAM_GATEWAY=FAIL runtime revision/readiness proof mismatch" >&2
      echo "EXPECTED_REVISION=${BR_TELEGRAM_GATEWAY_REVISION:-UNKNOWN}" >&2
      echo "TRACKED_PID=$(cat "${PID_FILE}" 2>/dev/null || echo MISSING)" >&2
      echo "REVISION_PROOF=$(cat "${REVISION_FILE}" 2>/dev/null || echo MISSING)" >&2
      echo "READY_PROOF=$(cat "${READY_FILE}" 2>/dev/null || echo MISSING)" >&2
      echo "=== TELEGRAM STARTUP LOG ===" >&2
      tail -n 120 "${LOG_FILE}" >&2 || true
      terminate_gateway_pids "${pid}"
      rm -f "${PID_FILE}" "${REVISION_FILE}" "${READY_FILE}"
      release_start_lock
      return 1
    fi
    echo "TELEGRAM_GATEWAY=STARTED PID=${pid}"
    echo "TELEGRAM_GATEWAY_REVISION=${BR_TELEGRAM_GATEWAY_REVISION}"
    publish_runtime_status
    if [[ "${BR_TELEGRAM_SUPPRESS_OWNER_VOICE_HANDOFF_ON_START:-0}" == "1" ]]; then
      echo "OWNER_VOICE_REFERENCE_HANDOFF=SUPPRESSED_FOR_RUNTIME_DEPLOY"
    else
      handoff_owner_voice_references || true
    fi
    echo "TELEGRAM_LOG=${LOG_FILE}"
    echo "BR_OMNIROUTE_REF=${BR_OMNIROUTE_REF}"
    release_start_lock
    tail -n 20 "${LOG_FILE}" || true
  else
    echo "TELEGRAM_GATEWAY=FAIL"
    tail -n 80 "${LOG_FILE}" || true
    rm -f "${PID_FILE}" "${REVISION_FILE}" "${READY_FILE}"
    release_start_lock
    return 1
  fi
}

stop_gateway() {
  local -a pids=()
  mapfile -t pids < <(gateway_pids)

  if [[ ${#pids[@]} -eq 0 ]]; then
    rm -f "${PID_FILE}" "${REVISION_FILE}" "${READY_FILE}"
    release_start_lock
    echo "TELEGRAM_GATEWAY=STOPPED"
    return 0
  fi

  terminate_gateway_pids "${pids[@]}"
  rm -f "${PID_FILE}" "${REVISION_FILE}" "${READY_FILE}"
  release_start_lock
  if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock >/dev/null 2>&1 || true
  fi
  echo "TELEGRAM_GATEWAY=STOPPED KILLED_INSTANCES=${#pids[@]}"
}

status_gateway() {
  local status=0
  if is_running; then
    local -a pids=()
    mapfile -t pids < <(gateway_pids)
    if [[ ${#pids[@]} -ne 1 ]]; then
      echo "TELEGRAM_GATEWAY=CONFLICT INSTANCES=${#pids[@]} TRACKED_PID=$(cat "${PID_FILE}")"
      status=2
    else
      echo "TELEGRAM_GATEWAY=RUNNING PID=$(cat "${PID_FILE}") INSTANCES=1"
    fi
  else
    local -a pids=()
    mapfile -t pids < <(gateway_pids)
    if [[ ${#pids[@]} -gt 0 ]]; then
      local expected loaded=""
      expected="$(current_repo_revision 2>/dev/null || true)"
      loaded="$(loaded_runtime_revision 2>/dev/null || true)"
      echo "TELEGRAM_GATEWAY=STALE_CODE INSTANCES=${#pids[@]} PIDS=${pids[*]} EXPECTED_REVISION=${expected:-UNKNOWN} LOADED_REVISION=${loaded:-MISSING}"
      status=2
    else
      echo "TELEGRAM_GATEWAY=NOT_RUNNING"
      status=1
    fi
  fi
  runtime_revision_report || status=2
  publish_runtime_status
  return "${status}"
}

cleanup_gateway_deploy_state() {
  rm -f "${MAINTENANCE_FILE}" 2>/dev/null || true
  release_start_lock
}

foreground_gateway() {
  local -a pids=()
  mapfile -t pids < <(gateway_pids)
  if [[ ${#pids[@]} -gt 0 ]]; then
    echo "TELEGRAM_GATEWAY=FAIL foreground refused while another gateway instance exists: ${pids[*]}" >&2
    return 1
  fi
  runtime_dependency_readiness
  load_token
  configure_cloud_routing
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  export TELEGRAM_CONTROL_STATE_FILE="${STATE_DIR}/telegram-control.json"
  export TELEGRAM_GATEWAY_REVISION_FILE="${REVISION_FILE}"
  export TELEGRAM_GATEWAY_READY_FILE="${READY_FILE}"
  export BR_TELEGRAM_GATEWAY_REVISION
  BR_TELEGRAM_GATEWAY_REVISION="$(current_repo_revision)"
  rm -f "${REVISION_FILE}" "${READY_FILE}"
  cd "${ROOT}"
  exec "${PYTHON_BIN}" -u scripts/telegram_harness_gateway_v2.py
}

doctor_gateway() {
  local status=0
  echo "=== TELEGRAM RUNTIME ==="
  runtime_revision_report || status=2

  local -a pids=()
  mapfile -t pids < <(gateway_pids)
  echo "RUNNING_GATEWAY_INSTANCES=${#pids[@]}"
  if [[ ${#pids[@]} -eq 1 ]]; then
    echo "TELEGRAM_GATEWAY_SINGLETON=PASS"
  else
    echo "TELEGRAM_GATEWAY_SINGLETON=FAIL"
    status=2
  fi

  echo "=== TELEGRAM BOT POLICY ==="
  load_token
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  export TELEGRAM_CONTROL_STATE_FILE="${STATE_DIR}/telegram-control.json"
  cd "${ROOT}"
  "${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.telegram_harness_gateway import TelegramApi

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    raise SystemExit("TELEGRAM_DOCTOR=FAIL token unavailable")

api = TelegramApi(token)
me = api.call("getMe")
webhook = api.call("getWebhookInfo")
state_path = Path(
    os.environ.get(
        "TELEGRAM_CONTROL_STATE_FILE",
        str(Path.home() / ".local/state/br-no-gta/telegram-control.json"),
    )
)
try:
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
except Exception:
    state = {}

can_join = bool((me or {}).get("can_join_groups"))
can_read_all = bool((me or {}).get("can_read_all_group_messages"))
webhook_url = str((webhook or {}).get("url") or "").strip()
allowed_chats = sorted({
    int(value)
    for value in (state.get("allowed_chat_ids") or [])
    if str(value).lstrip("-").isdigit()
})
paired_chat = state.get("chat_id")
if paired_chat not in (None, ""):
    try:
        allowed_chats = sorted(set(allowed_chats) | {int(paired_chat)})
    except (TypeError, ValueError):
        pass

print(f"TELEGRAM_BOT_USERNAME={(me or {}).get('username') or ''}")
print(f"TELEGRAM_BOT_CAN_JOIN_GROUPS={'YES' if can_join else 'NO'}")
print(
    "TELEGRAM_BOT_CAN_READ_ALL_GROUP_MESSAGES="
    + ("YES" if can_read_all else "NO")
)
print(
    "TELEGRAM_GROUP_NATURAL_LANGUAGE_READY="
    + ("PASS" if can_join and can_read_all else "FAIL")
)
print("TELEGRAM_WEBHOOK_CONFLICT=" + ("YES" if webhook_url else "NO"))
print(f"PAIRED_USER_ID={state.get('allowed_user_id') or 'NONE'}")
print(
    "ALLOWED_CHAT_IDS="
    + (",".join(str(item) for item in allowed_chats) if allowed_chats else "NONE")
)
if can_join and not can_read_all:
    print(
        "GROUP_BLOCKER=Telegram privacy mode prevents ordinary group messages; "
        "commands/replies/mentions may still arrive."
    )
PY

  echo "=== RECENT GATEWAY LOG ==="
  tail -n 40 "${LOG_FILE}" 2>/dev/null || true
  return "${status}"
}

source_proof() {
  configure_cloud_routing
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  cd "${ROOT}"
  if [[ -n "${2:-}" ]]; then
    exec "${PYTHON_BIN}" scripts/process_real_telegram_source.py --input-id "${2}"
  fi
  exec "${PYTHON_BIN}" scripts/process_real_telegram_source.py
}

presentation_proof() {
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  cd "${ROOT}"
  exec bash scripts/prove_real_telegram_presentation.sh "${2:-}" "${3:-}"
}

obsidian_bridge() {
  load_token
  configure_cloud_routing
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  cd "${ROOT}"
  if [[ -n "${2:-}" ]]; then
    exec "${PYTHON_BIN}" scripts/telegram_obsidian_bridge.py --input-id "${2}"
  fi
  exec "${PYTHON_BIN}" scripts/telegram_obsidian_bridge.py --latest
}

restart_gateway() {
  # Prevent the persistence supervisor from racing the intentional stop/start.
  : > "${MAINTENANCE_FILE}"
  trap 'cleanup_gateway_deploy_state' EXIT INT TERM
  if ! candidate_runtime_preflight; then
    echo "TELEGRAM_RESTART_PREFLIGHT=FAIL listener preserved when available" >&2
    return 1
  fi
  stop_gateway
  start_gateway
  cleanup_gateway_deploy_state
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
  reconcile)
    reconcile_gateway
    ;;
  status)
    status_gateway
    ;;
  runtime-attest)
    runtime_identity_attest
    ;;
  heartbeat)
    heartbeat_gateway
    ;;
  preflight)
    candidate_runtime_preflight
    ;;
  logs)
    tail -n "${2:-80}" "${LOG_FILE}" 2>/dev/null || true
    ;;
  doctor)
    doctor_gateway
    ;;
  foreground)
    foreground_gateway
    ;;
  source-proof)
    source_proof "$@"
    ;;
  presentation-proof)
    presentation_proof "$@"
    ;;
  obsidian-bridge)
    obsidian_bridge "$@"
    ;;
  *)
    echo "uso: $0 {start|stop|restart|reconcile|status|heartbeat|preflight|doctor|logs [N]|foreground|source-proof [INPUT_ID]|presentation-proof [TEST_INPUT_ID] [SOURCE_INPUT_ID]|obsidian-bridge [INPUT_ID]}" >&2
    exit 2
    ;;
esac
