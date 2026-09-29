from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


ATTEMPT_SCHEMA = "ContinuousOperationAttempt/v1"
_NONRETRYABLE_CODE_FAILURES = {
    "CONTRACT_VIOLATION",
    "EXECUTOR_BUG",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_error(value: str) -> str:
    text = " ".join(str(value or "").split())[:800]
    text = re.sub(r"(?i)(?:ghp|github_pat|sk|xox[baprs])[_-][A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)bot\d{6,}:[A-Za-z0-9_-]+", "bot[REDACTED]", text)
    text = re.sub(r"(?i)(authorization|token|secret|password)=\S+", r"\1=[REDACTED]", text)
    return text or "unspecified failure"


def classify_continuous_failure(exc: BaseException) -> dict[str, str]:
    name = type(exc).__name__
    message = _normalize_error(str(exc))
    upper = f"{name}:{message}".upper()

    if isinstance(exc, KeyError):
        failure_class = "CONTRACT_VIOLATION"
    elif isinstance(exc, (AttributeError, ImportError, ModuleNotFoundError, AssertionError, TypeError)):
        failure_class = "EXECUTOR_BUG"
    elif any(marker in upper for marker in (
        "PROVIDER_POOL_EXHAUSTED",
        "WAITING_FOR_PROVIDER_AVAILABILITY",
        "HTTP 429",
        "STATUS 429",
        "HTTP 503",
        "STATUS 503",
        "TIMEOUT",
    )):
        failure_class = "PROVIDER_TRANSIENT"
    elif any(marker in upper for marker in ("401", "AUTH_REQUIRED", "AUTHENTICATION")):
        failure_class = "AUTH_REQUIRED"
    else:
        failure_class = "EXECUTION_FAILURE"

    if failure_class in _NONRETRYABLE_CODE_FAILURES:
        retryability = "NOT_RETRYABLE_ON_SAME_EXECUTABLE_SHA"
        next_transition = "CODE_FIX_REQUIRED"
        wake_condition = "TARGET_SHA_CHANGED_OR_EXPLICIT_RETRY_AFTER_FIX"
    elif failure_class == "PROVIDER_TRANSIENT":
        retryability = "BOUNDED_RETRY_OR_PROVIDER_WAIT"
        next_transition = "WAITING_FOR_PROVIDER_AVAILABILITY"
        wake_condition = "PROVIDER_AVAILABILITY_OR_BACKOFF_DUE"
    elif failure_class == "AUTH_REQUIRED":
        retryability = "NOT_RETRYABLE_WITHOUT_AUTH_CHANGE"
        next_transition = "AUTH_REQUIRED"
        wake_condition = "AUTHENTICATION_CHANGED"
    else:
        retryability = "RECONCILE_BEFORE_RETRY"
        next_transition = "RECONCILE"
        wake_condition = "CAUSAL_STATE_CHANGED"

    return {
        "failure_class": failure_class,
        "exception_type": name,
        "sanitized_error": message,
        "retryability": retryability,
        "next_allowed_transition": next_transition,
        "wake_condition": wake_condition,
    }


def failure_fingerprint(
    *,
    target_sha: str,
    workflow_revision: str,
    failure_class: str,
    exception_type: str,
    causal_step: str,
    sanitized_error: str,
) -> str:
    identity = {
        "schema": "ContinuousOperationFailureIdentity/v1",
        "target_sha": str(target_sha or ""),
        "workflow_revision": str(workflow_revision or ""),
        "failure_class": str(failure_class or ""),
        "exception_type": str(exception_type or ""),
        "causal_step": str(causal_step or ""),
        "sanitized_error": _normalize_error(sanitized_error),
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class ContinuousOperationAttempt:
    schema: str
    run_id: str
    target_ref: str
    target_sha: str
    workflow_revision: str
    trigger_kind: str
    started_at: str
    finished_at: str
    status: str
    failure_class: str | None
    failure_fingerprint: str | None
    retryability: str
    causal_task_id: str | None
    causal_step: str
    exception_type: str | None
    sanitized_error: str | None
    evidence_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    side_effects_started: str
    side_effects_settled: str
    next_allowed_transition: str
    wake_condition: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_success_attempt(
    *,
    run_id: str,
    target_ref: str,
    target_sha: str,
    workflow_revision: str,
    trigger_kind: str,
    started_at: str,
    evidence_refs=(),
    artifact_refs=(),
) -> ContinuousOperationAttempt:
    return ContinuousOperationAttempt(
        schema=ATTEMPT_SCHEMA,
        run_id=str(run_id),
        target_ref=str(target_ref),
        target_sha=str(target_sha),
        workflow_revision=str(workflow_revision),
        trigger_kind=str(trigger_kind),
        started_at=str(started_at),
        finished_at=_now(),
        status="PASS",
        failure_class=None,
        failure_fingerprint=None,
        retryability="NOT_APPLICABLE",
        causal_task_id=None,
        causal_step="CONTINUOUS_CYCLE_SETTLED",
        exception_type=None,
        sanitized_error=None,
        evidence_refs=tuple(str(x) for x in evidence_refs if str(x)),
        artifact_refs=tuple(str(x) for x in artifact_refs if str(x)),
        side_effects_started="BOUNDED_BY_POLICY",
        side_effects_settled="PASS",
        next_allowed_transition="SCHEDULE_NEXT_DUE",
        wake_condition=None,
    )


def build_failure_attempt(
    *,
    exc: BaseException,
    run_id: str,
    target_ref: str,
    target_sha: str,
    workflow_revision: str,
    trigger_kind: str,
    started_at: str,
    causal_task_id: str | None = None,
    causal_step: str = "EXECUTE_CONTINUOUS_CYCLE",
    evidence_refs=(),
    artifact_refs=(),
) -> ContinuousOperationAttempt:
    classified = classify_continuous_failure(exc)
    fingerprint = failure_fingerprint(
        target_sha=target_sha,
        workflow_revision=workflow_revision,
        failure_class=classified["failure_class"],
        exception_type=classified["exception_type"],
        causal_step=causal_step,
        sanitized_error=classified["sanitized_error"],
    )
    return ContinuousOperationAttempt(
        schema=ATTEMPT_SCHEMA,
        run_id=str(run_id),
        target_ref=str(target_ref),
        target_sha=str(target_sha),
        workflow_revision=str(workflow_revision),
        trigger_kind=str(trigger_kind),
        started_at=str(started_at),
        finished_at=_now(),
        status="FAIL",
        failure_class=classified["failure_class"],
        failure_fingerprint=fingerprint,
        retryability=classified["retryability"],
        causal_task_id=(str(causal_task_id) if causal_task_id else None),
        causal_step=str(causal_step),
        exception_type=classified["exception_type"],
        sanitized_error=classified["sanitized_error"],
        evidence_refs=tuple(str(x) for x in evidence_refs if str(x)),
        artifact_refs=tuple(str(x) for x in artifact_refs if str(x)),
        side_effects_started="UNKNOWN_REQUIRES_RECONCILIATION",
        side_effects_settled="NOT_PROVEN",
        next_allowed_transition=classified["next_allowed_transition"],
        wake_condition=classified["wake_condition"],
    )


def same_sha_known_defect_hold(
    attempt: dict[str, Any] | ContinuousOperationAttempt,
    *,
    target_sha: str,
) -> bool:
    payload = attempt.to_dict() if isinstance(attempt, ContinuousOperationAttempt) else dict(attempt)
    return (
        payload.get("status") == "FAIL"
        and payload.get("failure_class") in _NONRETRYABLE_CODE_FAILURES
        and payload.get("retryability") == "NOT_RETRYABLE_ON_SAME_EXECUTABLE_SHA"
        and str(payload.get("target_sha") or "") == str(target_sha or "")
        and bool(str(payload.get("failure_fingerprint") or ""))
    )


def persist_attempt(
    attempt: ContinuousOperationAttempt,
    *,
    artifact_dir: str | Path,
) -> Path:
    root = Path(artifact_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "continuous-operation-attempt.json"
    target.write_text(
        json.dumps(attempt.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target
