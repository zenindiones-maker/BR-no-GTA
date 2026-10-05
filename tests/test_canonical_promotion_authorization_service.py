from __future__ import annotations

import inspect
import os
from pathlib import Path
import subprocess

import pytest

from app.database.schema import initialize_schema
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
    resolve_harness_authorization,
)
from app.services.security_guardian_service import SecurityReviewReceipt
import app.services.canonical_promotion_authorization_service as promotion_authority
from app.services.canonical_promotion_authorization_service import (
    CAPABILITY_ID,
    issue_exact_canonical_promotion_authorization,
)


WORK_REF = "refs/heads/work/gate6f-analytics-learning"
STAGING_REF = "refs/heads/staging/security-test-v1"


def run(cwd: Path, *args: str) -> str:
    cp = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True)
    return cp.stdout.strip()


def init_repo(tmp_path: Path):
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    run(repo, "git", "config", "user.email", "test@example.invalid")
    run(repo, "git", "config", "user.name", "Test")
    (repo / "app").mkdir()
    (repo / "app" / "x.py").write_text("X=1\n")
    run(repo, "git", "add", ".")
    run(repo, "git", "commit", "-m", "base")
    run(repo, "git", "branch", "-M", "work/gate6f-analytics-learning")
    base = run(repo, "git", "rev-parse", "HEAD")
    run(repo, "git", "remote", "add", "origin", str(remote))
    run(repo, "git", "push", "origin", "HEAD:work/gate6f-analytics-learning")
    (repo / "app" / "x.py").write_text("X=2\n")
    run(repo, "git", "add", ".")
    run(repo, "git", "commit", "-m", "candidate")
    candidate = run(repo, "git", "rev-parse", "HEAD")
    tree = run(repo, "git", "rev-parse", "HEAD^{tree}")
    run(repo, "git", "push", "origin", "HEAD:staging/security-test-v1")
    diff = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--no-textconv", "--binary", "--full-index", base, candidate],
        cwd=repo, capture_output=True, check=True,
    ).stdout
    import hashlib
    return repo, base, candidate, tree, hashlib.sha256(diff).hexdigest()


def review_fixture(monkeypatch, tmp_path: Path, *, disposition: str = "PASS"):
    db = tmp_path / "auth.sqlite3"
    monkeypatch.setenv("BR_TEST_DATABASE", str(db))
    initialize_schema()
    repo, base, candidate, tree, diff = init_repo(tmp_path)
    monkeypatch.setattr(promotion_authority, "_trusted_control_identity", lambda: (base, True))
    review_auth = issue_harness_authorization(
        authorized_action="REVIEW",
        subject="capability:security.review.repository",
        harness_decision_id="route-review-123",
        execution_id="mission-review:task-review",
        lineage={
            "goal_id": "goal-review",
            "mission_id": "mission-review",
            "task_id": "task-review",
            "routing_id": "route-review-123",
            "candidate_sha": candidate,
            "candidate_tree_sha": tree,
            "reviewed_diff_sha256": diff,
        },
    )
    consume_harness_authorization(review_auth)
    receipt = SecurityReviewReceipt.create(
        reviewed_candidate_sha=candidate,
        reviewed_tree_sha=tree,
        reviewed_diff_sha256=diff,
        reviewer_identity="independent-reviewer",
        reviewer_session="separate-review-session",
        reviewer_authorization=review_auth.authorization_id,
        scanner_evidence=("codeql:pass", "ci:pass"),
        findings=() if disposition == "PASS" else ("finding-1",),
        exceptions=(),
        disposition=disposition,
    )
    return repo, base, candidate, tree, diff, review_auth, receipt


def issue(repo, base, candidate, review_auth, receipt):
    return issue_exact_canonical_promotion_authorization(
        repository_root=repo,
        target_ref=WORK_REF,
        staging_ref=STAGING_REF,
        expected_old_oid=base,
        expected_candidate_sha=candidate,
        security_review_receipt=receipt,
        reviewer_authorization_id=review_auth.authorization_id,
        goal_id="goal-promote",
        mission_id="mission-promote",
        task_id="task-promote",
    )


def test_issuer_does_not_accept_caller_supplied_authority_provenance():
    params = inspect.signature(issue_exact_canonical_promotion_authorization).parameters
    assert "lineage" not in params
    assert "harness_decision_id" not in params
    assert "execution_id" not in params
    assert "authorization_id" not in params


