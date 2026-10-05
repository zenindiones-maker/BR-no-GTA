from __future__ import annotations

import inspect
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

import pytest

from app.database.schema import initialize_schema
from app.database.connection import get_connection
from app.database.agent_execution_lease_repository import (
    append_task_event,
    persist_lease,
    update_lease_status,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
    resolve_harness_authorization,
)
from app.services.agent_office.delegation import (
    DelegatedTaskLease,
    MANDATORY_FORBIDDEN_ACTIONS,
)
from app.services.security_guardian_service import SecurityReviewReceipt
from app.services.trusted_security_review_receipt_service import (
    issue_trusted_security_review_receipt,
    resolve_trusted_security_review_receipt,
)
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


def _persist_review_execution(
    *,
    review_auth,
    candidate: str,
    tree: str,
    diff: str,
    disposition: str = "PASS",
    decision: str = "PASS",
    delegation_id: str = "delegation:review-1",
    lease_authorization_id: str | None = None,
    reviewer_session_ref: str = "codex-session-review-1",
):
    lease = DelegatedTaskLease(
        mission_id="mission-review",
        task_id="task-review",
        goal_id="goal-review",
        harness_decision_id="route-review-123",
        authorization_id=lease_authorization_id or review_auth.authorization_id,
        delegation_id=delegation_id,
        agent_id="codex-independent-reviewer",
        capability_ids=("security.review.repository",),
        base_sha=candidate,
        allowed_paths=("app", "scripts", "tests"),
        allowed_tools=("git", "python"),
        allowed_actions=("read", "review"),
        forbidden_actions=tuple(sorted(MANDATORY_FORBIDDEN_ACTIONS)),
        input_artifact_refs=(),
        expected_outputs=("SecurityReviewReceipt/v1",),
        acceptance_criteria=("exact-bound independent review",),
        evidence_requirements=("ReviewIndependenceEvidence/v1",),
        time_budget_seconds=600,
        cost_budget=0.0,
        tool_call_budget=100,
        retry_budget=0,
        max_parallelism=1,
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        escalation_conditions=("finding",),
        owned_task_class="security-review",
        role="INDEPENDENT_REVIEWER",
        read_set=("app", "scripts", "tests"),
        write_set=(),
    )
    persist_lease(lease)
    update_lease_status(
        delegation_id,
        status="COMPLETED",
        result_ref=f"artifact://security-review/{delegation_id}",
        result_hash="e" * 64,
    )
    event_id = append_task_event(
        mission_id="mission-review",
        task_id="task-review",
        delegation_id=delegation_id,
        event_type="REVIEW_INDEPENDENCE_EVIDENCE",
        payload={
            "schema_version": "ReviewIndependenceEvidence/v1",
            "decision": decision,
            "candidate_sha": candidate,
            "candidate_tree_sha": tree,
            "reviewed_diff_sha256": diff,
            "reviewer_session_ref": reviewer_session_ref,
            "final_disposition": disposition,
        },
    )
    return issue_trusted_security_review_receipt(
        reviewer_authorization_id=review_auth.authorization_id,
        reviewer_delegation_id=delegation_id,
        review_independence_event_id=event_id,
    )


def _issue_review_auth(*, candidate: str, tree: str, diff: str, consumed: bool = True):
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
    if consumed:
        consume_harness_authorization(review_auth)
    return review_auth


def review_fixture(monkeypatch, tmp_path: Path, *, disposition: str = "PASS"):
    db = tmp_path / "auth.sqlite3"
    monkeypatch.setenv("BR_TEST_DATABASE", str(db))
    initialize_schema()
    repo, base, candidate, tree, diff = init_repo(tmp_path)
    monkeypatch.setattr(promotion_authority, "_trusted_control_identity", lambda: (base, True))
    review_auth = _issue_review_auth(candidate=candidate, tree=tree, diff=diff)
    receipt = _persist_review_execution(
        review_auth=review_auth,
        candidate=candidate,
        tree=tree,
        diff=diff,
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
        security_review_receipt_ref=receipt.receipt_ref,
        security_review_receipt_sha256=receipt.receipt_sha256,
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
    assert auth.lineage["security_review_receipt_ref"] == receipt.receipt_ref
    assert auth.lineage["security_review_receipt_sha256"] == receipt.receipt_sha256
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
            security_review_receipt_ref=receipt.receipt_ref,
            security_review_receipt_sha256=receipt.receipt_sha256,
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
            security_review_receipt_ref=receipt.receipt_ref,
            security_review_receipt_sha256=receipt.receipt_sha256,
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
            security_review_receipt_ref=receipt.receipt_ref,
            security_review_receipt_sha256=receipt.receipt_sha256,
            reviewer_authorization_id="fabricated-review-authorization-id",
            goal_id="goal-promote",
            mission_id="mission-promote",
            task_id="task-promote",
        )


