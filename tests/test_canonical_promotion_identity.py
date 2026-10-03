from __future__ import annotations

from pathlib import Path
import os
import shlex
import subprocess

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


def test_canonical_promotion_request_accepts_only_development_canonical_ref():
    assert request().target_ref == WORK_REF
    with pytest.raises(ValueError, match="TARGET_REF_NOT_ALLOWED"):
        request(target_ref=MAIN_REF)
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
    pushes = [line for line in text.splitlines() if " push " in line]
    assert len(pushes) == 1
    flags = [part for part in shlex.split(pushes[0]) if part.startswith("-")]
    assert flags == ["-C", "--force-with-lease=${TARGET_REF}:${EXPECTED_OLD_OID}"]
    assert "force=true" not in text
    assert "validate_trusted_promotion_evidence_bundle" in text
    service = (ROOT / "app" / "services" / "canonical_promotion_identity_service.py").read_text(encoding="utf-8")
    assert 'PROMOTION_AUTHORIZATION_SUBJECT = "development.canonical.promote"' in service
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


def test_canonical_promotion_workflow_pins_official_github_ed25519_host_key():
    text = PROMOTION_WORKFLOW.read_text(encoding="utf-8")
    assert "ssh-keyscan" not in text
    assert "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" in text
    assert "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU" in text
    assert "StrictHostKeyChecking=yes" in text
    assert "refs/heads/main" not in text


def test_canonical_acceptance_ruleset_is_layered_without_deploy_key_bypass():
    from app.services.canonical_promotion_identity_service import canonical_acceptance_ruleset_payload
    payload = canonical_acceptance_ruleset_payload()
    assert payload["name"] == "BR canonical development acceptance"
    assert payload["target"] == "branch"
    assert payload["enforcement"] == "active"
    assert payload["bypass_actors"] == []
    assert payload["conditions"]["ref_name"]["include"] == [
        "refs/heads/work/gate6f-analytics-learning",
    ]
    rules = {rule["type"]: rule for rule in payload["rules"]}
    assert "deletion" in rules
    assert "non_fast_forward" in rules
    assert rules["required_status_checks"]["parameters"]["required_status_checks"] == [
        {"context": "Deterministic policy contracts"}
    ]
    assert rules["code_scanning"]["parameters"]["code_scanning_tools"] == [{
        "tool": "CodeQL",
        "alerts_threshold": "errors",
        "security_alerts_threshold": "high_or_higher",
    }]


# SECURITY-PROMOTION-TRUST-BOUNDARY-REGRESSIONS
def test_promotion_workflow_does_not_trust_dispatch_supplied_auth_or_review_receipt():
    workflow = PROMOTION_WORKFLOW.read_text(encoding="utf-8")
    assert "${{ inputs.security_review_receipt_sha256 }}" not in workflow
    assert "${{ inputs.harness_authorization_id }}" not in workflow
    assert "BR_CANONICAL_PROMOTION_EVIDENCE_BUNDLE_JSON" in workflow


def test_promotion_workflow_separates_untrusted_candidate_preflight_from_write_credential_job():
    workflow = PROMOTION_WORKFLOW.read_text(encoding="utf-8")
    assert "  preflight:" in workflow
    assert "  promote:" in workflow
    assert "needs: preflight" in workflow
    assert "path: trusted-control" in workflow
    assert "ref: ${{ inputs.staging_ref }}" not in workflow
    promote = workflow.split("  promote:", 1)[1]
    assert "BR_CANONICAL_PROMOTION_SSH_KEY" in promote
    assert "actions/checkout" not in promote
    assert "python " not in promote
    assert "candidate/" not in promote


def test_security_guardian_policy_runs_on_every_security_staging_push_without_path_filter():
    workflow = (ROOT / ".github" / "workflows" / "security-guardian-baseline.yml").read_text(encoding="utf-8")
    assert '      - "staging/security-*"' in workflow
    push_block = workflow.split("  push:", 1)[1].split("\npermissions:", 1)[0]
    assert "paths:" not in push_block
    assert "Deterministic policy contracts" in workflow


def _trusted_evidence_bundle():
    from app.services.security_guardian_service import SecurityReviewReceipt
    receipt = SecurityReviewReceipt.create(
        reviewed_candidate_sha=SHA_B,
        reviewed_tree_sha=TREE,
        reviewed_diff_sha256="e" * 64,
        reviewer_identity="codex-security-reviewer",
        reviewer_session="review-session",
        reviewer_authorization="review-auth-1",
        scanner_evidence=("codeql:pass", "root-suite:pass", "ci:pass"),
        findings=(),
        exceptions=(),
        disposition="PASS",
    )
    binding = {
        "target_ref": WORK_REF,
        "expected_old_oid": SHA_A,
        "candidate_sha": SHA_B,
        "candidate_tree_sha": TREE,
        "reviewed_diff_sha256": "e" * 64,
        "security_review_receipt_sha256": receipt.content_sha256,
    }
    return {
        "schema_version": "CanonicalPromotionEvidenceBundle/v1",
        "trusted_source": "GITHUB_REPOSITORY_SECRET",
        "promotion_authorization": {
            "authorization_id": "promote-auth-1",
            "authorized_action": "DEVELOPMENT",
            "subject": "development.canonical.promote",
            "issued_by": "deepseek_harness",
            "status": "active",
            "lineage": binding,
        },
        "reviewer_authorization": {
            "authorization_id": "review-auth-1",
            "authorized_action": "REVIEW",
            "subject": "capability:security.review.repository",
            "issued_by": "deepseek_harness",
            "status": "consumed",
            "lineage": {
                "candidate_sha": SHA_B,
                "candidate_tree_sha": TREE,
                "reviewed_diff_sha256": "e" * 64,
            },
        },
        "security_review_receipt": receipt.to_dict() if hasattr(receipt, "to_dict") else {
            "reviewed_candidate_sha": receipt.reviewed_candidate_sha,
            "reviewed_tree_sha": receipt.reviewed_tree_sha,
            "reviewed_diff_sha256": receipt.reviewed_diff_sha256,
            "reviewer_identity": receipt.reviewer_identity,
            "reviewer_session": receipt.reviewer_session,
            "reviewer_authorization": receipt.reviewer_authorization,
            "scanner_evidence": list(receipt.scanner_evidence),
            "findings": list(receipt.findings),
            "exceptions": list(receipt.exceptions),
            "final_disposition": receipt.final_disposition,
            "content_sha256": receipt.content_sha256,
            "schema_version": receipt.schema_version,
        },
    }


