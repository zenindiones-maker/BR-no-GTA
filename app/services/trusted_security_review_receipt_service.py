from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from app.database.agent_execution_lease_repository import get_lease, get_task_event
from app.database.trusted_security_review_receipt_repository import (
    create_trusted_security_review_receipt,
    get_trusted_security_review_receipt,
)
from app.services.harness_authorization_service import validate_harness_authorization
from app.services.security_review_task_result_service import SecurityReviewTaskResult


REVIEW_SUBJECT = "capability:security.review.repository"
REVIEW_CAPABILITY_ID = "security.review.repository"
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


def _artifact_target(
    repository_root: str | Path,
    result_ref: str,
) -> Path:
    repo = Path(repository_root).resolve()
    ref = str(result_ref or "").strip()
    if not ref:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_TASK_RESULT_MISSING")
    if ref.startswith("artifact:"):
        ref = ref[len("artifact:"):]

    candidate = Path(ref)
    if candidate.is_absolute():
        configured_root = str(os.getenv("AGENT_OFFICE_ARTIFACT_ROOT") or "").strip()
        if not configured_root:
            raise PermissionError(
                "TRUSTED_SECURITY_REVIEW_ABSOLUTE_TASK_RESULT_REF_NOT_ALLOWED"
            )
        allowed_root = Path(configured_root).resolve()
        target = candidate.resolve()
        if target != allowed_root and allowed_root not in target.parents:
            raise PermissionError(
                "TRUSTED_SECURITY_REVIEW_TASK_RESULT_REF_ESCAPED_ARTIFACT_ROOT"
            )
    else:
        target = (repo / candidate).resolve()
        if target != repo and repo not in target.parents:
            raise PermissionError(
                "TRUSTED_SECURITY_REVIEW_TASK_RESULT_REF_ESCAPED_REPOSITORY"
            )

    if not target.is_file():
        raise PermissionError("TRUSTED_SECURITY_REVIEW_TASK_RESULT_NOT_FOUND")
    return target


def _load_review_task_result(
    *,
    repository_root: str | Path,
    lease: Mapping[str, Any],
    expected_candidate_sha: str,
    expected_candidate_tree_sha: str,
    expected_reviewed_diff_sha256: str,
) -> SecurityReviewTaskResult:
    result_ref = str(lease.get("result_ref") or "").strip()
    result_hash = _require_hex(
        lease.get("result_hash"), _HEX64, "task_result_sha256"
    )
    target = _artifact_target(repository_root, result_ref)
    raw = target.read_bytes()
    observed_hash = sha256(raw).hexdigest()
    if observed_hash != result_hash:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_TASK_RESULT_DIGEST_MISMATCH"
        )
    try:
        artifact = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_TASK_RESULT_INVALID_JSON"
        ) from exc
    if not isinstance(artifact, dict):
        raise PermissionError("TRUSTED_SECURITY_REVIEW_TASK_RESULT_INVALID")

    if str(artifact.get("status") or "").strip().upper() != "SUCCEEDED":
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_TASK_RESULT_NOT_SUCCEEDED"
        )
    for field, expected in {
        "task_id": str(lease.get("task_id") or ""),
        "delegation_id": str(lease.get("delegation_id") or ""),
        "capability": REVIEW_CAPABILITY_ID,
    }.items():
        if str(artifact.get(field) or "").strip() != expected:
            raise PermissionError(
                f"TRUSTED_SECURITY_REVIEW_TASK_RESULT_{field.upper()}_MISMATCH"
            )
    agent = str(artifact.get("agent") or "").strip()
    if agent != str(lease.get("agent_id") or "").strip():
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_TASK_RESULT_AGENT_MISMATCH"
        )

    domain = artifact.get("domain_evidence")
    if not isinstance(domain, Mapping):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_TASK_RESULT_DOMAIN_EVIDENCE_MISSING"
        )
    try:
        result = SecurityReviewTaskResult.from_mapping(
            domain,
            expected_candidate_sha=expected_candidate_sha,
            expected_candidate_tree_sha=expected_candidate_tree_sha,
            expected_reviewed_diff_sha256=expected_reviewed_diff_sha256,
        )
    except (TypeError, ValueError, PermissionError) as exc:
        if isinstance(exc, PermissionError):
            raise
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_TASK_RESULT_CONTRACT_INVALID"
        ) from exc
    return result


