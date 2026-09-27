from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

TASK_ATOMICITY_SCHEMA = "TaskAtomicityContract/v1"
ATOMIC = "ATOMIC"
SPLIT_REQUIRED = "SPLIT_REQUIRED"

def _canon(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

def _texts(values: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        str(item).strip()
        for item in (values or ())
        if str(item).strip()
    ))

@dataclass(frozen=True)
class TaskAtomicityContract:
    mission_id: str
    task_id: str
    atomic_goal: str
    preconditions: tuple[str, ...]
    allowed_inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    read_scope: tuple[str, ...]
    write_scope: tuple[str, ...]
    side_effect_scope: tuple[str, ...]
    postconditions: tuple[str, ...]
    failure_semantics: str
    retry_semantics: str
    idempotency_identity: str
    evidence_requirements: tuple[str, ...]
    decision: str
    split_reasons: tuple[str, ...]
    content_sha256: str
    authority: str = "DEEPSEEK_HARNESS"
    schema: str = TASK_ATOMICITY_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class TaskSplitRequired(ValueError):
    def __init__(self, contract: TaskAtomicityContract):
        self.contract = contract
        super().__init__(
            "TASK_SPLIT_REQUIRED:"
            + contract.task_id
            + ":"
            + ",".join(contract.split_reasons)
        )

def compile_task_atomicity_contract(
    task: Mapping[str, Any],
    *,
    mission_id: str,
) -> TaskAtomicityContract:
    task_id = str(task.get("task_id") or "").strip()
    objective = str(task.get("objective") or "").strip()
    mission_id = str(mission_id or "").strip()
    if not task_id or not objective or not mission_id:
        raise ValueError(
            "task atomicity requires mission_id, task_id and objective"
        )

    declared_atomic_goals = _texts(task.get("atomic_goals"))
    atomic_goals = declared_atomic_goals or (objective,)
    expected_outputs = _texts(task.get("expected_outputs"))
    if not expected_outputs:
        single = str(task.get("expected_output") or "").strip()
        expected_outputs = (single,) if single else ()

    split_reasons: list[str] = []
    if len(atomic_goals) > 1:
        split_reasons.append("MULTIPLE_ATOMIC_GOALS")
    if bool(task.get("independent_outcomes", False)):
        split_reasons.append("INDEPENDENT_OUTCOMES_DECLARED")

    # A caller may describe work but cannot self-authorize atomicity.
    # caller-supplied atomicity_decision/atomicity_contract fields are ignored.
    decision = SPLIT_REQUIRED if split_reasons else ATOMIC

    dependencies = _texts(task.get("dependencies"))
    input_refs = _texts(task.get("input_refs"))
    preconditions = _texts(task.get("preconditions")) or tuple(
        [*(f"dependency:{value}" for value in dependencies)]
        + [*(f"input:{value}" for value in input_refs)]
    )
    postconditions = _texts(task.get("postconditions")) or _texts(
        task.get("acceptance_criteria")
    )
    evidence_requirements = _texts(task.get("evidence_requirements"))
    if not evidence_requirements:
        evidence_contract = str(task.get("evidence_contract") or "").strip()
        if evidence_contract:
            evidence_requirements = (evidence_contract,)

    retry_budget = int(task.get("retry_budget") or 0)
    retry_semantics = str(task.get("retry_semantics") or "").strip().upper()
    if not retry_semantics:
        retry_semantics = (
            f"BOUNDED_RETRY:{retry_budget}"
            if retry_budget > 0
            else "NO_RETRY"
        )
    failure_semantics = str(
        task.get("failure_semantics") or "FAIL_CLOSED"
    ).strip().upper()

    identity_payload = {
        "mission_id": mission_id,
        "task_id": task_id,
        "atomic_goal": atomic_goals[0],
        "preconditions": list(preconditions),
        "allowed_inputs": list(input_refs),
        "expected_outputs": list(expected_outputs),
        "read_scope": list(_texts(task.get("read_scope"))),
        "write_scope": list(_texts(task.get("write_scope"))),
        "side_effect_scope": list(_texts(task.get("allowed_side_effects"))),
        "postconditions": list(postconditions),
        "failure_semantics": failure_semantics,
        "retry_semantics": retry_semantics,
        "evidence_requirements": list(evidence_requirements),
    }
    idempotency_identity = (
        str(task.get("idempotency_key") or "").strip()
        or "atomic-task:" + sha256(_canon(identity_payload)).hexdigest()
    )
    logical = {
        "schema": TASK_ATOMICITY_SCHEMA,
        **identity_payload,
        "idempotency_identity": idempotency_identity,
        "decision": decision,
        "split_reasons": split_reasons,
        "authority": "DEEPSEEK_HARNESS",
    }
    return TaskAtomicityContract(
        mission_id=mission_id,
        task_id=task_id,
        atomic_goal=atomic_goals[0],
        preconditions=preconditions,
        allowed_inputs=input_refs,
        expected_outputs=expected_outputs,
        read_scope=_texts(task.get("read_scope")),
        write_scope=_texts(task.get("write_scope")),
        side_effect_scope=_texts(task.get("allowed_side_effects")),
        postconditions=postconditions,
        failure_semantics=failure_semantics,
        retry_semantics=retry_semantics,
        idempotency_identity=idempotency_identity,
        evidence_requirements=evidence_requirements,
        decision=decision,
        split_reasons=tuple(split_reasons),
        content_sha256=sha256(_canon(logical)).hexdigest(),
    )

def require_atomic_task(
    task: Mapping[str, Any],
    *,
    mission_id: str,
) -> TaskAtomicityContract:
    contract = compile_task_atomicity_contract(
        task,
        mission_id=mission_id,
    )
    if contract.decision == SPLIT_REQUIRED:
        raise TaskSplitRequired(contract)
    return contract
