"""Synthetic contract fixtures only; none of these are execution evidence."""
from copy import deepcopy
from dataclasses import asdict, fields, replace
from pathlib import Path

import pytest

from app.services.canonical_bootstrap_contract import (
    BootstrapRequiredCheck, CanonicalBootstrapContract, validate_bootstrap_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


def contract():
    return CanonicalBootstrapContract(
        target_ref="refs/heads/work/gate6f-analytics-learning",
        expected_old_oid="a" * 40, candidate_sha="b" * 40, candidate_tree_sha="c" * 40,
        reviewed_diff_sha256="d" * 64, security_review_receipt_sha256="e" * 64,
        harness_authorization_id="synthetic-promotion-authorization",
        required_check_identity=BootstrapRequiredCheck(
            repository="zenindiones-maker/BR-no-GTA",
            workflow_path=".github/workflows/security-guardian-baseline.yml",
            name="Deterministic policy contracts", app_id=1, run_id=2, check_run_id=3,
            head_sha="b" * 40,
        ),
        bootstrap_executor_sha256="f" * 64,
        promotion_identity="BR_CANONICAL_PROMOTION_DEPLOY_KEY_V1",
    )


def evidence(c):
    return dict(
        schema_version="CanonicalBootstrapEvidence/v1", contract_sha256=c.content_sha256,
        binding=c.to_dict(), observed_remote_before=c.expected_old_oid,
        observed_remote_after=c.candidate_sha, observed_tree_after=c.candidate_tree_sha,
        required_check_conclusion="success", executor_retired=True,
        authorization_consumed=True,
    )


def test_permanent_workflow_is_post_bootstrap_only_with_trusted_canonical_code():
    text = (ROOT / ".github/workflows/canonical-promotion.yml").read_text()
    preflight, promote = text.split("  promote:", 1)
    assert "POST-BOOTSTRAP ONLY" in text
    assert "docs/security/CANONICAL_BOOTSTRAP_V1.md" in text
    assert "if: github.ref == 'refs/heads/work/gate6f-analytics-learning'" in preflight
    assert "ref: ${{ github.sha }}" in preflight
    assert "path: trusted-control" in preflight
    assert "BR_CANONICAL_PROMOTION_SSH_KEY" not in preflight
    assert "actions/checkout" not in promote
    assert "python " not in promote
    assert "canonical_bootstrap_contract" not in text


@pytest.mark.parametrize("field", [f.name for f in fields(CanonicalBootstrapContract)])
def test_every_bootstrap_binding_is_required_and_exact(field):
    c = contract()
    kwargs = {f.name: getattr(c, f.name) for f in fields(c)}
    del kwargs[field]
    with pytest.raises(TypeError):
        CanonicalBootstrapContract(**kwargs)
    for replacement in (None, "changed"):
        altered = evidence(c)
        altered["binding"][field] = replacement
        with pytest.raises(PermissionError):
            validate_bootstrap_evidence(c, altered)
    missing = evidence(c)
    del missing["binding"][field]
    with pytest.raises(PermissionError):
        validate_bootstrap_evidence(c, missing)


@pytest.mark.parametrize("field", list(evidence(contract())))
def test_all_completion_evidence_is_mandatory_and_exact(field):
    c = contract()
    good = evidence(c)
    validate_bootstrap_evidence(c, good)
    for missing in (True, False):
        bad = deepcopy(good)
        if missing:
            del bad[field]
        else:
            bad[field] = "wrong"
        with pytest.raises(PermissionError):
            validate_bootstrap_evidence(c, bad)


@pytest.mark.parametrize("field", [f.name for f in fields(BootstrapRequiredCheck)])
def test_required_check_provenance_is_exact_bound(field):
    c = contract()
    bad = evidence(c)
    bad["binding"]["required_check_identity"][field] = "substituted"
    with pytest.raises(PermissionError):
        validate_bootstrap_evidence(c, bad)
    kwargs = asdict(c.required_check_identity)
    del kwargs[field]
    with pytest.raises(TypeError):
        BootstrapRequiredCheck(**kwargs)


def test_bootstrap_rejects_unbound_check_and_invalid_digests():
    c = contract()
    with pytest.raises(ValueError, match="CHECK_HEAD"):
        replace(c, required_check_identity=replace(c.required_check_identity, head_sha="a" * 40))
    for name in ("candidate_sha", "candidate_tree_sha", "expected_old_oid",
                 "reviewed_diff_sha256", "security_review_receipt_sha256",
                 "bootstrap_executor_sha256"):
        with pytest.raises(ValueError):
            replace(c, **{name: "short"})
    for name, value in (("target_ref", "refs/heads/main"),
                        ("promotion_identity", "security-guardian"),
                        ("harness_authorization_id", "")):
        with pytest.raises(ValueError):
            replace(c, **{name: value})
    assert replace(c, bootstrap_executor_sha256="1" * 64).content_sha256 != c.content_sha256
    bad = evidence(c)
    bad["executor_retired"] = 1
    with pytest.raises(PermissionError):
        validate_bootstrap_evidence(c, bad)