def _validate_review_execution_lease(
    *,
    lease: Mapping[str, Any],
    review_auth: Any,
    lineage: Mapping[str, Any],
) -> None:
    if str(lease.get("authorization_id") or "") != review_auth.authorization_id:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_AUTH_MISMATCH")
    if str(lease.get("status") or "") != "COMPLETED":
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_NOT_COMPLETED")
    if str(lease.get("mission_id") or "") != str(lineage.get("mission_id") or ""):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_EXECUTION_MISSION_MISMATCH"
        )
    if str(lease.get("task_id") or "") != str(lineage.get("task_id") or ""):
        raise PermissionError("TRUSTED_SECURITY_REVIEW_EXECUTION_TASK_MISMATCH")
    capability_ids = lease.get("capability_ids") or ()
    if REVIEW_CAPABILITY_ID not in tuple(str(item) for item in capability_ids):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_EXECUTION_CAPABILITY_MISMATCH"
        )


def _validate_independence_event(
    *,
    event: Mapping[str, Any],
    lease: Mapping[str, Any],
    review_auth: Any,
    candidate: str,
    tree: str,
    diff: str,
    result_ref: str,
    result_hash: str,
    task_result: SecurityReviewTaskResult,
    principal_sha: str,
) -> tuple[str, str]:
    if str(event.get("delegation_id") or "") != str(
        lease.get("delegation_id") or ""
    ):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_EXECUTION_MISMATCH"
        )
    if str(event.get("event_type") or "") != "REVIEW_INDEPENDENCE_EVIDENCE":
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_TYPE_MISMATCH"
        )
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

    if str(payload.get("reviewed_task_result_ref") or "").strip() != result_ref:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_TASK_RESULT_REF_MISMATCH"
        )
    if (
        str(payload.get("reviewed_task_result_sha256") or "").strip().lower()
        != result_hash
    ):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_TASK_RESULT_DIGEST_MISMATCH"
        )
    principal_ref = str(lease.get("delegation_id") or "")
    if (
        str(payload.get("reviewer_execution_principal_ref") or "").strip()
        != principal_ref
    ):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_PRINCIPAL_REF_MISMATCH"
        )
    supplied_principal_sha = str(
        payload.get("reviewer_execution_principal_sha256") or ""
    ).strip().lower()
    if supplied_principal_sha != principal_sha:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_PRINCIPAL_DIGEST_MISMATCH"
        )
    if (
        str(payload.get("reviewer_authorization_id") or "").strip()
        != review_auth.authorization_id
    ):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_AUTHORIZATION_MISMATCH"
        )
    if (
        str(payload.get("reviewer_session_ref") or "").strip()
        != task_result.reviewer_session_ref
    ):
        raise PermissionError("TRUSTED_SECURITY_REVIEW_SESSION_MISMATCH")
    return decision, _digest(_event_payload(event))


