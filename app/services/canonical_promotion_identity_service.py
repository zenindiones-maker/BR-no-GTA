from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

ALLOWED_CANONICAL_REFS = frozenset({
    "refs/heads/main",
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
                    "~DEFAULT_BRANCH",
                    "refs/heads/work/gate6f-analytics-learning",
                    "refs/heads/security-promotion-probe",
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
