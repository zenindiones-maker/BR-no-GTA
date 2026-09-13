from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.database.harness_authorization_repository import (
    create_harness_authorization,
    get_harness_authorization,
    update_harness_authorization_status,
)

HARNESS_ISSUER = "deepseek_harness"


@dataclass(frozen=True)
class HarnessAuthorization:
    authorization_id: str
    harness_decision_id: str
    execution_id: str
    authorized_action: str
    subject: str
    issued_by: str
    issued_at: str
    status: str
    lineage: dict[str, Any]

    @property
    def authority(self) -> str:
        return self.issued_by


def _from_record(record: dict[str, Any]) -> HarnessAuthorization:
    return HarnessAuthorization(**{key: record[key] for key in HarnessAuthorization.__dataclass_fields__})


def issue_harness_authorization(*, authorized_action: str, subject: str,
                                harness_decision_id: str | None = None,
                                execution_id: str | None = None,
                                lineage: dict[str, Any] | None = None) -> HarnessAuthorization:
    if not authorized_action or not authorized_action.strip():
        raise ValueError("authorized_action is required")
    if not subject or not subject.strip():
        raise ValueError("subject is required")
    authorization = HarnessAuthorization(
        authorization_id=str(uuid4()),
        harness_decision_id=harness_decision_id or str(uuid4()),
        execution_id=execution_id or str(uuid4()),
        authorized_action=authorized_action.strip().upper(),
        subject=subject.strip(),
        issued_by=HARNESS_ISSUER,
        issued_at=datetime.now(timezone.utc).isoformat(),
        status="active",
        lineage=dict(lineage or {}),
    )
    return _from_record(create_harness_authorization(asdict(authorization)))


def _authorization_id(value: HarnessAuthorization | dict[str, Any] | str) -> str:
    if isinstance(value, HarnessAuthorization):
        return value.authorization_id
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        candidate = value.get("authorization_id")
        if isinstance(candidate, str):
            return candidate
    raise PermissionError("Persisted Harness authorization_id is required")


def resolve_harness_authorization(
    value: HarnessAuthorization | dict[str, Any] | str,
    *, allowed_statuses: tuple[str, ...] = ("active",),
) -> HarnessAuthorization:
    record = get_harness_authorization(_authorization_id(value))
    if record is None:
        raise PermissionError("Harness authorization provenance was not found")
    authorization = _from_record(record)
    if authorization.issued_by != HARNESS_ISSUER:
        raise PermissionError("DeepSeek Harness is the sole authorization authority")
    if authorization.status not in allowed_statuses:
        raise PermissionError(f"Harness authorization status is {authorization.status!r}")
    return authorization


def validate_harness_authorization(
    value: HarnessAuthorization | dict[str, Any] | str,
    *, expected_action: str, expected_subject: str,
    expected_execution_id: str | None = None,
    allowed_statuses: tuple[str, ...] = ("active",),
) -> HarnessAuthorization:
    authorization = resolve_harness_authorization(value, allowed_statuses=allowed_statuses)
    if authorization.authorized_action != expected_action.strip().upper():
        raise PermissionError("Harness authorization action mismatch")
    if authorization.subject != expected_subject:
        raise PermissionError("Harness authorization subject mismatch")
    if expected_execution_id is not None and authorization.execution_id != expected_execution_id:
        raise PermissionError("Harness authorization execution_id mismatch")
    return authorization


def authorization_to_context(authorization: HarnessAuthorization) -> dict[str, Any]:
    return {
        "authorization_id": authorization.authorization_id,
        "harness_decision_id": authorization.harness_decision_id,
        "brain_decision_id": authorization.harness_decision_id,
        "execution_id": authorization.execution_id,
        "authorized_action": authorization.authorized_action,
        "authorization_subject": authorization.subject,
        "issued_by": authorization.issued_by,
        "lineage": dict(authorization.lineage),
    }


def consume_harness_authorization(value: HarnessAuthorization | dict[str, Any] | str) -> None:
    update_harness_authorization_status(_authorization_id(value), "consumed")


def revoke_harness_authorization(value: HarnessAuthorization | dict[str, Any] | str) -> None:
    update_harness_authorization_status(_authorization_id(value), "revoked")
