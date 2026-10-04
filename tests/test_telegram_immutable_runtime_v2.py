from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_a15_deploy_manager_uses_machine_managed_bare_repo_and_exact_release_sha():
    text = (ROOT / "scripts" / "telegram_a15_immutable_deploy.sh").read_text(encoding="utf-8")
    assert 'DEPLOY_REPO="${DEPLOY_ROOT}/repo.git"' in text
    assert 'RELEASES_DIR="${DEPLOY_ROOT}/releases"' in text
    assert 'CURRENT_LINK="${DEPLOY_ROOT}/current"' in text
    assert 'CANONICAL_BRANCH="work/gate6f-analytics-learning"' in text
    assert "git --git-dir" in text
    assert "worktree add --detach" in text
    assert "DESIRED_SHA=" in text
    assert "ACTIVE_RUNTIME_SHA=" in text


def test_deploy_candidate_preflight_happens_before_known_good_stop_and_has_rollback():
    text = (ROOT / "scripts" / "telegram_a15_immutable_deploy.sh").read_text(encoding="utf-8")
    reconcile = text.split("reconcile_runtime()", 1)[1]
    assert reconcile.index("candidate_preflight") < reconcile.index("stop_known_good")
    assert "PREVIOUS_KNOWN_GOOD_SHA=" in reconcile
    assert "rollback_known_good" in reconcile
    assert "ROLLBACK_RUNTIME_REVISION=" in text
    assert "ROLLBACK_GATEWAY_READY=PASS" in text
    assert "ROLLBACK_GATEWAY_SINGLETON=PASS" in text


def test_deploy_manager_never_checks_development_worktree_cleanliness():
    text = (ROOT / "scripts" / "telegram_a15_immutable_deploy.sh").read_text(encoding="utf-8")
    forbidden = ("~/GTA/BR", "working_tree_clean", "git status --porcelain", "merge --ff-only")
    assert all(token not in text for token in forbidden)


def test_runtime_control_uses_external_environment_and_fixed_canonical_ref():
    text = (ROOT / "scripts" / "telegram_termux_control.sh").read_text(encoding="utf-8")
    assert 'RUNTIME_ENV_ROOT="${BR_TELEGRAM_RUNTIME_ENV_ROOT:-${DEPLOY_ENV_BASE}/${RUNTIME_RELEASE_SHA}}"' in text
    assert 'PYTHON_BIN="${RUNTIME_ENV_ROOT}/bin/python"' in text
    assert 'CANONICAL_BRANCH="${BR_CANONICAL_BRANCH:-work/gate6f-analytics-learning}"' in text
    assert 'branch="${CANONICAL_BRANCH}"' in text
    assert "preflight)" in text


def test_persistence_supervisor_targets_deploy_manager_not_development_root():
    text = (ROOT / "scripts" / "install_telegram_termux_persistence.sh").read_text(encoding="utf-8")
    assert 'DEPLOY_MANAGER="${CONFIG_DIR}/telegram-a15-deploy-manager.sh"' in text
    supervisor = text.split("while true; do", 1)[1]
    assert 'bash "${DEPLOY_MANAGER}" reconcile' in supervisor
    assert 'git -C "${ROOT}"' not in supervisor
    assert 'working tree' not in supervisor.lower()


def test_a15_deploy_publishes_exact_github_deployment_record_before_stop():
    text = (ROOT / "scripts" / "telegram_a15_immutable_deploy.sh").read_text(encoding="utf-8")
    assert 'DEPLOYMENT_ENVIRONMENT="a15-telegram-production"' in text
    assert "create_github_deployment()" in text
    assert "publish_github_deployment_status()" in text
    assert '"auto_merge":false' in text
    assert '"required_contexts":[]' in text
    assert '"canonical_sha"' in text
    assert '"candidate_tree_sha"' in text
    assert '"previous_known_good_sha"' in text
    assert '"a15_runtime_identity"' in text

    reconcile = text.split("reconcile_runtime()", 1)[1]
    assert reconcile.index("create_github_deployment") < reconcile.index("stop_known_good")
    assert 'publish_github_deployment_status "${DEPLOYMENT_ID}" "queued"' in reconcile
    assert 'publish_github_deployment_status "${DEPLOYMENT_ID}" "in_progress"' in reconcile
    assert 'publish_github_deployment_status "${DEPLOYMENT_ID}" "success"' in reconcile


def test_a15_rollback_uses_distinct_previous_sha_deployment_record():
    text = (ROOT / "scripts" / "telegram_a15_immutable_deploy.sh").read_text(encoding="utf-8")
    rollback = text.split("rollback_known_good()", 1)[1].split("write_deployment_state()", 1)[0]
    assert "ROLLBACK_DEPLOYMENT_ID=" in rollback
    assert 'create_github_deployment "${previous_sha}"' in rollback
    assert '"rollback_in_progress"' in rollback
    assert '"rollback_success"' in rollback
    assert 'publish_github_deployment_status "${failed_deployment_id}" "failure"' in rollback
