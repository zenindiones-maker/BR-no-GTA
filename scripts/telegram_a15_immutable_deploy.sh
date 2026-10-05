#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

REPOSITORY="zenindiones-maker/BR-no-GTA"
REMOTE_URL="${BR_GITHUB_REMOTE_URL:-https://github.com/zenindiones-maker/BR-no-GTA.git}"
CANONICAL_BRANCH="work/gate6f-analytics-learning"
DEPLOY_ROOT="${HOME}/.local/share/br-no-gta/deploy"
DEPLOY_REPO="${DEPLOY_ROOT}/repo.git"
RELEASES_DIR="${DEPLOY_ROOT}/releases"
CURRENT_LINK="${DEPLOY_ROOT}/current"
ENV_DIR="${DEPLOY_ROOT}/envs"
STATE_DIR="${HOME}/.local/state/br-no-gta"
CONFIG_DIR="${HOME}/.config/br-no-gta"
DEPLOY_LOCK="${STATE_DIR}/telegram-a15-deploy.lock"
KNOWN_GOOD_FILE="${STATE_DIR}/telegram-a15-known-good.sha"
DEPLOY_STATUS_FILE="${STATE_DIR}/telegram-a15-deployment.env"
DEPLOYMENT_ENVIRONMENT="a15-telegram-production"
RUNTIME_IDENTITY="a15-telegram-production"

mkdir -p "${DEPLOY_ROOT}" "${RELEASES_DIR}" "${ENV_DIR}" "${STATE_DIR}" "${CONFIG_DIR}"
chmod 700 "${DEPLOY_ROOT}" "${STATE_DIR}" "${CONFIG_DIR}" 2>/dev/null || true

git_bare() {
  git --git-dir="${DEPLOY_REPO}" "$@"
}

ensure_deploy_repo() {
  if [[ ! -d "${DEPLOY_REPO}" ]]; then
    git clone --bare "${REMOTE_URL}" "${DEPLOY_REPO}"
  fi
  git_bare config remote.origin.url "${REMOTE_URL}"
  git_bare fetch --prune origin     "+refs/heads/${CANONICAL_BRANCH}:refs/remotes/origin/canonical"
}

desired_sha() {
  git_bare rev-parse refs/remotes/origin/canonical
}

release_path() {
  printf '%s/%s\n' "${RELEASES_DIR}" "$1"
}

env_path() {
  printf '%s/%s\n' "${ENV_DIR}" "$1"
}

active_release_path() {
  [[ -L "${CURRENT_LINK}" ]] || return 1
  readlink -f "${CURRENT_LINK}"
}

active_sha() {
  local release
  release="$(active_release_path 2>/dev/null || true)"
  [[ -n "${release}" && -d "${release}" ]] || return 1
  git -C "${release}" rev-parse HEAD 2>/dev/null
}

materialize_release() {
  local sha="$1" release expected_tree actual_tree
  release="$(release_path "${sha}")"
  expected_tree="$(git_bare rev-parse "${sha}^{tree}")"
  if [[ ! -d "${release}" ]]; then
    git_bare worktree add --detach "${release}" "${sha}"
  fi
  [[ "$(git -C "${release}" rev-parse HEAD)" == "${sha}" ]] || {
    echo "A15_RELEASE=FAIL exact commit mismatch" >&2
    return 1
  }
  actual_tree="$(git -C "${release}" rev-parse "HEAD^{tree}")"
  [[ "${actual_tree}" == "${expected_tree}" ]] || {
    echo "A15_RELEASE=FAIL tree identity mismatch" >&2
    return 1
  }
  if [[ -n "$(git -C "${release}" status --porcelain --untracked-files=all)" ]]; then
    echo "A15_RELEASE=FAIL immutable candidate checkout is dirty" >&2
    return 1
  fi
  printf 'CANDIDATE_TREE_SHA=%s\n' "${actual_tree}"
  printf '%s\n' "${release}"
}

