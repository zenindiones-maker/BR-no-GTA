from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


CONTRACT_INPUT_GAP = "CONTRACT_INPUT_GAP"
CONTRACT_OUTPUT_FAILURE = "CONTRACT_OUTPUT_FAILURE"
TOOL_REQUEST_INVALID = "TOOL_REQUEST_INVALID"
TOOL_AUTHORIZATION_SCOPE_GAP = "TOOL_AUTHORIZATION_SCOPE_GAP"
TOOL_EXECUTION_TRANSIENT = "TOOL_EXECUTION_TRANSIENT"
PROVIDER_TRANSIENT = "PROVIDER_TRANSIENT"
PROVIDER_MODEL_UNAVAILABLE = "PROVIDER_MODEL_UNAVAILABLE"
REGISTRY_SELECTION_GAP = "REGISTRY_SELECTION_GAP"
ARTIFACT_RESOLUTION_FAILURE = "ARTIFACT_RESOLUTION_FAILURE"
CHECKPOINT_INCOMPATIBLE = "CHECKPOINT_INCOMPATIBLE"
DETERMINISTIC_CODE_DEFECT = "DETERMINISTIC_CODE_DEFECT"
MUTATION_VALIDATION_FAILURE = "MUTATION_VALIDATION_FAILURE"
EXTERNAL_CREDENTIAL_REQUIRED = "EXTERNAL_CREDENTIAL_REQUIRED"
EXTERNAL_PERMISSION_REQUIRED = "EXTERNAL_PERMISSION_REQUIRED"
HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"

_TERMINAL_HUMAN = {
    EXTERNAL_CREDENTIAL_REQUIRED,
    EXTERNAL_PERMISSION_REQUIRED,
    HUMAN_REVIEW_REQUIRED,
}

_STRATEGIES: dict[str, tuple[str, ...]] = {
    CONTRACT_INPUT_GAP: ("RECOMPUTE_TYPED_INPUT_SCOPE",),
    TOOL_AUTHORIZATION_SCOPE_GAP: ("RECOMPUTE_TYPED_INPUT_SCOPE",),
    CONTRACT_OUTPUT_FAILURE: ("STRUCTURED_CORRECTION_TURN",),
    TOOL_REQUEST_INVALID: ("STRUCTURED_CORRECTION_TURN",),
    TOOL_EXECUTION_TRANSIENT: ("RETRY_SAME_TASK", "LOCALIZED_TOOL_REPLAN"),
    PROVIDER_TRANSIENT: ("RETRY_SAME_TASK", "LOCALIZED_PROVIDER_REPLAN"),
    PROVIDER_MODEL_UNAVAILABLE: ("LOCALIZED_PROVIDER_REPLAN",),
    REGISTRY_SELECTION_GAP: ("LOCALIZED_REGISTRY_RESOLUTION",),
    ARTIFACT_RESOLUTION_FAILURE: ("REFRESH_LINEAGE",),
    CHECKPOINT_INCOMPATIBLE: ("INVALIDATE_INCOMPATIBLE_NODE",),
    DETERMINISTIC_CODE_DEFECT: ("SELF_IMPROVEMENT_SUBFLOW",),
    MUTATION_VALIDATION_FAILURE: ("ROLLBACK_AND_REVISE",),
}


@dataclass(frozen=True)
class FailureClassification:
    failure_class: str
    failure_signature: str
    error_code: str
    safe_reason: str
    recoverable: bool
    human_intervention_required: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryDecision:
    recoverable: bool
    strategy: str | None
    attempt: int
    exhausted: bool
    human_intervention_required: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cause_chain(exc: BaseException) -> list[BaseException]:
    rows: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(rows) < 8:
        seen.add(id(current))
        rows.append(current)
        next_exc = getattr(current, "__cause__", None)
        if next_exc is None:
            next_exc = getattr(current, "__context__", None)
        current = next_exc if isinstance(next_exc, BaseException) else None
    return rows


