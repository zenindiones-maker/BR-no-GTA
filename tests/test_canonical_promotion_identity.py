from __future__ import annotations

from pathlib import Path

import pytest

from app.services.canonical_promotion_identity_service import (
    CanonicalPromotionRequest,
    CanonicalPromotionReceipt,
    validate_canonical_promotion_request,
)

ROOT = Path(__file__).resolve().parents[1]
PROMOTION_WORKFLOW = ROOT / ".github" / "workflows" / "canonical-promotion.yml"
RUN001_BOOTSTRAP = ROOT / ".github" / "workflows" / "run001-bootstrap.yml"
RUN001_EXECUTOR = ROOT / ".github" / "workflows" / "run001-final-products-executor.yml"

WORK_REF = "refs/heads/work/gate6f-analytics-learning"
MAIN_REF = "refs/heads/main"
SHA_A = "a" * 40
SHA_B = "b" * 40
TREE = "c" * 40
SECURITY = "d" * 64


def request(**overrides):
    data = dict(
        target_ref=WORK_REF,
        expected_old_oid=SHA_A,
        candidate_sha=SHA_B,
        candidate_tree_sha=TREE,
        security_review_receipt_sha256=SECURITY,
        harness_authorization_id="auth-123",
        staging_ref="refs/heads/staging/security-guardian-foundation-v1",
    )
    data.update(overrides)
    return CanonicalPromotionRequest.create(**data)


def test_canonical_promotion_request_accepts_only_canonical_refs():
    assert request().target_ref == WORK_REF
    assert request(target_ref=MAIN_REF).target_ref == MAIN_REF
    with pytest.raises(ValueError, match="TARGET_REF_NOT_ALLOWED"):
        request(target_ref="refs/heads/staging/security-guardian-foundation-v1")


def test_canonical_promotion_request_binds_old_oid_candidate_tree_and_security_receipt():
    r = request()
    assert r.expected_old_oid == SHA_A
    assert r.candidate_sha == SHA_B
    assert r.candidate_tree_sha == TREE
    assert r.security_review_receipt_sha256 == SECURITY
    assert len(r.content_sha256) == 64


@pytest.mark.parametrize("field,value", [
    ("expected_old_oid", "main"),
    ("candidate_sha", "deadbeef"),
    ("candidate_tree_sha", "x" * 40),
    ("security_review_receipt_sha256", "a" * 63),
])
def test_canonical_promotion_request_rejects_unbound_or_noncanonical_digests(field, value):
    with pytest.raises(ValueError):
        request(**{field: value})


def test_validator_requires_exact_remote_old_oid_candidate_sha_tree_and_fast_forward():
    r = request()
    result = validate_canonical_promotion_request(
        r,
        observed_remote_oid=SHA_A,
        observed_candidate_sha=SHA_B,
        observed_candidate_tree_sha=TREE,
        candidate_is_descendant_of_expected_old=True,
        security_review_disposition="PASS",
        authorization_subject="development.canonical.promote",
        authorization_action="DEVELOPMENT",
    )
    assert result["decision"] == "PASS"
    assert result["force"] is False
    assert result["fast_forward_only"] is True


def test_validator_fails_closed_on_stale_remote_or_tree_drift():
    r = request()
    with pytest.raises(PermissionError, match="CANONICAL_PROMOTION_CAS_MISMATCH"):
        validate_canonical_promotion_request(
            r,
            observed_remote_oid="e" * 40,
            observed_candidate_sha=SHA_B,
            observed_candidate_tree_sha=TREE,
            candidate_is_descendant_of_expected_old=True,
            security_review_disposition="PASS",
            authorization_subject="development.canonical.promote",
            authorization_action="DEVELOPMENT",
        )
    with pytest.raises(PermissionError, match="CANONICAL_PROMOTION_TREE_MISMATCH"):
        validate_canonical_promotion_request(
            r,
            observed_remote_oid=SHA_A,
            observed_candidate_sha=SHA_B,
            observed_candidate_tree_sha="e" * 40,
            candidate_is_descendant_of_expected_old=True,
            security_review_disposition="PASS",
            authorization_subject="development.canonical.promote",
            authorization_action="DEVELOPMENT",
        )