ensure_runtime_env() {
  local sha="$1" release="$2" env_root bootstrap_python requirements
  env_root="$(env_path "${sha}")"
  bootstrap_python="$(command -v python 2>/dev/null || true)"
  [[ -n "${bootstrap_python}" ]] || {
    echo "A15_RUNTIME_ENV=FAIL bootstrap python unavailable" >&2
    return 1
  }
  if [[ ! -x "${env_root}/bin/python" ]]; then
    "${bootstrap_python}" -m venv "${env_root}"
  fi
  requirements="${release}/requirements/a15-telegram.txt"
  [[ -f "${requirements}" ]] || {
    echo "A15_RUNTIME_ENV=FAIL missing requirements/a15-telegram.txt" >&2
    return 1
  }
  "${env_root}/bin/python" -m pip install -r "${requirements}" >/dev/null
  printf '%s\n' "${env_root}"
}

control_for() {
  printf '%s/scripts/telegram_termux_control.sh\n' "$1"
}

candidate_preflight() {
  local sha="$1" release="$2" env_root="$3" control
  control="$(control_for "${release}")"
  BR_CANONICAL_BRANCH="${CANONICAL_BRANCH}"   BR_TELEGRAM_RUNTIME_ENV_ROOT="${env_root}"   BR_TELEGRAM_RUNTIME_RELEASE_SHA="${sha}"     bash "${control}" preflight
}

stop_known_good() {
  local release="$1" sha="$2" control env_root
  [[ -n "${release}" && -d "${release}" ]] || return 0
  control="$(control_for "${release}")"
  env_root="$(env_path "${sha}")"
  BR_CANONICAL_BRANCH="${CANONICAL_BRANCH}"   BR_TELEGRAM_RUNTIME_ENV_ROOT="${env_root}"   BR_TELEGRAM_RUNTIME_RELEASE_SHA="${sha}"     bash "${control}" stop
}

start_release() {
  local sha="$1" release="$2" env_root="$3" control
  control="$(control_for "${release}")"
  BR_CANONICAL_BRANCH="${CANONICAL_BRANCH}"   BR_TELEGRAM_RUNTIME_ENV_ROOT="${env_root}"   BR_TELEGRAM_RUNTIME_RELEASE_SHA="${sha}"   BR_TELEGRAM_SUPPRESS_OWNER_VOICE_HANDOFF_ON_START=1     bash "${control}" start 9>&-
}

attest_release() {
  local sha="$1" release="$2" env_root="$3" expected_tree="${4:-}" control
  control="$(control_for "${release}")"
  BR_CANONICAL_BRANCH="${CANONICAL_BRANCH}" \
  BR_TELEGRAM_RUNTIME_ENV_ROOT="${env_root}" \
  BR_TELEGRAM_RUNTIME_RELEASE_SHA="${sha}" \
  BR_TELEGRAM_GATEWAY_REVISION="${sha}" \
  BR_TELEGRAM_EXPECTED_TREE_SHA="${expected_tree}" \
    bash "${control}" runtime-attest >/dev/null || return $?
  BR_CANONICAL_BRANCH="${CANONICAL_BRANCH}" \
  BR_TELEGRAM_RUNTIME_ENV_ROOT="${env_root}" \
  BR_TELEGRAM_RUNTIME_RELEASE_SHA="${sha}" \
    bash "${control}" doctor >/dev/null || return $?
}

activate_release_pointer() {
  local release="$1" temporary
  temporary="${CURRENT_LINK}.next.$$"
  ln -s "${release}" "${temporary}"
  mv -Tf "${temporary}" "${CURRENT_LINK}"
}

github_deployment_payload() {
  local sha="$1" tree="$2" previous="$3" kind="$4" timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"ref":"%s","environment":"%s","auto_merge":false,"required_contexts":[],"description":"BR-no-GTA A15 Telegram exact SHA deployment","payload":{"canonical_sha":"%s","candidate_tree_sha":"%s","previous_known_good_sha":"%s","a15_runtime_identity":"%s","deployment_kind":"%s","timestamp":"%s"}}\n' \
    "${sha}" "${DEPLOYMENT_ENVIRONMENT}" "${sha}" "${tree}" "${previous}" "${RUNTIME_IDENTITY}" "${kind}" "${timestamp}"
}

