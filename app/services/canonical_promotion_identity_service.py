from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

ALLOWED_CANONICAL_REFS = frozenset({
    "refs/heads/work/gate6f-analytics-learning",
})
PROMOTION_AUTHORIZATION_SUBJECT = "development.canonical.promote"
PROMOTION_AUTHORIZATION_ACTION = "DEVELOPMENT"
PROMOTION_IDENTITY = "BR_CANONICAL_PROMOTION_DEPLOY_KEY_V1"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _digest(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _sha40(value: str, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _HEX40.fullmatch(text):
        raise ValueError(f"{field} must be an exact 40-hex git object id")
    return text


def _sha64(value: str, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _HEX64.fullmatch(text):
        raise ValueError(f"{field} must be an exact 64-hex sha256 digest")
    return text


@dataclass(frozen=True)
class CanonicalPromotionRequest:
    target_ref: str
    expected_old_oid: str
    candidate_sha: str
    candidate_tree_sha: str
    security_review_receipt_sha256: str
    harness_authorization_id: str
    staging_ref: str
    content_sha256: str
    schema_version: str = "CanonicalPromotionRequest/v1"

    @classmethod
    def create(
        cls,
        *,
        target_ref: str,
        expected_old_oid: str,
        candidate_sha: str,
        candidate_tree_sha: str,
        security_review_receipt_sha256: str,
        harness_authorization_id: str,
        staging_ref: str,
    ) -> "CanonicalPromotionRequest":
        target = str(target_ref or "").strip()
        if target not in ALLOWED_CANONICAL_REFS:
            raise ValueError(f"TARGET_REF_NOT_ALLOWED:{target}")
        staging = str(staging_ref or "").strip()
        if not staging.startswith("refs/heads/staging/"):
            raise ValueError("STAGING_REF_NOT_ALLOWED")
        authorization = str(harness_authorization_id or "").strip()
        if not authorization:
            raise ValueError("harness_authorization_id is required")
        logical = {
            "schema_version": "CanonicalPromotionRequest/v1",
            "target_ref": target,
            "expected_old_oid": _sha40(expected_old_oid, "expected_old_oid"),
            "candidate_sha": _sha40(candidate_sha, "candidate_sha"),
            "candidate_tree_sha": _sha40(candidate_tree_sha, "candidate_tree_sha"),
            "security_review_receipt_sha256": _sha64(
                security_review_receipt_sha256,
                "security_review_receipt_sha256",
            ),
            "harness_authorization_id": authorization,
            "staging_ref": staging,
        }
        return cls(
            target_ref=logical["target_ref"],
            expected_old_oid=logical["expected_old_oid"],
            candidate_sha=logical["candidate_sha"],
            candidate_tree_sha=logical["candidate_tree_sha"],
            security_review_receipt_sha256=logical["security_review_receipt_sha256"],
            harness_authorization_id=logical["harness_authorization_id"],
            staging_ref=logical["staging_ref"],
            content_sha256=_digest(logical),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalPromotionReceipt:
    request_sha256: str
    target_ref: str
    expected_old_oid: str
    candidate_sha: str
    candidate_tree_sha: str
    observed_remote_before: str
    observed_remote_after: str
    observed_tree_after: str
    promotion_identity: str
    ruleset_id: str
    disposition: str
    content_sha256: str
    schema_version: str = "CanonicalPromotionReceipt/v1"

    @classmethod
    def create(
        cls,
        *,
        request: CanonicalPromotionRequest,
        observed_remote_before: str,
        observed_remote_after: str,
        observed_tree_after: str,
        promotion_identity: str,
        ruleset_id: str,
        disposition: str,
    ) -> "CanonicalPromotionReceipt":
        before = _sha40(observed_remote_before, "observed_remote_before")
        after = _sha40(observed_remote_after, "observed_remote_after")
        tree = _sha40(observed_tree_after, "observed_tree_after")
        state = str(disposition or "").strip().upper()
        if state not in {"PROMOTED", "NOOP_ALREADY_AT_CANDIDATE"}:
            raise ValueError("invalid canonical promotion disposition")
        if before != request.expected_old_oid:
            raise ValueError("receipt old oid does not bind request")
        if after != request.candidate_sha:
            raise ValueError("receipt remote after does not bind candidate")
        if tree != request.candidate_tree_sha:
            raise ValueError("receipt tree does not bind candidate tree")
        logical = {
            "schema_version": "CanonicalPromotionReceipt/v1",
            "request_sha256": request.content_sha256,
            "target_ref": request.target_ref,
            "expected_old_oid": request.expected_old_oid,
            "candidate_sha": request.candidate_sha,
            "candidate_tree_sha": request.candidate_tree_sha,
            "observed_remote_before": before,
            "observed_remote_after": after,
            "observed_tree_after": tree,
            "promotion_identity": str(promotion_identity),
            "ruleset_id": str(ruleset_id),
            "disposition": state,
        }
        return cls(
            request_sha256=logical["request_sha256"],
            target_ref=logical["target_ref"],
            expected_old_oid=logical["expected_old_oid"],
            candidate_sha=logical["candidate_sha"],
            candidate_tree_sha=logical["candidate_tree_sha"],
            observed_remote_before=logical["observed_remote_before"],
            observed_remote_after=logical["observed_remote_after"],
            observed_tree_after=logical["observed_tree_after"],
            promotion_identity=logical["promotion_identity"],
            ruleset_id=logical["ruleset_id"],
            disposition=logical["disposition"],
            content_sha256=_digest(logical),
        )


def validate_canonical_promotion_request(
    request: CanonicalPromotionRequest,
    *,
    observed_remote_oid: str,
    observed_candidate_sha: str,
    observed_candidate_tree_sha: str,
    candidate_is_descendant_of_expected_old: bool,
    security_review_disposition: str,
    authorization_subject: str,
    authorization_action: str,
) -> dict[str, Any]:
    remote = _sha40(observed_remote_oid, "observed_remote_oid")
    candidate = _sha40(observed_candidate_sha, "observed_candidate_sha")
    tree = _sha40(observed_candidate_tree_sha, "observed_candidate_tree_sha")

    if remote != request.expected_old_oid:
        raise PermissionError(
            f"CANONICAL_PROMOTION_CAS_MISMATCH:expected={request.expected_old_oid}:observed={remote}"
        )
    if candidate != request.candidate_sha:
        raise PermissionError("CANONICAL_PROMOTION_CANDIDATE_MISMATCH")
    if tree != request.candidate_tree_sha:
        raise PermissionError("CANONICAL_PROMOTION_TREE_MISMATCH")
    if not candidate_is_descendant_of_expected_old:
        raise PermissionError("CANONICAL_PROMOTION_NON_FAST_FORWARD")
    if str(security_review_disposition).upper() not in {"PASS", "PASS_WITH_ACCEPTED_RISK"}:
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_NOT_PASS")
    if str(authorization_subject) != PROMOTION_AUTHORIZATION_SUBJECT:
        raise PermissionError("CANONICAL_PROMOTION_HARNESS_AUTHORIZATION_SUBJECT_MISMATCH")
    if str(authorization_action).upper() != PROMOTION_AUTHORIZATION_ACTION:
        raise PermissionError("CANONICAL_PROMOTION_HARNESS_AUTHORIZATION_ACTION_MISMATCH")

    return {
        "schema_version": "CanonicalPromotionValidation/v1",
        "decision": "PASS",
        "target_ref": request.target_ref,
        "expected_old_oid": request.expected_old_oid,
        "candidate_sha": request.candidate_sha,
        "candidate_tree_sha": request.candidate_tree_sha,
        "request_sha256": request.content_sha256,
        "fast_forward_only": True,
        "force": False,
    }



TRUSTED_PROMOTION_EVIDENCE_SOURCE = "GITHUB_REPOSITORY_SECRET"
REVIEW_AUTHORIZATION_SUBJECT = "capability:security.review.repository"


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PermissionError(f"CANONICAL_PROMOTION_{field.upper()}_MISSING")
    return value


def _validate_authorization_record(
    value: Mapping[str, Any],
    *,
    expected_action: str,
    expected_subject: str,
    allowed_statuses: frozenset[str],
    field: str,
) -> Mapping[str, Any]:
    authorization_id = str(value.get("authorization_id") or "").strip()
    if not authorization_id:
        raise PermissionError(f"CANONICAL_PROMOTION_{field.upper()}_ID_MISSING")
    if str(value.get("issued_by") or "") != "deepseek_harness":
        raise PermissionError(f"CANONICAL_PROMOTION_{field.upper()}_ISSUER_MISMATCH")
    if str(value.get("authorized_action") or "").strip().upper() != expected_action:
        raise PermissionError(f"CANONICAL_PROMOTION_{field.upper()}_ACTION_MISMATCH")
    if str(value.get("subject") or "").strip() != expected_subject:
        raise PermissionError(f"CANONICAL_PROMOTION_{field.upper()}_SUBJECT_MISMATCH")
    if str(value.get("status") or "").strip().lower() not in allowed_statuses:
        raise PermissionError(f"CANONICAL_PROMOTION_{field.upper()}_STATUS_INVALID")
    return value


def validate_trusted_promotion_evidence_bundle(
    bundle: Mapping[str, Any],
    *,
    target_ref: str,
    expected_old_oid: str,
    candidate_sha: str,
    candidate_tree_sha: str,
    reviewed_diff_sha256: str,
) -> dict[str, Any]:
    """Validate evidence delivered through the trusted canonical-workflow boundary."""
    if str(bundle.get("schema_version") or "") != "CanonicalPromotionEvidenceBundle/v1":
        raise PermissionError("CANONICAL_PROMOTION_EVIDENCE_SCHEMA_MISMATCH")
    if str(bundle.get("trusted_source") or "") != TRUSTED_PROMOTION_EVIDENCE_SOURCE:
        raise PermissionError("CANONICAL_PROMOTION_TRUSTED_SOURCE_MISMATCH")

    target = str(target_ref or "").strip()
    if target not in ALLOWED_CANONICAL_REFS:
        raise PermissionError("CANONICAL_PROMOTION_TARGET_REF_MISMATCH")
    expected_old = _sha40(expected_old_oid, "expected_old_oid")
    candidate = _sha40(candidate_sha, "candidate_sha")
    tree = _sha40(candidate_tree_sha, "candidate_tree_sha")
    diff_sha = _sha64(reviewed_diff_sha256, "reviewed_diff_sha256")

    receipt_raw = _require_mapping(bundle.get("security_review_receipt"), "security_review_receipt")
    if str(receipt_raw.get("schema_version") or "") != "SecurityReviewReceipt/v1":
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_SCHEMA_MISMATCH")

    from app.services.security_guardian_service import SecurityReviewReceipt

    receipt = SecurityReviewReceipt.create(
        reviewed_candidate_sha=str(receipt_raw.get("reviewed_candidate_sha") or ""),
        reviewed_tree_sha=str(receipt_raw.get("reviewed_tree_sha") or ""),
        reviewed_diff_sha256=str(receipt_raw.get("reviewed_diff_sha256") or ""),
        reviewer_identity=str(receipt_raw.get("reviewer_identity") or ""),
        reviewer_session=str(receipt_raw.get("reviewer_session") or ""),
        reviewer_authorization=str(receipt_raw.get("reviewer_authorization") or ""),
        scanner_evidence=tuple(receipt_raw.get("scanner_evidence") or ()),
        findings=tuple(receipt_raw.get("findings") or ()),
        exceptions=tuple(receipt_raw.get("exceptions") or ()),
        disposition=str(receipt_raw.get("final_disposition") or ""),
    )
    supplied_receipt_digest = _sha64(
        str(receipt_raw.get("content_sha256") or ""),
        "security_review_receipt.content_sha256",
    )
    if supplied_receipt_digest != receipt.content_sha256:
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_DIGEST_MISMATCH")
    if receipt.reviewed_candidate_sha != candidate:
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_CANDIDATE_MISMATCH")
    if receipt.reviewed_tree_sha != tree:
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_TREE_MISMATCH")
    if receipt.reviewed_diff_sha256 != diff_sha:
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_DIFF_MISMATCH")
    if receipt.final_disposition not in {"PASS", "PASS_WITH_ACCEPTED_RISK"}:
        raise PermissionError("CANONICAL_PROMOTION_SECURITY_REVIEW_NOT_PASS")

    review_auth = _validate_authorization_record(
        _require_mapping(bundle.get("reviewer_authorization"), "reviewer_authorization"),
        expected_action="REVIEW",
        expected_subject=REVIEW_AUTHORIZATION_SUBJECT,
        allowed_statuses=frozenset({"active", "consumed"}),
        field="reviewer_authorization",
    )
    if str(review_auth.get("authorization_id")) != receipt.reviewer_authorization:
        raise PermissionError("CANONICAL_PROMOTION_REVIEWER_AUTHORIZATION_RECEIPT_MISMATCH")
    review_lineage = _require_mapping(review_auth.get("lineage"), "reviewer_authorization_lineage")
    for key, expected in {
        "candidate_sha": candidate,
        "candidate_tree_sha": tree,
        "reviewed_diff_sha256": diff_sha,
    }.items():
        if str(review_lineage.get(key) or "").lower() != expected:
            raise PermissionError(f"CANONICAL_PROMOTION_REVIEWER_LINEAGE_{key.upper()}_MISMATCH")

    promotion_auth = _validate_authorization_record(
        _require_mapping(bundle.get("promotion_authorization"), "promotion_authorization"),
        expected_action=PROMOTION_AUTHORIZATION_ACTION,
        expected_subject=PROMOTION_AUTHORIZATION_SUBJECT,
        allowed_statuses=frozenset({"active"}),
        field="promotion_authorization",
    )
    promotion_lineage = _require_mapping(
        promotion_auth.get("lineage"), "promotion_authorization_lineage"
    )
    required_lineage = {
        "target_ref": target,
        "expected_old_oid": expected_old,
        "candidate_sha": candidate,
        "candidate_tree_sha": tree,
        "reviewed_diff_sha256": diff_sha,
        "security_review_receipt_sha256": receipt.content_sha256,
    }
    for key, expected in required_lineage.items():
        observed = str(promotion_lineage.get(key) or "")
        if key != "target_ref":
            observed = observed.lower()
        if observed != expected:
            raise PermissionError(f"CANONICAL_PROMOTION_LINEAGE_{key.upper()}_MISMATCH")

    return {
        "schema_version": "CanonicalPromotionTrustedEvidenceValidation/v1",
        "trusted_source": TRUSTED_PROMOTION_EVIDENCE_SOURCE,
        "harness_authorization_id": str(promotion_auth["authorization_id"]),
        "authorization_subject": str(promotion_auth["subject"]),
        "authorization_action": str(promotion_auth["authorized_action"]).upper(),
        "security_review_receipt_sha256": receipt.content_sha256,
        "security_review_disposition": receipt.final_disposition,
        "reviewer_authorization_id": str(review_auth["authorization_id"]),
        "candidate_sha": candidate,
        "candidate_tree_sha": tree,
        "reviewed_diff_sha256": diff_sha,
    }


def canonical_promotion_ruleset_payload() -> dict[str, Any]:
    return {
        "name": "BR canonical promotion identity",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [
            {
                "actor_id": None,
                "actor_type": "DeployKey",
                "bypass_mode": "always",
            }
        ],
        "conditions": {
            "ref_name": {
                "include": [
                    "refs/heads/work/gate6f-analytics-learning",
                ],
                "exclude": [],
            }
        },
        "rules": [
            {"type": "creation"},
            {"type": "update"},
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def canonical_acceptance_ruleset_payload() -> dict[str, Any]:
    return {
        "name": "BR canonical development acceptance",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {
                "include": ["refs/heads/work/gate6f-analytics-learning"],
                "exclude": [],
            }
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": "Deterministic policy contracts"},
                    ],
                    "strict_required_status_checks_policy": False,
                },
            },
            {
                "type": "code_scanning",
                "parameters": {
                    "code_scanning_tools": [
                        {
                            "tool": "CodeQL",
                            "alerts_threshold": "errors",
                            "security_alerts_threshold": "high_or_higher",
                        }
                    ]
                },
            },
        ],
    }