def issue_trusted_security_review_receipt(
    *,
    repository_root: str | Path,
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
    candidate = _require_hex(
        lineage.get("candidate_sha"), _HEX40, "candidate_sha"
    )
    tree = _require_hex(
        lineage.get("candidate_tree_sha"), _HEX40, "candidate_tree_sha"
    )
    diff = _require_hex(
        lineage.get("reviewed_diff_sha256"), _HEX64, "reviewed_diff_sha256"
    )

    lease = get_lease(str(reviewer_delegation_id or "").strip())
    if lease is None:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_EXECUTION_PRINCIPAL_NOT_FOUND"
        )
    _validate_review_execution_lease(
        lease=lease, review_auth=review_auth, lineage=lineage
    )

    result_ref = str(lease.get("result_ref") or "").strip()
    if not result_ref:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_TASK_RESULT_MISSING")
    result_hash = _require_hex(
        lease.get("result_hash"), _HEX64, "task_result_sha256"
    )
    task_result = _load_review_task_result(
        repository_root=repository_root,
        lease=lease,
        expected_candidate_sha=candidate,
        expected_candidate_tree_sha=tree,
        expected_reviewed_diff_sha256=diff,
    )

    principal_ref = str(lease["delegation_id"])
    principal_sha = _digest(_principal_payload(lease))

    event = get_task_event(int(review_independence_event_id))
    if event is None:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_NOT_FOUND"
        )
    decision, independence_sha = _validate_independence_event(
        event=event,
        lease=lease,
        review_auth=review_auth,
        candidate=candidate,
        tree=tree,
        diff=diff,
        result_ref=result_ref,
        result_hash=result_hash,
        task_result=task_result,
        principal_sha=principal_sha,
    )
    independence_ref = f"agent_execution_event:{int(event['id'])}"

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
        "reviewer_session_ref": task_result.reviewer_session_ref,
        "final_disposition": task_result.final_disposition,
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
    *,
    repository_root: str | Path,
) -> TrustedSecurityReviewReceiptRecord:
    ref = str(receipt_ref or "").strip()
    supplied_digest = _require_hex(
        receipt_sha256, _HEX64, "receipt_sha256"
    )
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
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_RECEIPT_DIGEST_MISMATCH"
        )
    if record.issued_by != ISSUED_BY:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_ISSUER_MISMATCH")

    seed = {
        key: value
        for key, value in record.to_dict().items()
        if key not in {"receipt_ref", "receipt_sha256", "schema_version"}
    }
    if _digest(seed) != record.receipt_sha256:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_RECORD_INTEGRITY_MISMATCH"
        )

    review_auth = validate_harness_authorization(
        record.reviewer_authorization_id,
        expected_action="REVIEW",
        expected_subject=REVIEW_SUBJECT,
        allowed_statuses=("consumed",),
    )
    if review_auth.status != record.reviewer_authorization_status:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_AUTH_STATUS_MISMATCH"
        )
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
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_EXECUTION_PRINCIPAL_NOT_FOUND"
        )
    _validate_review_execution_lease(
        lease=lease, review_auth=review_auth, lineage=lineage
    )
    if _digest(_principal_payload(lease)) != (
        record.reviewer_execution_principal_sha256
    ):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_PRINCIPAL_DIGEST_MISMATCH"
        )
    if str(lease.get("result_ref") or "") != record.reviewed_task_result_ref:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_TASK_RESULT_REF_MISMATCH"
        )
    if (
        str(lease.get("result_hash") or "").lower()
        != record.reviewed_task_result_sha256
    ):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_TASK_RESULT_DIGEST_MISMATCH"
        )
    task_result = _load_review_task_result(
        repository_root=repository_root,
        lease=lease,
        expected_candidate_sha=record.candidate_sha,
        expected_candidate_tree_sha=record.candidate_tree_sha,
        expected_reviewed_diff_sha256=record.reviewed_diff_sha256,
    )
    if task_result.reviewer_session_ref != record.reviewer_session_ref:
        raise PermissionError("TRUSTED_SECURITY_REVIEW_SESSION_MISMATCH")
    if task_result.final_disposition != record.final_disposition:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_DISPOSITION_MISMATCH"
        )

    prefix = "agent_execution_event:"
    if not record.review_independence_ref.startswith(prefix):
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_REF_INVALID"
        )
    try:
        event_id = int(record.review_independence_ref[len(prefix):])
    except ValueError as exc:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_REF_INVALID"
        ) from exc
    event = get_task_event(event_id)
    if event is None:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_NOT_FOUND"
        )
    observed_event_digest = _digest(_event_payload(event))
    if observed_event_digest != record.review_independence_sha256:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_DIGEST_MISMATCH"
        )
    decision, _ = _validate_independence_event(
        event=event,
        lease=lease,
        review_auth=review_auth,
        candidate=record.candidate_sha,
        tree=record.candidate_tree_sha,
        diff=record.reviewed_diff_sha256,
        result_ref=record.reviewed_task_result_ref,
        result_hash=record.reviewed_task_result_sha256,
        task_result=task_result,
        principal_sha=record.reviewer_execution_principal_sha256,
    )
    if decision != record.review_independence_decision:
        raise PermissionError(
            "TRUSTED_SECURITY_REVIEW_INDEPENDENCE_DECISION_MISMATCH"
        )
    return record