create_github_deployment() {
  local sha="$1" tree="$2" previous="$3" kind="$4"
  local payload_file deployment_id
  command -v gh >/dev/null 2>&1 || {
    echo "GITHUB_DEPLOYMENT=FAIL gh unavailable" >&2
    return 1
  }
  payload_file="$(mktemp "${STATE_DIR}/github-deployment.XXXXXX.json")"
  github_deployment_payload "${sha}" "${tree}" "${previous}" "${kind}" > "${payload_file}"
  if ! deployment_id="$(
    gh api --method POST \
      -H "Accept: application/vnd.github+json" \
      "repos/${REPOSITORY}/deployments" \
      --input "${payload_file}" \
      --jq '.id'
  )"; then
    rm -f "${payload_file}"
    echo "GITHUB_DEPLOYMENT=FAIL create" >&2
    return 1
  fi
  rm -f "${payload_file}"
  [[ "${deployment_id}" =~ ^[0-9]+$ ]] || {
    echo "GITHUB_DEPLOYMENT=FAIL invalid deployment id" >&2
    return 1
  }
  printf '%s\n' "${deployment_id}"
}

publish_github_deployment_status() {
  local deployment_id="$1" state="$2" lifecycle="$3"
  local payload_file rc
  [[ "${deployment_id}" =~ ^[0-9]+$ ]] || return 1
  payload_file="$(mktemp "${STATE_DIR}/github-deployment-status.XXXXXX.json")"
  printf '{"state":"%s","description":"%s","environment":"%s","auto_inactive":false}\n' \
    "${state}" "${lifecycle}" "${DEPLOYMENT_ENVIRONMENT}" > "${payload_file}"
  set +e
  gh api --method POST \
    -H "Accept: application/vnd.github+json" \
    "repos/${REPOSITORY}/deployments/${deployment_id}/statuses" \
    --input "${payload_file}" >/dev/null
  rc="$?"
  set -e
  rm -f "${payload_file}"
  return "${rc}"
}

verify_github_deployment_status() {
  local deployment_id="$1" expected_state="$2" observed
  [[ "${deployment_id}" =~ ^[0-9]+$ ]] || return 1
  command -v gh >/dev/null 2>&1 || return 1
  observed="$(
    gh api -H "Accept: application/vnd.github+json"       "repos/${REPOSITORY}/deployments/${deployment_id}/statuses"       --jq '.[0].state' 2>/dev/null || true
  )"
  [[ "${observed}" == "${expected_state}" ]]
}

rollback_known_good() {
  local previous_sha="$1" failed_deployment_id="${2:-}" failed_desired_sha="${3:-}"
  local previous_release previous_env control previous_tree
  ROLLBACK_DEPLOYMENT_ID=""
  [[ -n "${previous_sha}" ]] || {
    echo "ROLLBACK=UNAVAILABLE no previous known-good SHA" >&2
    return 1
  }
  if [[ -n "${failed_deployment_id}" ]]; then
    publish_github_deployment_status "${failed_deployment_id}" "failure" "candidate_failed" || true
  fi
  previous_release="$(release_path "${previous_sha}")"
  previous_env="$(env_path "${previous_sha}")"
  [[ -d "${previous_release}" && -x "${previous_env}/bin/python" ]] || {
    echo "ROLLBACK=FAIL previous known-good materialization unavailable" >&2
    return 1
  }
  previous_tree="$(git_bare rev-parse "${previous_sha}^{tree}")"
  ROLLBACK_DEPLOYMENT_ID="$(
    create_github_deployment "${previous_sha}" "${previous_tree}" "${failed_desired_sha}" "rollback" 2>/dev/null || true
  )"
  if [[ -n "${ROLLBACK_DEPLOYMENT_ID}" ]]; then
    publish_github_deployment_status "${ROLLBACK_DEPLOYMENT_ID}" "in_progress" "rollback_in_progress" || true
  fi

  start_release "${previous_sha}" "${previous_release}" "${previous_env}"
  attest_release "${previous_sha}" "${previous_release}" "${previous_env}" "${previous_tree}"

  activate_release_pointer "${previous_release}"
  printf '%s\n' "${previous_sha}" > "${KNOWN_GOOD_FILE}"
  if [[ -n "${ROLLBACK_DEPLOYMENT_ID}" ]]; then
    publish_github_deployment_status "${ROLLBACK_DEPLOYMENT_ID}" "success" "rollback_success" || return 1
    verify_github_deployment_status "${ROLLBACK_DEPLOYMENT_ID}" "success" || {
      echo "ROLLBACK_REMOTE_READBACK=FAIL" >&2
      return 1
    }
    echo "ROLLBACK_REMOTE_READBACK=VERIFIED"
  fi
  echo "ROLLBACK_RUNTIME_REVISION=${previous_sha}"
  echo "ROLLBACK_DEPLOYMENT_ID=${ROLLBACK_DEPLOYMENT_ID:-UNAVAILABLE}"
  echo "ROLLBACK_GATEWAY_SINGLETON=PASS"
  echo "ROLLBACK_GATEWAY_READY=PASS"
}