def classify_internal_failure(
    exc: BaseException,
    *,
    task: Any,
    context: dict[str, Any] | None = None,
    contract_version: str = "1",
) -> FailureClassification:
    causes = _cause_chain(exc)
    names = " ".join(type(item).__name__ for item in causes)
    reason_parts = []
    for item in causes:
        safe = str(getattr(item, "safe_reason", "") or "").strip()
        reason_parts.append(safe or str(item))
    reason = " | ".join(reason_parts)[:1600]
    folded = (names + " " + reason).casefold()

    if "taskinputcontractviolation" in folded:
        failure_class = CONTRACT_INPUT_GAP
    elif (
        "agenttoolauthorizationerror" in folded
        and "tool_input_ref_outside_task_scope" in folded
    ):
        failure_class = TOOL_AUTHORIZATION_SCOPE_GAP
    elif "agenttoolrequesterror" in folded:
        failure_class = TOOL_REQUEST_INVALID
    elif (
        "taskoutputcontractviolation" in folded
        or "agentturncontracterror" in folded
    ):
        failure_class = CONTRACT_OUTPUT_FAILURE
    elif any(marker in folded for marker in (
        "external_credential_required",
        "credential required",
        "authentication required",
        "codex_noninteractive_auth_configuration",
    )):
        failure_class = EXTERNAL_CREDENTIAL_REQUIRED
    elif any(marker in folded for marker in (
        "external_permission_required",
        "permission required",
        "forbidden external",
    )):
        failure_class = EXTERNAL_PERMISSION_REQUIRED
    elif "human_review_required" in folded:
        failure_class = HUMAN_REVIEW_REQUIRED
    elif any(marker in folded for marker in (
        "model_unavailable",
        "model unavailable",
        "gone",
    )):
        failure_class = PROVIDER_MODEL_UNAVAILABLE
    elif (
        "capabilityreturnedfailure" in folded
        and any(marker in folded for marker in (
            "upstream service failed",
            "provider unavailable",
            "timeout",
            "timed out",
            "temporar",
            "http 429",
            "http 5",
            "rate limit",
        ))
    ):
        failure_class = PROVIDER_TRANSIENT
    elif any(marker in folded for marker in (
        "nvidia nim request timed out",
        "semantic provider request timed out",
        "provider request timed out",
        "provider timeout",
    )):
        failure_class = PROVIDER_TRANSIENT
    elif any(marker in folded for marker in (
        "transport_request",
        "provider_timeout",
        "upstream service failed",
    )):
        failure_class = PROVIDER_TRANSIENT
    elif (
        any(marker in folded for marker in (
            "nvidia nim",
            "semantic provider",
            "provider",
            "model",
        ))
        and any(marker in folded for marker in (
            "timeout",
            "timed out",
            "temporar",
            "rate limit",
            "http 429",
            "http 5",
        ))
    ):
        failure_class = PROVIDER_TRANSIENT
    elif (
        "agenttool" in folded
        and any(marker in folded for marker in ("timeout", "transient"))
    ):
        failure_class = TOOL_EXECUTION_TRANSIENT
    elif any(marker in folded for marker in (
        "no healthy registry capability",
        "registry selection",
        "routingpolicyerror",
        "non-executable registry capability",
    )):
        failure_class = REGISTRY_SELECTION_GAP
    elif any(marker in folded for marker in (
        "dependencyartifactmissing",
        "artifact_resolution",
        "artifact not found",
        "tool_input_artifact_not_found",
    )):
        failure_class = ARTIFACT_RESOLUTION_FAILURE
    elif "checkpoint" in folded and any(
        marker in folded
        for marker in ("incompatible", "hash", "lineage", "stale")
    ):
        failure_class = CHECKPOINT_INCOMPATIBLE
    elif "validation" in folded and any(
        marker in folded
        for marker in ("candidate", "mutation", "regression")
    ):
        failure_class = MUTATION_VALIDATION_FAILURE
    else:
        failure_class = DETERMINISTIC_CODE_DEFECT

    error_code = type(causes[0]).__name__ if causes else type(exc).__name__
    task_class = str(getattr(task, "task_class", "") or "")
    capability_id = str(getattr(task, "capability_id", "") or "")
    lineage_signature = ""
    if isinstance(context, dict):
        lineage_signature = str(
            context.get("task_input_scope_sha256")
            or context.get("dependency_context_sha256")
            or ""
        )
    signature = sha256(json.dumps(
        {
            "failure_class": failure_class,
            "task_class": task_class,
            "capability_id": capability_id,
            "error_code": error_code,
            "contract_version": str(contract_version or "1"),
            "input_lineage_signature": lineage_signature,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    human = failure_class in _TERMINAL_HUMAN
    return FailureClassification(
        failure_class=failure_class,
        failure_signature=signature,
        error_code=error_code,
        safe_reason=reason[:800],
        recoverable=not human,
        human_intervention_required=human,
    )


class HarnessInternalRecoveryState:
    def __init__(
        self,
        *,
        mission_id: str,
        goal_id: str,
        artifact_dir: str | Path,
    ) -> None:
        self.path = Path(artifact_dir) / "internal-recovery-state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
        else:
            loaded = {}
        self.state: dict[str, Any] = {
            "schema": "HarnessMissionRecoveryState/v1",
            "authority": "DEEPSEEK_HARNESS",
            "ORIGINAL_MISSION_ID": mission_id,
            "ORIGINAL_GOAL_ID": goal_id,
            "MISSION_STATUS": "RUNNING",
            "CURRENT_TASK": None,
            "LAST_SUCCESSFUL_TASK": None,
            "FAILED_TASK": None,
            "FAILURE_CLASS": None,
            "FAILURE_SIGNATURE": None,
            "RECOVERY_STATE": "IDLE",
            "RECOVERY_ATTEMPT": 0,
            "RECOVERY_REASON": None,
            "CHECKPOINT_REFS": [],
            "NEXT_TRANSITION": None,
            "strategies_by_signature": {},
            "events": [],
            **loaded,
        }
        self.state["ORIGINAL_MISSION_ID"] = mission_id
        self.state["ORIGINAL_GOAL_ID"] = goal_id
        self._persist()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _event(self, name: str, **fields: Any) -> None:
        rows = list(self.state.get("events") or ())
        rows.append({
            "event": name,
            "timestamp": self._now(),
            **fields,
        })
        self.state["events"] = rows[-200:]

    def _persist(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                self.state,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state, default=str))

    def task_started(self, task_id: str) -> None:
        self.state["MISSION_STATUS"] = "RUNNING"
        self.state["CURRENT_TASK"] = task_id
        self.state["NEXT_TRANSITION"] = "EXECUTE_TASK"
        self._event("TASK_STARTED", task_id=task_id)
        self._persist()

    def observe_failure(
        self,
        *,
        task: Any,
        exc: BaseException,
        context: dict[str, Any] | None = None,
        contract_version: str = "1",
    ) -> FailureClassification:
        classification = classify_internal_failure(
            exc,
            task=task,
            context=context,
            contract_version=contract_version,
        )
        self.state["FAILED_TASK"] = str(getattr(task, "task_id", "") or "")
        self.state["FAILURE_CLASS"] = classification.failure_class
        self.state["FAILURE_SIGNATURE"] = classification.failure_signature
        self.state["RECOVERY_REASON"] = classification.safe_reason
        self.state["MISSION_STATUS"] = (
            "BLOCKED_EXTERNAL"
            if classification.human_intervention_required
            else "RECOVERING_INTERNAL"
        )
        self.state["RECOVERY_STATE"] = "CLASSIFIED"
        self.state["NEXT_TRANSITION"] = (
            "WAIT_FOR_HUMAN"
            if classification.human_intervention_required
            else "SELECT_RECOVERY"
        )
        self._event(
            "TASK_FAILED",
            task_id=self.state["FAILED_TASK"],
            failure_class=classification.failure_class,
            failure_signature=classification.failure_signature,
        )
        self._event(
            "FAILURE_CLASSIFIED",
            task_id=self.state["FAILED_TASK"],
            failure_class=classification.failure_class,
            failure_signature=classification.failure_signature,
            human_intervention_required=(
                classification.human_intervention_required
            ),
        )
        self._persist()
        return classification

    def select_recovery(
        self,
        classification: FailureClassification,
        *,
        disallowed_strategies: tuple[str, ...] = (),
    ) -> RecoveryDecision:
        if classification.human_intervention_required:
            return RecoveryDecision(
                recoverable=False,
                strategy=None,
                attempt=0,
                exhausted=False,
                human_intervention_required=True,
            )
        sequence = _STRATEGIES.get(classification.failure_class, ())
        used = list(
            (self.state.get("strategies_by_signature") or {}).get(
                classification.failure_signature,
                (),
            )
        )
        disallowed = {str(item) for item in disallowed_strategies}
        strategy = next(
            (
                item
                for item in sequence
                if item not in used and item not in disallowed
            ),
            None,
        )
        decision = RecoveryDecision(
            recoverable=strategy is not None,
            strategy=strategy,
            attempt=len(used) + 1 if strategy else len(used),
            exhausted=strategy is None,
            human_intervention_required=False,
        )
        self.state["NEXT_TRANSITION"] = (
            "RECOVERY_START" if strategy else "FAILED_TERMINAL"
        )
        self._event(
            "RECOVERY_SELECTED",
            task_id=self.state.get("FAILED_TASK"),
            failure_signature=classification.failure_signature,
            strategy=strategy,
            attempt=decision.attempt,
            exhausted=decision.exhausted,
        )
        if strategy is None:
            self.state["MISSION_STATUS"] = "FAILED_TERMINAL"
            self.state["RECOVERY_STATE"] = "EXHAUSTED"
        self._persist()
        return decision

    def recovery_started(
        self,
        *,
        classification: FailureClassification,
        decision: RecoveryDecision,
    ) -> None:
        if not decision.recoverable or not decision.strategy:
            return
        by_sig = dict(self.state.get("strategies_by_signature") or {})
        used = list(by_sig.get(classification.failure_signature) or ())
        used.append(decision.strategy)
        by_sig[classification.failure_signature] = used
        self.state["strategies_by_signature"] = by_sig
        self.state["MISSION_STATUS"] = "RECOVERING_INTERNAL"
        self.state["RECOVERY_STATE"] = "RUNNING"
        self.state["RECOVERY_ATTEMPT"] = int(
            self.state.get("RECOVERY_ATTEMPT") or 0
        ) + 1
        self.state["NEXT_TRANSITION"] = decision.strategy
        self._event(
            "RECOVERY_STARTED",
            task_id=self.state.get("FAILED_TASK"),
            failure_class=classification.failure_class,
            failure_signature=classification.failure_signature,
            strategy=decision.strategy,
            attempt=decision.attempt,
        )
        self._event(
            "RECOVERY_STEP",
            task_id=self.state.get("FAILED_TASK"),
            strategy=decision.strategy,
            attempt=decision.attempt,
        )
        self._persist()

    def recovery_validated(
        self,
        *,
        task_id: str,
        validation: str,
    ) -> None:
        self.state["RECOVERY_STATE"] = "VALIDATED"
        self.state["NEXT_TRANSITION"] = "RESUME_FAILED_TASK"
        self._event(
            "RECOVERY_VALIDATED",
            task_id=task_id,
            validation=validation,
        )
        self._persist()

    def task_resumed(self, task_id: str) -> None:
        self.state["MISSION_STATUS"] = "RUNNING"
        self.state["CURRENT_TASK"] = task_id
        self.state["RECOVERY_STATE"] = "RESUMED"
        self.state["NEXT_TRANSITION"] = "EXECUTE_TASK"
        self._event("TASK_RESUMED", task_id=task_id)
        self._persist()

    def task_completed(self, task_id: str) -> None:
        self.state["MISSION_STATUS"] = "RUNNING"
        self.state["CURRENT_TASK"] = task_id
        self.state["LAST_SUCCESSFUL_TASK"] = task_id
        self.state["FAILED_TASK"] = None
        self.state["FAILURE_CLASS"] = None
        self.state["FAILURE_SIGNATURE"] = None
        self.state["RECOVERY_STATE"] = "IDLE"
        self.state["NEXT_TRANSITION"] = "NEXT_TASK"
        self._event("TASK_COMPLETED", task_id=task_id)
        self._persist()

    def mission_completed(self) -> None:
        self.state["MISSION_STATUS"] = "COMPLETED"
        self.state["CURRENT_TASK"] = None
        self.state["NEXT_TRANSITION"] = None
        self._event("MISSION_CONTINUED", status="COMPLETED")
        self._persist()