def test_exact_promotion_authorization_routes_and_binds_git_and_review(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    auth = issue(repo, base, candidate, review_auth, receipt)
    assert auth.authorized_action == "DEVELOPMENT"
    assert auth.subject == "development.canonical.promote"
    assert auth.issued_by == "deepseek_harness"
    assert auth.status == "active"
    assert auth.harness_decision_id == auth.lineage["routing_id"]
    assert auth.lineage["capability_id"] == CAPABILITY_ID
    assert auth.lineage["target_ref"] == WORK_REF
    assert auth.lineage["expected_old_oid"] == base
    assert auth.lineage["candidate_sha"] == candidate
    assert auth.lineage["candidate_tree_sha"] == tree
    assert auth.lineage["reviewed_diff_sha256"] == diff
    assert auth.lineage["security_review_receipt_sha256"] == receipt.content_sha256
    assert auth.lineage["reviewer_authorization_id"] == review_auth.authorization_id
    assert auth.lineage["goal_id"] == "goal-promote"
    assert auth.lineage["mission_id"] == "mission-promote"
    assert auth.lineage["task_id"] == "task-promote"
    persisted = resolve_harness_authorization(auth.authorization_id)
    assert persisted.authorization_id == auth.authorization_id


def test_promotion_authorization_requires_consumed_exact_review_auth(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    from app.database.harness_authorization_repository import update_harness_authorization_status
    update_harness_authorization_status(review_auth.authorization_id, "revoked")
    with pytest.raises(PermissionError):
        issue(repo, base, candidate, review_auth, receipt)


def test_promotion_authorization_rejects_block_receipt(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(
        monkeypatch, tmp_path, disposition="BLOCK"
    )
    with pytest.raises(PermissionError, match="SECURITY_REVIEW_NOT_PASS"):
        issue(repo, base, candidate, review_auth, receipt)


def test_promotion_authorization_rejects_remote_cas_or_candidate_drift(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(promotion_authority, "_trusted_control_identity", lambda: ("f" * 40, True))
    with pytest.raises(PermissionError, match="CANONICAL_PROMOTION_CAS_MISMATCH"):
        issue_exact_canonical_promotion_authorization(
            repository_root=repo,
            target_ref=WORK_REF,
            staging_ref=STAGING_REF,
            expected_old_oid="f" * 40,
            expected_candidate_sha=candidate,
            security_review_receipt=receipt,
            reviewer_authorization_id=review_auth.authorization_id,
            goal_id="goal-promote", mission_id="mission-promote", task_id="task-promote",
        )
    monkeypatch.setattr(promotion_authority, "_trusted_control_identity", lambda: (base, True))
    with pytest.raises(PermissionError, match="CANDIDATE_MISMATCH"):
        issue_exact_canonical_promotion_authorization(
            repository_root=repo,
            target_ref=WORK_REF,
            staging_ref=STAGING_REF,
            expected_old_oid=base,
            expected_candidate_sha="f" * 40,
            security_review_receipt=receipt,
            reviewer_authorization_id=review_auth.authorization_id,
            goal_id="goal-promote", mission_id="mission-promote", task_id="task-promote",
        )


def test_registry_promotion_authorizer_has_no_canonical_write_or_security_guardian_authority():
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    record = GLOBAL_CAPABILITY_REGISTRY.get(CAPABILITY_ID)
    assert record is not None
    assert record.allowed_actions == ("DEVELOPMENT",)
    assert record.authority == "NONE"
    assert record.routing_authority == "NONE"
    assert record.publication_authority == "NONE"
    assert record.default_write_scope == ()
    assert record.agent_id != "codex-security-reviewer"
    assert "canonical ref write" not in record.side_effects


def test_promotion_authorization_rejects_candidate_self_authorization_control_plane(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(
        promotion_authority,
        "_trusted_control_identity",
        lambda: (candidate, True),
    )
    with pytest.raises(PermissionError, match="TRUSTED_CONTROL_SHA_MISMATCH"):
        issue(repo, base, candidate, review_auth, receipt)


def test_promotion_authorization_rejects_dirty_trusted_control(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(
        promotion_authority,
        "_trusted_control_identity",
        lambda: (base, False),
    )
    with pytest.raises(PermissionError, match="TRUSTED_CONTROL_DIRTY"):
        issue(repo, base, candidate, review_auth, receipt)


def test_promotion_authorization_rejects_unpersisted_review_authorization(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    with pytest.raises(PermissionError, match="provenance was not found"):
        issue_exact_canonical_promotion_authorization(
            repository_root=repo,
            target_ref=WORK_REF,
            staging_ref=STAGING_REF,
            expected_old_oid=base,
            expected_candidate_sha=candidate,
            security_review_receipt=receipt,
            reviewer_authorization_id="fabricated-review-authorization-id",
            goal_id="goal-promote",
            mission_id="mission-promote",
            task_id="task-promote",
        )
