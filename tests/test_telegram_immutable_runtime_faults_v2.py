from __future__ import annotations

from pathlib import Path
import os
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "telegram_a15_immutable_deploy.sh"


def _prefix() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    return text.split('case "${1:-reconcile}" in', 1)[0]


def _run_shell(tmp_path: Path, body: str, *, check: bool = True):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    cp = subprocess.run(
        ["bash"],
        input=_prefix() + "\n" + body,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if check and cp.returncode != 0:
        raise AssertionError(
            f"shell failed rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
        )
    return cp, home


def _success_overrides() -> str:
    return r'''
EVENTS="${HOME}/events.log"
ensure_deploy_repo() { :; }
desired_sha() { printf '%s\n' "dddddddddddddddddddddddddddddddddddddddd"; }
active_sha() { printf '%s\n' "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; }
materialize_release() {
  mkdir -p "${RELEASES_DIR}/dddddddddddddddddddddddddddddddddddddddd"
  printf '%s\n' "CANDIDATE_TREE_SHA=cccccccccccccccccccccccccccccccccccccccc"
  printf '%s\n' "${RELEASES_DIR}/dddddddddddddddddddddddddddddddddddddddd"
}
ensure_runtime_env() {
  local root="${ENV_DIR}/dddddddddddddddddddddddddddddddddddddddd"
  mkdir -p "${root}/bin"
  : > "${root}/bin/python"
  chmod +x "${root}/bin/python"
  printf '%s\n' "${root}"
}
candidate_preflight() { echo "preflight" >> "${EVENTS}"; return 0; }
stop_known_good() { echo "stop" >> "${EVENTS}"; return 0; }
start_release() { echo "start" >> "${EVENTS}"; return 0; }
attest_release() { echo "attest" >> "${EVENTS}"; return 0; }
activate_release_pointer() { echo "activate" >> "${EVENTS}"; return 0; }
create_github_deployment() { echo "101"; }
publish_github_deployment_status() {
  echo "status:$1:$2:$3" >> "${EVENTS}"
  return 0
}
verify_github_deployment_status() {
  echo "readback:$1:$2" >> "${EVENTS}"
  return 0
}
'''


def test_dirty_development_workspace_does_not_block_runtime_reconcile(tmp_path: Path):
    cp, home = _run_shell(
        tmp_path,
        _success_overrides()
        + r'''
DEV="${HOME}/GTA/BR"
mkdir -p "${DEV}"
git -C "${DEV}" init -q
git -C "${DEV}" config user.name Test
git -C "${DEV}" config user.email test@example.invalid
mkdir -p "${DEV}/app"
printf 'A=1\n' > "${DEV}/app/base.py"
git -C "${DEV}" add app/base.py
git -C "${DEV}" commit -qm base
printf 'A=2\n' > "${DEV}/app/base.py"
git -C "${DEV}" add app/base.py
git -C "${DEV}" commit -qm local-only
printf 'dirty\n' >> "${DEV}/app/base.py"
printf 'untracked\n' > "${DEV}/config.yaml"
BEFORE="$(git -C "${DEV}" status --porcelain=v1 -uall)"
reconcile_runtime
AFTER="$(git -C "${DEV}" status --porcelain=v1 -uall)"
printf 'DEV_STATE_EQUAL=%s\n' "$([[ "${BEFORE}" == "${AFTER}" ]] && echo YES || echo NO)"
cat "${EVENTS}"
''',
    )
    assert "DEPLOYMENT=SUCCESS" in cp.stdout
    assert "ACTIVE_RUNTIME_SHA=dddddddddddddddddddddddddddddddddddddddd" in cp.stdout
    assert "DEV_STATE_EQUAL=YES" in cp.stdout
    lines = cp.stdout.splitlines()
    assert lines.index("preflight") < lines.index("stop") < lines.index("start")
    assert "status:101:queued:queued" in lines
    assert "status:101:in_progress:in_progress" in lines
    assert "status:101:success:success" in lines
    assert "readback:101:success" in lines


def test_preflight_failure_preserves_known_good_listener(tmp_path: Path):
    body = _success_overrides() + r'''
candidate_preflight() { echo "preflight-fail" >> "${EVENTS}"; return 1; }
set +e
reconcile_runtime
RC="$?"
set -e
printf 'RC=%s\n' "${RC}"
cat "${EVENTS}"
'''
    cp, _ = _run_shell(tmp_path, body, check=True)
    assert "RC=1" in cp.stdout
    assert "preflight-fail" in cp.stdout
    assert "\nstop\n" not in f"\n{cp.stdout}\n"
    assert "\nstart\n" not in f"\n{cp.stdout}\n"
    assert "status:101:failure:preflight_failed" in cp.stdout


def test_rollback_known_good_restarts_previous_sha_and_records_distinct_deployment(tmp_path: Path):
    previous = "a" * 40
    desired = "d" * 40
    body = r'''
EVENTS="${HOME}/rollback-events.log"
PREVIOUS="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DESIRED="dddddddddddddddddddddddddddddddddddddddd"
FAILED_DEPLOYMENT="101"
mkdir -p "${RELEASES_DIR}/${PREVIOUS}" "${ENV_DIR}/${PREVIOUS}/bin"
: > "${ENV_DIR}/${PREVIOUS}/bin/python"
chmod +x "${ENV_DIR}/${PREVIOUS}/bin/python"
git_bare() {
  if [[ "$1" == "rev-parse" ]]; then
    echo "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    return 0
  fi
  return 0
}
create_github_deployment() {
  echo "202"
}
publish_github_deployment_status() {
  echo "status:$1:$2:$3" >> "${EVENTS}"
  return 0
}
verify_github_deployment_status() {
  echo "readback:$1:$2" >> "${EVENTS}"
  return 0
}
control_for() {
  echo "/fake/control.sh"
}
bash() {
  echo "control:$*" >> "${EVENTS}"
  return 0
}
activate_release_pointer() {
  echo "activate:$1" >> "${EVENTS}"
  return 0
}
rollback_known_good "${PREVIOUS}" "${FAILED_DEPLOYMENT}" "${DESIRED}"
cat "${EVENTS}"
printf 'KNOWN_GOOD=%s\n' "$(cat "${KNOWN_GOOD_FILE}")"
'''
    cp, _ = _run_shell(tmp_path, body)
    assert f"ROLLBACK_RUNTIME_REVISION={previous}" in cp.stdout
    assert "ROLLBACK_DEPLOYMENT_ID=202" in cp.stdout
    assert "ROLLBACK_GATEWAY_SINGLETON=PASS" in cp.stdout
    assert "ROLLBACK_GATEWAY_READY=PASS" in cp.stdout
    assert "status:101:failure:candidate_failed" in cp.stdout
    assert "status:202:in_progress:rollback_in_progress" in cp.stdout
    assert "status:202:success:rollback_success" in cp.stdout
    assert "readback:202:success" in cp.stdout
    assert f"KNOWN_GOOD={previous}" in cp.stdout


def test_deployment_lock_allows_only_one_reconcile_writer(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    marker = home / "preflight-entered"
    harness = tmp_path / "reconcile-harness.sh"
    harness.write_text(
        _prefix()
        + "\n"
        + _success_overrides()
        + r'''
candidate_preflight() {
  touch "${HOME}/preflight-entered"
  sleep 1
  return 0
}
reconcile_runtime
''',
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["HOME"] = str(home)

    first = subprocess.Popen(
        ["bash", str(harness)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    deadline = time.time() + 5
    while not marker.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert marker.exists(), "first deploy never reached preflight under lock"

    second = subprocess.run(
        ["bash", str(harness)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    first_out, first_err = first.communicate(timeout=10)

    assert first.returncode == 0, first_err
    assert "DEPLOYMENT=SUCCESS" in first_out
    assert second.returncode == 0
    assert "DEPLOYMENT_CONCURRENCY=HELD" in second.stdout


def test_restart_reconciles_persisted_interrupted_candidate_back_to_known_good(tmp_path: Path):
    body = r"""
PREVIOUS="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DESIRED="dddddddddddddddddddddddddddddddddddddddd"
EVENTS="${HOME}/restart-events.log"
mkdir -p "${RELEASES_DIR}/${PREVIOUS}" "${ENV_DIR}/${PREVIOUS}/bin"
: > "${ENV_DIR}/${PREVIOUS}/bin/python"
chmod +x "${ENV_DIR}/${PREVIOUS}/bin/python"
cat > "${DEPLOY_STATUS_FILE}" <<EOF
CANONICAL_SHA=${DESIRED}
CANDIDATE_TREE_SHA=cccccccccccccccccccccccccccccccccccccccc
PREVIOUS_KNOWN_GOOD_SHA=${PREVIOUS}
DEPLOYMENT_STATE=rollback_in_progress
DEPLOYMENT_ID=101
ROLLBACK_DEPLOYMENT_ID=
A15_RUNTIME_IDENTITY=a15-telegram-production
TIMESTAMP=2026-10-04T00:00:00Z
EOF
printf "%s\n" "${PREVIOUS}" > "${KNOWN_GOOD_FILE}"
ensure_deploy_repo() { :; }
desired_sha() { printf "%s\n" "${DESIRED}"; }
active_sha() { return 1; }
git_bare() {
  if [[ "$1" == "rev-parse" ]]; then echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; return 0; fi
  return 0
}
create_github_deployment() { echo 202; }
publish_github_deployment_status() { echo "status:$1:$2:$3" >> "${EVENTS}"; }
verify_github_deployment_status() { return 0; }
control_for() { echo /fake/control.sh; }
bash() { echo "control:$*" >> "${EVENTS}"; return 0; }
activate_release_pointer() { echo "activate:$1" >> "${EVENTS}"; }
recover_interrupted_deployment
cat "${EVENTS}"
cat "${DEPLOY_STATUS_FILE}"
"""
    cp,_ = _run_shell(tmp_path, body)
    assert "status:202:success:rollback_success" in cp.stdout
    assert "DEPLOYMENT_STATE=rollback_success" in cp.stdout
    assert "PREVIOUS_KNOWN_GOOD_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in cp.stdout


def test_successful_candidate_fails_closed_when_remote_status_readback_is_missing(tmp_path: Path):
    body = _success_overrides() + r"""
verify_github_deployment_status() { echo "readback-fail:$1:$2" >> "${EVENTS}"; return 1; }
set +e
reconcile_runtime
RC="$?"
set -e
printf 'RC=%s\n' "${RC}"
cat "${EVENTS}"
cat "${DEPLOY_STATUS_FILE}"
"""
    cp,_ = _run_shell(tmp_path, body)
    assert "RC=1" in cp.stdout
    assert "readback-fail:101:success" in cp.stdout
    assert "DEPLOYMENT_STATE=remote_readback_pending" in cp.stdout


def test_start_release_closes_deployment_lock_fd_before_control_child():
    source = SCRIPT.read_text(encoding="utf-8")
    body = source.split("start_release() {", 1)[1].split("\n}", 1)[0]
    assert '9>&-' in body


def test_attest_release_propagates_status_failure_even_if_doctor_succeeds(tmp_path: Path):
    body = r"""
control_for() { echo /fake/control.sh; }
bash() {
  case "$*" in
    *" runtime-attest") return 7 ;;
    *" doctor") return 0 ;;
  esac
  return 0
}
set +e
attest_release aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa /fake/release /fake/env bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
RC="$?"
set -e
printf 'ATTEST_RC=%s\n' "$RC"
"""
    cp, _ = _run_shell(tmp_path, body)
    assert "ATTEST_RC=7" in cp.stdout


def test_rollback_uses_exact_identity_attestation_not_canonical_status():
    source = SCRIPT.read_text(encoding="utf-8")
    body = source.split("rollback_known_good() {", 1)[1].split("\n}", 1)[0]
    assert 'attest_release "${previous_sha}" "${previous_release}" "${previous_env}" "${previous_tree}"' in body
    assert 'bash "${control}" status' not in body


def test_persistent_runtime_does_not_inherit_deployment_lock_fd(tmp_path: Path):
    body = r"""
CONTROL="${HOME}/fake-control.sh"
CHILD_PID_FILE="${HOME}/child.pid"
cat > "${CONTROL}" <<'EOF'
#!/bin/bash
if [[ "${1:-}" == "start" ]]; then
  nohup sleep 8 >/dev/null 2>&1 </dev/null &
  printf '%s\n' "$!" > "${HOME}/child.pid"
fi
exit 0
EOF
chmod +x "${CONTROL}"
control_for() { printf '%s\n' "${CONTROL}"; }
mkdir -p "${RELEASES_DIR}/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
mkdir -p "${ENV_DIR}/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bin"
: > "${ENV_DIR}/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bin/python"
chmod +x "${ENV_DIR}/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bin/python"
exec 9>"${DEPLOY_LOCK}"
flock -n 9
start_release aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "${RELEASES_DIR}/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" "${ENV_DIR}/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
exec 9>&-
SECOND="$(bash -c 'exec 9>"$1"; if flock -n 9; then echo ACQUIRED; else echo HELD; fi' _ "${DEPLOY_LOCK}")"
printf 'SECOND_LOCK=%s\n' "${SECOND}"
kill "$(cat "${CHILD_PID_FILE}")" 2>/dev/null || true
"""
    cp,_ = _run_shell(tmp_path, body)
    assert "SECOND_LOCK=ACQUIRED" in cp.stdout


def test_restart_recovery_precedes_remote_fetch_when_origin_is_unavailable(tmp_path: Path):
    body = r"""
PREVIOUS="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DESIRED="dddddddddddddddddddddddddddddddddddddddd"
EVENTS="${HOME}/restart-order.log"
mkdir -p "${RELEASES_DIR}/${PREVIOUS}" "${ENV_DIR}/${PREVIOUS}/bin"
: > "${ENV_DIR}/${PREVIOUS}/bin/python"
chmod +x "${ENV_DIR}/${PREVIOUS}/bin/python"
cat > "${DEPLOY_STATUS_FILE}" <<EOF
CANONICAL_SHA=${DESIRED}
CANDIDATE_TREE_SHA=cccccccccccccccccccccccccccccccccccccccc
PREVIOUS_KNOWN_GOOD_SHA=${PREVIOUS}
DEPLOYMENT_STATE=rollback_in_progress
DEPLOYMENT_ID=101
ROLLBACK_DEPLOYMENT_ID=
A15_RUNTIME_IDENTITY=a15-telegram-production
TIMESTAMP=2026-10-04T00:00:00Z
EOF
ensure_deploy_repo() { echo fetch >> "${EVENTS}"; return 1; }
git_bare() {
  if [[ "$1" == "rev-parse" ]]; then echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; return 0; fi
  return 0
}
create_github_deployment() { echo 202; }
publish_github_deployment_status() { :; }
verify_github_deployment_status() { return 0; }
control_for() { echo /fake/control.sh; }
bash() { echo rollback >> "${EVENTS}"; return 0; }
activate_release_pointer() { :; }
set +e
reconcile_runtime
RC="$?"
set -e
printf 'RC=%s\n' "${RC}"
cat "${EVENTS}"
"""
    cp,_ = _run_shell(tmp_path, body)
    lines = cp.stdout.splitlines()
    assert "rollback" in lines
    assert "fetch" in lines
    assert lines.index("rollback") < lines.index("fetch")