recover_interrupted_deployment() {
  [[ -s "${DEPLOY_STATUS_FILE}" ]] || return 0
  local CANONICAL_SHA="" CANDIDATE_TREE_SHA="" PREVIOUS_KNOWN_GOOD_SHA=""
  local DEPLOYMENT_STATE="" DEPLOYMENT_ID="" ROLLBACK_DEPLOYMENT_ID=""
  local A15_RUNTIME_IDENTITY="" TIMESTAMP=""
  source "${DEPLOY_STATUS_FILE}"
  case "${DEPLOYMENT_STATE:-}" in
    rollback_in_progress|in_progress|queued)
      [[ -n "${PREVIOUS_KNOWN_GOOD_SHA:-}" ]] || {
        echo "RESTART_RECOVERY=FAIL missing previous known-good SHA" >&2
        return 1
      }
      write_deployment_state "${CANONICAL_SHA:-}" "${PREVIOUS_KNOWN_GOOD_SHA}" "rollback_in_progress" "${CANDIDATE_TREE_SHA:-}" "${DEPLOYMENT_ID:-}" "${ROLLBACK_DEPLOYMENT_ID:-}"
      rollback_known_good "${PREVIOUS_KNOWN_GOOD_SHA}" "${DEPLOYMENT_ID:-}" "${CANONICAL_SHA:-}"
      write_deployment_state "${CANONICAL_SHA:-}" "${PREVIOUS_KNOWN_GOOD_SHA}" "rollback_success" "${CANDIDATE_TREE_SHA:-}" "${DEPLOYMENT_ID:-}" "${ROLLBACK_DEPLOYMENT_ID:-}"
      echo "RESTART_RECOVERY=PASS"
      ;;
    remote_readback_pending)
      if verify_github_deployment_status "${DEPLOYMENT_ID:-}" "success"; then
        write_deployment_state "${CANONICAL_SHA:-}" "${PREVIOUS_KNOWN_GOOD_SHA:-}" "success" "${CANDIDATE_TREE_SHA:-}" "${DEPLOYMENT_ID:-}" "${ROLLBACK_DEPLOYMENT_ID:-}"
        echo "RESTART_REMOTE_READBACK=VERIFIED"
        return 0
      fi
      echo "RESTART_REMOTE_READBACK=PENDING" >&2
      return 1
      ;;
    rollback_success|success|failure|"")
      return 0
      ;;
    *)
      echo "RESTART_RECOVERY=FAIL unknown deployment state: ${DEPLOYMENT_STATE}" >&2
      return 1
      ;;
  esac
}

