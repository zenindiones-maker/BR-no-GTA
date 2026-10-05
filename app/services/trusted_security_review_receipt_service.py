from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from app.database.agent_execution_lease_repository import get_lease, get_task_event
from app.database.trusted_security_review_receipt_repository import (
    create_trusted_security_review_receipt,
    get_trusted_security_review_receipt,
)
from app.services.harness_authorization_service import validate_harness_authorization


REVIEW_SUBJECT = "capability:security.review.repository"
ISSUED_BY = "trusted_security_review_service"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _require_hex(value: Any, pattern: re.Pattern[str], field: str) -> str:
    text = str(value or "").strip().lower()
    if pattern.fullmatch(text) is None:
        raise PermissionError(f"TRUSTED_SECURITY_REVIEW_INVALID_{field.upper()}")
    return text


@dataclass(frozen=True)
class TrustedSecurityReviewReceiptRecord:
    receipt_ref: str
    receipt_sha256: str
    candidate_sha: str
    candidate_tree_sha: str
    reviewed_diff_sha256: str
    reviewer_authorization_id: str
    reviewer_authorization_status: str
    reviewer_execution_principal_ref: str
    reviewer_execution_principal_sha256: str
    review_independence_ref: str
    review_independence_sha256: str
    review_independence_decision: str
    reviewed_task_result_ref: str
    reviewed_task_result_sha256: str
    reviewer_session_ref: str
    final_disposition: str
    issued_by: str = ISSUED_BY
    schema_version: str = "TrustedSecurityReviewReceiptRecord/v1"

    @property
    def content_sha256(self) -> str:
        return self.receipt_sha256

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _principal_payload(lease: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "delegation_id": str(lease.get("delegation_id") or ""),
        "mission_id": str(lease.get("mission_id") or ""),
        "task_id": str(lease.get("task_id") or ""),
        "authorization_id": str(lease.get("authorization_id") or ""),
        "agent_id": str(lease.get("agent_id") or ""),
        "base_sha": str(lease.get("base_sha") or "").lower(),
        "status": str(lease.get("status") or ""),
    }


def _event_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(event["id"]),
        "mission_id": str(event.get("mission_id") or ""),
        "task_id": str(event.get("task_id") or ""),
        "delegation_id": str(event.get("delegation_id") or ""),
        "event_type": str(event.get("event_type") or ""),
        "payload": dict(event.get("payload") or {}),
        "created_at": str(event.get("created_at") or ""),
    }


def issue_trusted_security_review_receipt(
    *,
    reviewer_authorization_id: str,
    reviewer_delegation_id: str,
    review_independence_event_id: int,
) -> TrustedSecurityReviewReceiptRecord:
    review_auth = validate_harness_authorization(
        reviewer_authorization_id,
        expected_action="REVIEW",
        expected_subject=REVIEW_SUBJECT,
        allowed_statuses=("consumed",),
    )
    lineage = dict(review_auth.lineage or {})
    candidate = _require_hex(lineage.get("candidate_sha"), _HEX40, "candidate_sha")
    tree = _require_hex(lineage.get("candidate_tree_sha"), _HEX40, "candidate_tree_sha")
    diff = _require_hex(lineage.get("reviewed_diff_sha256"), _HEX64, "reviewed_diff_sha256")

    lease = get_lease(str(reviewer_delegation_id or "").strip())
    if lease is None:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_PRINCIPAL_NOT_FOUND")
    if str(lease.get("authorization_id") or "") != review_auth.authorization_id:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_AUTH_MISMATCH")
    if str(lease.get("status") or "") != "COMPLETED":
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_NOT_COMPLETED")
    if str(lease.get("mission_id") or "") != str(lineage.get("mission_id") or ""):
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_MISSION_MISMATCH")
    if str(lease.get("task_id") or "") != str(lineage.get("task_id") or ""):
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_TASK_MISMATCH")

    result_ref = str(lease.get("result_ref") or "").strip()
    result_hash = _require_hex(lease.get("result_hash"), _HEX64, "task_result_sha256")
    if not result_ref:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_TASK_RESULT_MISSING")

    event = get_task_event(int(review_independence_event_id))
    if event is None:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_INDEPENDENCE_NOT_FOUND")
    if str(event.get("delegation_id") or "") != str(lease.get("delegation_id") or ""):
        raise PermissionError("TRUSTED_SECURITY_REVIEW_INDEPENDENCE_EXECUTION_MISMATCH")
    if str(event.get("event_type") or "") != "REVIEW_INDEPENDENCE_EVIDENCE":
        raise PermissionError("TRUSTED_SECURITY_REVIEW_INDEPENDENCE_TYPE_MISMATCH")
    payload = dict(event.get("payload") or {})
    decision = str(payload.get("decision") or "").strip().upper()
    if decision != "PASS":
        raise PermissionError("TRUSTED_SECURITY_REVIEW_INDEPENDENCE_NOT_PASS")
    for key, expected in {
        "candidate_sha": candidate,
        "candidate_tree_sha": tree,
        "reviewed_diff_sha256": diff,
    }.items():
        if str(payload.get(key) or "").strip().lower() != expected:
            raise PermissionError(
                f"TRUSTED_SECURITY_REVIEW_INDEPENDENCE_{key.upper()}_MISMATCH"
            )

    reviewer_session_ref = str(payload.get("reviewer_session_ref") or "").strip()
    if not reviewer_session_ref:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_SESSION_MISSING")
    disposition = str(payload.get("final_disposition") or "").strip().upper()
    if disposition not in {"PASS", "BLOCK", "PASS_WITH_ACCEPTED_RISK"}:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_DISPOSITION_INVALID")

    principal_ref = str(lease["delegation_id"])
    principal_sha = _digest(_principal_payload(lease))
    independence_ref = f"agent_execution_event:{int(event['id'])}"
    independence_sha = _digest(_event_payload(event))

    seed = {
        "candidate_sha": candidate,
        "candidate_tree_sha": tree,
        "reviewed_diff_sha256": diff,
        "reviewer_authorization_id": review_auth.authorization_id,
        "reviewer_authorization_status": review_auth.status,
        "reviewer_execution_principal_ref": principal_ref,
        "reviewer_execution_principal_sha256": principal_sha,
        "review_independence_ref": independence_ref,
        "review_independence_sha256": independence_sha,
        "review_independence_decision": decision,
        "reviewed_task_result_ref": result_ref,
        "reviewed_task_result_sha256": result_hash,
        "reviewer_session_ref": reviewer_session_ref,
        "final_disposition": disposition,
        "issued_by": ISSUED_BY,
    }
    receipt_sha = _digest(seed)
    receipt_ref = f"trusted-security-review:{receipt_sha[:32]}"
    record = TrustedSecurityReviewReceiptRecord(
        receipt_ref=receipt_ref,
        receipt_sha256=receipt_sha,
        **seed,
    )
    create_trusted_security_review_receipt(record.to_dict())
    return record