def test_validator_rejects_non_fast_forward_security_fail_and_wrong_harness_subject():
    r = request()
    base = dict(
        observed_remote_oid=SHA_A,
        observed_candidate_sha=SHA_B,
        observed_candidate_tree_sha=TREE,
        candidate_is_descendant_of_expected_old=True,
        security_review_disposition="PASS",
        authorization_subject="development.canonical.promote",
        authorization_action="DEVELOPMENT",
    )
    for key, value, marker in (
        ("candidate_is_descendant_of_expected_old", False, "NON_FAST_FORWARD"),
        ("security_review_disposition", "BLOCK", "SECURITY_REVIEW_NOT_PASS"),
        ("authorization_subject", "security.review.repository", "HARNESS_AUTHORIZATION_SUBJECT_MISMATCH"),
    ):
        payload = dict(base)
        payload[key] = value
        with pytest.raises(PermissionError, match=marker):
            validate_canonical_promotion_request(r, **payload)


def test_promotion_receipt_binds_remote_readback():
    receipt = CanonicalPromotionReceipt.create(
        request=request(),
        observed_remote_before=SHA_A,
        observed_remote_after=SHA_B,
        observed_tree_after=TREE,
        promotion_identity="BR_CANONICAL_PROMOTION_DEPLOY_KEY_V1",
        ruleset_id="123",
        disposition="PROMOTED",
    )
    assert receipt.observed_remote_after == SHA_B
    assert receipt.observed_tree_after == TREE
    assert receipt.disposition == "PROMOTED"
    assert len(receipt.content_sha256) == 64


def test_canonical_promotion_workflow_is_narrow_and_credential_isolated():
    text = PROMOTION_WORKFLOW.read_text(encoding="utf-8")
    assert "permissions: {}" in text
    assert "contents: write" not in text
    assert "write-all" not in text
    assert "persist-credentials: false" in text
    assert "environment: canonical-promotion" in text
    assert "BR_CANONICAL_PROMOTION_SSH_KEY" in text
    assert "StrictHostKeyChecking=no" not in text
    assert "--force" not in text
    assert "force=true" not in text
    assert "development.canonical.promote" in text
    assert "expected_old_oid" in text
    assert "candidate_sha" in text
    assert "candidate_tree_sha" in text
    assert "security_review_receipt_sha256" in text
    assert "if: always()" in text
    assert "rm -f" in text


def test_legacy_run001_workflows_no_longer_write_canonical_directly():
    dynamic_target = 'git push origin "HEAD:$' + '{TARGET_REF}"'
    for path in (RUN001_BOOTSTRAP, RUN001_EXECUTOR):
        text = path.read_text(encoding="utf-8")
        assert "git push origin HEAD:work/gate6f-analytics-learning" not in text
        assert dynamic_target not in text
        assert "persist-credentials: true" not in text
        assert "CANONICAL_PROMOTION_REQUIRED" in text


def test_security_guardian_itself_does_not_gain_promotion_authority():
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    record = GLOBAL_CAPABILITY_REGISTRY.get("security.review.repository")
    assert record is not None
    assert record.authority == "NONE"
    assert record.default_write_scope == ()
    assert "development.canonical.promote" not in record.allowed_actions


def test_final_ruleset_targets_only_canonical_branches_and_only_deploy_key_bypasses():
    from app.services.canonical_promotion_identity_service import canonical_promotion_ruleset_payload
    payload = canonical_promotion_ruleset_payload()
    assert payload["target"] == "branch"
    assert payload["enforcement"] == "active"
    assert payload["conditions"]["ref_name"]["include"] == [
        "~DEFAULT_BRANCH",
        "refs/heads/work/gate6f-analytics-learning",
    ]
    assert payload["conditions"]["ref_name"]["exclude"] == []
    assert payload["bypass_actors"] == [
        {"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "always"}
    ]
    assert {rule["type"] for rule in payload["rules"]} == {
        "creation", "update", "deletion", "non_fast_forward"
    }
    assert all(actor["actor_type"] not in {"User", "RepositoryRole", "OrganizationAdmin"}
               for actor in payload["bypass_actors"])