write_deployment_state() {
  local desired="$1" previous="$2" state="$3" tree="$4"
  local deployment_id="${5:-}" rollback_deployment_id="${6:-}"
  local tmp="${DEPLOY_STATUS_FILE}.tmp.$$"
  umask 077
  {
    printf 'CANONICAL_SHA=%q\n' "${desired}"
    printf 'CANDIDATE_TREE_SHA=%q\n' "${tree}"
    printf 'PREVIOUS_KNOWN_GOOD_SHA=%q\n' "${previous}"
    printf 'DEPLOYMENT_STATE=%q\n' "${state}"
    printf 'DEPLOYMENT_ID=%q\n' "${deployment_id}"
    printf 'ROLLBACK_DEPLOYMENT_ID=%q\n' "${rollback_deployment_id}"
    printf 'A15_RUNTIME_IDENTITY=%q\n' "${RUNTIME_IDENTITY}"
    printf 'TIMESTAMP=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "${tmp}"
  mv "${tmp}" "${DEPLOY_STATUS_FILE}"
}

reconcile_runtime() {
  exec 9>"${DEPLOY_LOCK}"
  if ! flock -n 9; then
    echo "DEPLOYMENT_CONCURRENCY=HELD"
    return 0
  fi

  recover_interrupted_deployment
  ensure_deploy_repo
  local DESIRED_SHA ACTIVE_RUNTIME_SHA PREVIOUS_KNOWN_GOOD_SHA active_tree
  local candidate_output candidate_release candidate_tree candidate_env previous_release
  local DEPLOYMENT_ID ROLLBACK_DEPLOYMENT_ID
  DEPLOYMENT_ID=""
  ROLLBACK_DEPLOYMENT_ID=""

  DESIRED_SHA="$(desired_sha)"
  ACTIVE_RUNTIME_SHA="$(active_sha 2>/dev/null || true)"
  PREVIOUS_KNOWN_GOOD_SHA="${ACTIVE_RUNTIME_SHA}"
  if [[ -z "${PREVIOUS_KNOWN_GOOD_SHA}" && -s "${KNOWN_GOOD_FILE}" ]]; then
    PREVIOUS_KNOWN_GOOD_SHA="$(cat "${KNOWN_GOOD_FILE}")"
  fi

  echo "DESIRED_SHA=${DESIRED_SHA}"
  echo "ACTIVE_RUNTIME_SHA=${ACTIVE_RUNTIME_SHA:-NONE}"
  echo "PREVIOUS_KNOWN_GOOD_SHA=${PREVIOUS_KNOWN_GOOD_SHA:-NONE}"

  if [[ "${DESIRED_SHA}" == "${ACTIVE_RUNTIME_SHA}" && -n "${ACTIVE_RUNTIME_SHA}" ]]; then
    candidate_release="$(release_path "${ACTIVE_RUNTIME_SHA}")"
    candidate_env="$(env_path "${ACTIVE_RUNTIME_SHA}")"
    active_tree="$(git_bare rev-parse "${ACTIVE_RUNTIME_SHA}^{tree}")"
    if attest_release "${ACTIVE_RUNTIME_SHA}" "${candidate_release}" "${candidate_env}" "${active_tree}"; then
      echo "NO_DEPLOY_REQUIRED"
      return 0
    fi
  fi

  candidate_output="$(materialize_release "${DESIRED_SHA}")"
  candidate_release="$(printf '%s\n' "${candidate_output}" | tail -n 1)"
  candidate_tree="$(printf '%s\n' "${candidate_output}" | awk -F= '/^CANDIDATE_TREE_SHA=/{print $2; exit}')"
  candidate_env="$(ensure_runtime_env "${DESIRED_SHA}" "${candidate_release}")"

  if ! DEPLOYMENT_ID="$(
    create_github_deployment "${DESIRED_SHA}" "${candidate_tree}" "${PREVIOUS_KNOWN_GOOD_SHA}" "candidate"
  )"; then
    write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "failure" "${candidate_tree}" "" ""
    echo "TELEGRAM_DEPLOY=FAIL GitHub deployment record unavailable; known-good preserved" >&2
    return 1
  fi
  write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "queued" "${candidate_tree}" "${DEPLOYMENT_ID}" ""
  publish_github_deployment_status "${DEPLOYMENT_ID}" "queued" "queued"
  publish_github_deployment_status "${DEPLOYMENT_ID}" "in_progress" "in_progress"
  write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "in_progress" "${candidate_tree}" "${DEPLOYMENT_ID}" ""

  if ! candidate_preflight "${DESIRED_SHA}" "${candidate_release}" "${candidate_env}"; then
    publish_github_deployment_status "${DEPLOYMENT_ID}" "failure" "preflight_failed" || true
    write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "failure" "${candidate_tree}" "${DEPLOYMENT_ID}" ""
    echo "TELEGRAM_DEPLOY_PREFLIGHT=FAIL known-good listener preserved" >&2
    return 1
  fi
  echo "TELEGRAM_DEPLOY_PREFLIGHT=PASS"

  previous_release=""
  if [[ -n "${PREVIOUS_KNOWN_GOOD_SHA}" ]]; then
    previous_release="$(release_path "${PREVIOUS_KNOWN_GOOD_SHA}")"
  fi
  stop_known_good "${previous_release}" "${PREVIOUS_KNOWN_GOOD_SHA}" || true

  if ! start_release "${DESIRED_SHA}" "${candidate_release}" "${candidate_env}"; then
    write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "rollback_in_progress" "${candidate_tree}" "${DEPLOYMENT_ID}" ""
    rollback_known_good "${PREVIOUS_KNOWN_GOOD_SHA}" "${DEPLOYMENT_ID}" "${DESIRED_SHA}"
    write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "rollback_success" "${candidate_tree}" "${DEPLOYMENT_ID}" "${ROLLBACK_DEPLOYMENT_ID}"
    return 1
  fi

  if ! attest_release "${DESIRED_SHA}" "${candidate_release}" "${candidate_env}" "${candidate_tree}"; then
    BR_CANONICAL_BRANCH="${CANONICAL_BRANCH}"     BR_TELEGRAM_RUNTIME_ENV_ROOT="${candidate_env}"     BR_TELEGRAM_RUNTIME_RELEASE_SHA="${DESIRED_SHA}"       bash "$(control_for "${candidate_release}")" stop || true
    write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "rollback_in_progress" "${candidate_tree}" "${DEPLOYMENT_ID}" ""
    rollback_known_good "${PREVIOUS_KNOWN_GOOD_SHA}" "${DEPLOYMENT_ID}" "${DESIRED_SHA}"
    write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "rollback_success" "${candidate_tree}" "${DEPLOYMENT_ID}" "${ROLLBACK_DEPLOYMENT_ID}"
    return 1
  fi

  activate_release_pointer "${candidate_release}"
  printf '%s\n' "${DESIRED_SHA}" > "${KNOWN_GOOD_FILE}"
  publish_github_deployment_status "${DEPLOYMENT_ID}" "success" "success"
  if ! verify_github_deployment_status "${DEPLOYMENT_ID}" "success"; then
    write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "remote_readback_pending" "${candidate_tree}" "${DEPLOYMENT_ID}" ""
    echo "DEPLOYMENT_REMOTE_READBACK=FAIL" >&2
    return 1
  fi
  write_deployment_state "${DESIRED_SHA}" "${PREVIOUS_KNOWN_GOOD_SHA}" "success" "${candidate_tree}" "${DEPLOYMENT_ID}" ""
  echo "DEPLOYMENT_REMOTE_READBACK=VERIFIED"
  echo "GITHUB_DEPLOYMENT_ID=${DEPLOYMENT_ID}"
  echo "A15_DEPLOYMENT_EXACT_SHA=PASS"
  echo "ACTIVE_RUNTIME_SHA=${DESIRED_SHA}"
  echo "DEPLOYMENT=SUCCESS"
}

case "${1:-reconcile}" in
  reconcile)
    reconcile_runtime
    ;;
  desired-sha)
    ensure_deploy_repo
    desired_sha
    ;;
  active-sha)
    active_sha
    ;;
  *)
    echo "usage: $0 {reconcile|desired-sha|active-sha}" >&2
    exit 2
    ;;
esac