def test_trusted_promotion_evidence_bundle_binds_real_semantic_evidence():
    from app.services.canonical_promotion_identity_service import validate_trusted_promotion_evidence_bundle
    result = validate_trusted_promotion_evidence_bundle(
        _trusted_evidence_bundle(),
        target_ref=WORK_REF,
        expected_old_oid=SHA_A,
        candidate_sha=SHA_B,
        candidate_tree_sha=TREE,
        reviewed_diff_sha256="e" * 64,
    )
    assert result["harness_authorization_id"] == "promote-auth-1"
    assert result["security_review_disposition"] == "PASS"
    assert len(result["security_review_receipt_sha256"]) == 64


def test_trusted_promotion_evidence_bundle_rejects_caller_fabrication_and_binding_drift():
    from app.services.canonical_promotion_identity_service import validate_trusted_promotion_evidence_bundle
    forged = _trusted_evidence_bundle()
    forged["trusted_source"] = "WORKFLOW_DISPATCH_INPUT"
    with pytest.raises(PermissionError, match="TRUSTED_SOURCE"):
        validate_trusted_promotion_evidence_bundle(
            forged,
            target_ref=WORK_REF,
            expected_old_oid=SHA_A,
            candidate_sha=SHA_B,
            candidate_tree_sha=TREE,
            reviewed_diff_sha256="e" * 64,
        )
    drift = _trusted_evidence_bundle()
    drift["promotion_authorization"]["lineage"]["candidate_sha"] = "f" * 40
    with pytest.raises(PermissionError, match="LINEAGE"):
        validate_trusted_promotion_evidence_bundle(
            drift,
            target_ref=WORK_REF,
            expected_old_oid=SHA_A,
            candidate_sha=SHA_B,
            candidate_tree_sha=TREE,
            reviewed_diff_sha256="e" * 64,
        )


@pytest.mark.parametrize("race,non_fast_forward", [(False, False), (True, False), (False, True)])
def test_actual_promotion_update_rejects_remote_race_even_on_candidate_ancestry(
    tmp_path, race, non_fast_forward,
):
    """Run the workflow's actual update/readback shell against synthetic local Git."""
    repo = tmp_path / "objects"
    remote = tmp_path / "remote.git"
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")

    def git(*args, input=None):
        return subprocess.run(["git", *map(str, args)], input=input, text=True,
                              capture_output=True, check=True, env=env).stdout.strip()

    git("init", "--bare", repo)
    git("init", "--bare", remote)
    tree = git("-C", repo, "mktree", input="")
    a = git("-C", repo, "commit-tree", tree, "-m", "A")
    b = git("-C", repo, "commit-tree", tree, "-p", a, "-m", "B")
    c = git("-C", repo, "commit-tree", tree, "-p", b, "-m", "candidate")
    old, candidate = (b, a) if non_fast_forward else (a, c)
    # Seed all objects without performing any network operation.
    git("-C", repo, "push", remote, f"{c}:refs/heads/fixture")
    git("--git-dir", remote, "update-ref", WORK_REF, old)
    if race:
        git("-C", repo, "merge-base", "--is-ancestor", b, c)

    workflow = PROMOTION_WORKFLOW.read_text()
    update = workflow.split("  promote:", 1)[1].split(
        '          git -C "$repo" merge-base --is-ancestor', 1,
    )[1].split('          echo "CANONICAL_PROMOTION_REMOTE_READBACK=VERIFIED"', 1)[0]
    update = 'git -C "$repo" merge-base --is-ancestor' + update
    assert 'test "$before" = "$EXPECTED_OLD_OID"' in update
    if race:
        push = next(line for line in update.splitlines() if " push " in line)
        # Precisely after the immediate equality check, before the atomic update.
        update = update.replace(push, 'git --git-dir="$remote" update-ref "$TARGET_REF" '
                                '"$RACE_OID" "$EXPECTED_OLD_OID"\n' + push)
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + update], text=True, capture_output=True,
        env=dict(env, repo=str(repo), remote=str(remote), ssh_cmd="false",
                 TARGET_REF=WORK_REF, EXPECTED_OLD_OID=old, CANDIDATE_SHA=candidate,
                 CANDIDATE_TREE_SHA=tree, RACE_OID=b),
    )
    observed = git("--git-dir", remote, "rev-parse", WORK_REF)
    if race or non_fast_forward:
        assert result.returncode != 0
        assert observed == (b if race else old)
        if race:
            assert "stale info" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert observed == c
        assert git("--git-dir", remote, "rev-parse", f"{observed}^{{tree}}") == tree