def test_caller_created_security_review_mapping_cannot_authorize_promotion(monkeypatch, tmp_path: Path):
    from dataclasses import asdict
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    forged = asdict(receipt)
    with pytest.raises((PermissionError, TypeError), match="TRUSTED|receipt|unexpected|SECURITY_REVIEW"):
        issue_exact_canonical_promotion_authorization(
            repository_root=repo,
            target_ref=WORK_REF,
            staging_ref=STAGING_REF,
            expected_old_oid=base,
            expected_candidate_sha=candidate,
            security_review_receipt=forged,
            reviewer_authorization_id=review_auth.authorization_id,
            goal_id="goal-promote",
            mission_id="mission-promote",
            task_id="task-promote",
        )


def test_promotion_authorizer_requires_opaque_trusted_receipt_reference():
    params = inspect.signature(issue_exact_canonical_promotion_authorization).parameters
    assert "security_review_receipt" not in params
    assert "security_review_receipt_ref" in params
    assert "security_review_receipt_sha256" in params


def test_missing_trusted_receipt_record_is_rejected(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    with pytest.raises(PermissionError, match="RECEIPT_NOT_FOUND"):
        issue_exact_canonical_promotion_authorization(
            repository_root=repo,
            target_ref=WORK_REF,
            staging_ref=STAGING_REF,
            expected_old_oid=base,
            expected_candidate_sha=candidate,
            security_review_receipt_ref="trusted-security-review:missing",
            security_review_receipt_sha256="a" * 64,
            reviewer_authorization_id=review_auth.authorization_id,
            goal_id="goal-promote",
            mission_id="mission-promote",
            task_id="task-promote",
        )


@pytest.mark.parametrize(
    ("field", "other"),
    [
        ("candidate_sha", "f" * 40),
        ("candidate_tree_sha", "a" * 40),
        ("reviewed_diff_sha256", "b" * 64),
    ],
)
def test_receipt_lineage_must_match_consumed_review_authorization(monkeypatch, tmp_path: Path, field: str, other: str):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    with get_connection() as connection:
        connection.execute(
            f"UPDATE trusted_security_review_receipts SET {field}=? WHERE receipt_ref=?",
            (other, receipt.receipt_ref),
        )
        connection.commit()
    with pytest.raises(PermissionError):
        issue(repo, base, candidate, review_auth, receipt)


def test_active_nonconsumed_review_authorization_cannot_issue_trusted_receipt(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "auth.sqlite3"))
    initialize_schema()
    _repo, _base, candidate, tree, diff = init_repo(tmp_path)
    review_auth = _issue_review_auth(candidate=candidate, tree=tree, diff=diff, consumed=False)
    lease = DelegatedTaskLease(
        mission_id="mission-review", task_id="task-review", goal_id="goal-review",
        harness_decision_id="route-review-123", authorization_id=review_auth.authorization_id,
        delegation_id="delegation:active-review", agent_id="codex-independent-reviewer",
        capability_ids=("security.review.repository",), base_sha=candidate,
        allowed_paths=("app",), allowed_tools=("git",), allowed_actions=("read",),
        forbidden_actions=tuple(sorted(MANDATORY_FORBIDDEN_ACTIONS)), input_artifact_refs=(),
        expected_outputs=("SecurityReviewReceipt/v1",), acceptance_criteria=("review",),
        evidence_requirements=("ReviewIndependenceEvidence/v1",), time_budget_seconds=600,
        cost_budget=0.0, tool_call_budget=20, retry_budget=0, max_parallelism=1,
        expires_at=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),
        escalation_conditions=("finding",), owned_task_class="security-review",
        role="INDEPENDENT_REVIEWER", read_set=("app",), write_set=(),
    )
    persist_lease(lease)
    update_lease_status(
        lease.delegation_id, status="COMPLETED",
        result_ref="artifact://review/active", result_hash="e"*64,
    )
    event_id = append_task_event(
        mission_id="mission-review", task_id="task-review",
        delegation_id=lease.delegation_id, event_type="REVIEW_INDEPENDENCE_EVIDENCE",
        payload={
            "decision":"PASS", "candidate_sha":candidate, "candidate_tree_sha":tree,
            "reviewed_diff_sha256":diff, "reviewer_session_ref":"s1",
            "final_disposition":"PASS",
        },
    )
    with pytest.raises(PermissionError):
        issue_trusted_security_review_receipt(
            reviewer_authorization_id=review_auth.authorization_id,
            reviewer_delegation_id=lease.delegation_id,
            review_independence_event_id=event_id,
        )