def resolve_trusted_security_review_receipt(
    receipt_ref: str,
    receipt_sha256: str,
) -> TrustedSecurityReviewReceiptRecord:
    ref = str(receipt_ref or "").strip()
    supplied_digest = _require_hex(receipt_sha256, _HEX64, "receipt_sha256")
    raw = get_trusted_security_review_receipt(ref)
    if raw is None:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_RECEIPT_NOT_FOUND")

    fields = {
        name: raw.get(name)
        for name in TrustedSecurityReviewReceiptRecord.__dataclass_fields__
        if name not in {"schema_version"}
    }
    record = TrustedSecurityReviewReceiptRecord(**fields)
    if record.receipt_sha256 != supplied_digest:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_RECEIPT_DIGEST_MISMATCH")
    if record.issued_by != ISSUED_BY:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_ISSUER_MISMATCH")

    seed = {
        key: value
        for key, value in record.to_dict().items()
        if key not in {"receipt_ref", "receipt_sha256", "schema_version"}
    }
    if _digest(seed) != record.receipt_sha256:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_RECORD_INTEGRITY_MISMATCH")

    review_auth = validate_harness_authorization(
        record.reviewer_authorization_id,
        expected_action="REVIEW",
        expected_subject=REVIEW_SUBJECT,
        allowed_statuses=("consumed",),
    )
    if review_auth.status != record.reviewer_authorization_status:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_AUTH_STATUS_MISMATCH")
    lineage = dict(review_auth.lineage or {})
    for key, expected in {
        "candidate_sha": record.candidate_sha,
        "candidate_tree_sha": record.candidate_tree_sha,
        "reviewed_diff_sha256": record.reviewed_diff_sha256,
    }.items():
        if str(lineage.get(key) or "").strip().lower() != expected:
            raise PermissionError(
                f"TRUSTED_SECURITY_REVIEW_AUTH_{key.upper()}_MISMATCH"
            )

    lease = get_lease(record.reviewer_execution_principal_ref)
    if lease is None:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_PRINCIPAL_NOT_FOUND")
    if str(lease.get("authorization_id") or "") != record.reviewer_authorization_id:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_AUTH_MISMATCH")
    if _digest(_principal_payload(lease)) != record.reviewer_execution_principal_sha256:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_PRINCIPAL_DIGEST_MISMATCH")
    if str(lease.get("result_ref") or "") != record.reviewed_task_result_ref:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_TASK_RESULT_REF_MISMATCH")
    if str(lease.get("result_hash") or "").lower() != record.reviewed_task_result_sha256:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_TASK_RESULT_DIGEST_MISMATCH")

    prefix = "agent_execution_event:"
    if not record.review_independence_ref.startswith(prefix):
        raise PermissionError("TRUSTED_SECURITY_REVIEW_INDEPENDENCE_REF_INVALID")
    event = get_task_event(int(record.review_independence_ref[len(prefix):]))
    if event is None:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_INDEPENDENCE_NOT_FOUND")
    if _digest(_event_payload(event)) != record.review_independence_sha256:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_INDEPENDENCE_DIGEST_MISMATCH")
    payload = dict(event.get("payload") or {})
    if str(payload.get("decision") or "").strip().upper() != "PASS":
        raise PermissionError("TRUSTED_SECURITY_REVIEW_INDEPENDENCE_NOT_PASS")
    if str(payload.get("reviewer_session_ref") or "").strip() != record.reviewer_session_ref:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_SESSION_MISMATCH")
    return record
