"""Structural bootstrap evidence contract; never an executor or authority source.

The separately reviewed external capsule must authenticate all inputs before use.
Do not import this candidate module to perform the first canonical installation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class BootstrapRequiredCheck:
    repository: str
    workflow_path: str
    name: str
    app_id: int
    run_id: int
    check_run_id: int
    head_sha: str

    def __post_init__(self) -> None:
        if (
            self.repository != "zenindiones-maker/BR-no-GTA"
            or self.workflow_path != ".github/workflows/security-guardian-baseline.yml"
            or self.name != "Deterministic policy contracts"
        ):
            raise ValueError("BOOTSTRAP_REQUIRED_CHECK_IDENTITY")
        for value in (self.app_id, self.run_id, self.check_run_id):
            if type(value) is not int or value <= 0:
                raise ValueError("BOOTSTRAP_REQUIRED_CHECK_ID")
        _hex(self.head_sha, 40)


def _hex(value: str, length: int) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        raise ValueError("BOOTSTRAP_EXACT_DIGEST_REQUIRED")


@dataclass(frozen=True)
class CanonicalBootstrapContract:
    target_ref: str
    expected_old_oid: str
    candidate_sha: str
    candidate_tree_sha: str
    reviewed_diff_sha256: str
    security_review_receipt_sha256: str
    harness_authorization_id: str
    required_check_identity: BootstrapRequiredCheck
    bootstrap_executor_sha256: str
    promotion_identity: str

    def __post_init__(self) -> None:
        if self.target_ref != "refs/heads/work/gate6f-analytics-learning":
            raise ValueError("BOOTSTRAP_TARGET_REF")
        for value in (self.expected_old_oid, self.candidate_sha, self.candidate_tree_sha):
            _hex(value, 40)
        for value in (self.reviewed_diff_sha256, self.security_review_receipt_sha256,
                      self.bootstrap_executor_sha256):
            _hex(value, 64)
        if self.expected_old_oid == self.candidate_sha:
            raise ValueError("BOOTSTRAP_NO_INSTALLATION")
        if not isinstance(self.harness_authorization_id, str) or not self.harness_authorization_id.strip():
            raise ValueError("BOOTSTRAP_AUTHORIZATION_REQUIRED")
        if not isinstance(self.required_check_identity, BootstrapRequiredCheck):
            raise ValueError("BOOTSTRAP_REQUIRED_CHECK_IDENTITY")
        if self.required_check_identity.head_sha != self.candidate_sha:
            raise ValueError("BOOTSTRAP_REQUIRED_CHECK_HEAD")
        if self.promotion_identity != "BR_CANONICAL_PROMOTION_DEPLOY_KEY_V1":
            raise ValueError("BOOTSTRAP_PROMOTION_IDENTITY")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": "CanonicalBootstrapContract/v1", **asdict(self)}

    @property
    def content_sha256(self) -> str:
        return sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False).encode("utf-8")).hexdigest()


def validate_bootstrap_evidence(
    contract: CanonicalBootstrapContract, evidence: Mapping[str, Any],
) -> None:
    """Check a completed receipt against an independently trusted contract.

    Equality is necessary, not proof of provenance. This function cannot issue
    authorization, authenticate GitHub responses, execute Git, or promote.
    """
    expected = {
        "schema_version": "CanonicalBootstrapEvidence/v1",
        "contract_sha256": contract.content_sha256,
        "binding": contract.to_dict(),
        "observed_remote_before": contract.expected_old_oid,
        "observed_remote_after": contract.candidate_sha,
        "observed_tree_after": contract.candidate_tree_sha,
        "required_check_conclusion": "success",
        "executor_retired": True,
        "authorization_consumed": True,
    }
    # Canonical JSON also rejects type substitutions such as 1 for true.
    if json.dumps(dict(evidence), sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise PermissionError("BOOTSTRAP_EVIDENCE_MISSING_OR_MISMATCHED")