def test_independence_fail_is_rejected_before_receipt_issuance(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "auth.sqlite3"))
    initialize_schema()
    _repo, _base, candidate, tree, diff = init_repo(tmp_path)
    review_auth = _issue_review_auth(candidate=candidate, tree=tree, diff=diff)
    with pytest.raises(PermissionError, match="INDEPENDENCE_NOT_PASS"):
        _persist_review_execution(
            review_auth=review_auth,
            candidate=candidate,
            tree=tree,
            diff=diff,
            decision="FAIL",
            delegation_id="delegation:independence-fail",
        )


def test_review_execution_authorization_mismatch_is_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "auth.sqlite3"))
    initialize_schema()
    _repo, _base, candidate, tree, diff = init_repo(tmp_path)
    review_auth = _issue_review_auth(candidate=candidate, tree=tree, diff=diff)
    with pytest.raises(PermissionError, match="EXECUTION_AUTH_MISMATCH"):
        _persist_review_execution(
            review_auth=review_auth,
            candidate=candidate,
            tree=tree,
            diff=diff,
            delegation_id="delegation:wrong-auth",
            lease_authorization_id="another-review-authorization",
        )


def test_task_result_digest_change_invalidates_trusted_receipt(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    update_lease_status(
        receipt.reviewer_execution_principal_ref,
        status="COMPLETED",
        result_ref=receipt.reviewed_task_result_ref,
        result_hash="a" * 64,
    )
    with pytest.raises(PermissionError, match="PRINCIPAL_DIGEST_MISMATCH|TASK_RESULT_DIGEST_MISMATCH"):
        issue(repo, base, candidate, review_auth, receipt)


def test_fabricated_reviewer_session_invalidates_trusted_receipt(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    event_id = int(receipt.review_independence_ref.split(":", 1)[1])
    with get_connection() as connection:
        row = connection.execute("SELECT payload FROM agent_execution_events WHERE id=?", (event_id,)).fetchone()
        import json
        payload = json.loads(row["payload"])
        payload["reviewer_session_ref"] = "fabricated-session"
        connection.execute(
            "UPDATE agent_execution_events SET payload=? WHERE id=?",
            (json.dumps(payload, sort_keys=True), event_id),
        )
        connection.commit()
    with pytest.raises(PermissionError, match="INDEPENDENCE_DIGEST_MISMATCH|SESSION_MISMATCH"):
        issue(repo, base, candidate, review_auth, receipt)


def test_fabricated_reviewer_principal_invalidates_trusted_receipt(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    with get_connection() as connection:
        connection.execute(
            "UPDATE agent_execution_leases SET agent_id=? WHERE delegation_id=?",
            ("fabricated-reviewer", receipt.reviewer_execution_principal_ref),
        )
        connection.commit()
    with pytest.raises(PermissionError, match="PRINCIPAL_DIGEST_MISMATCH"):
        issue(repo, base, candidate, review_auth, receipt)


def test_persisted_exact_real_trusted_receipt_is_resolvable(monkeypatch, tmp_path: Path):
    repo, base, candidate, tree, diff, review_auth, receipt = review_fixture(monkeypatch, tmp_path)
    resolved = resolve_trusted_security_review_receipt(receipt.receipt_ref, receipt.receipt_sha256)
    assert resolved == receipt
    auth = issue(repo, base, candidate, review_auth, receipt)
    assert auth.lineage["security_review_receipt_ref"] == receipt.receipt_ref
