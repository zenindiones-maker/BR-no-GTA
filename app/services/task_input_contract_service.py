from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any


_ROLE_INPUT_CONTRACTS: dict[str, dict[str, tuple[str, ...]]] = {
    "DIAGNOSIS": {
        "required": ("incident_evidence",),
        "optional": (),
    },
    "ROOT_CAUSE": {
        "required": ("diagnosis",),
        "optional": ("incident_evidence",),
    },
    "PROPOSAL": {
        "required": ("root_cause",),
        "optional": ("incident_evidence",),
    },
    "REVIEW": {
        "required": ("proposal", "root_cause", "incident_evidence"),
        "optional": (),
    },
    "APPLY": {
        "required": ("proposal", "review", "recovery_candidate_spec"),
        "optional": (),
    },
    "VALIDATE": {
        "required": ("applied_candidate", "validation_plan"),
        "optional": (),
    },
}

_SOURCE_ROLE_LABEL = {
    "DIAGNOSIS": "diagnosis",
    "ROOT_CAUSE": "root_cause",
    "PROPOSAL": "proposal",
    "REVIEW": "review",
    "APPLY": "applied_candidate",
}


@dataclass(frozen=True)
class TaskInputValidation:
    functional_role: str
    required: bool
    valid: bool
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...]
    resolved_inputs: dict[str, str]
    missing_inputs: tuple[str, ...]
    authorized_refs: tuple[str, ...]
    source_task_ids: tuple[str, ...]
    input_ref_count: int
    unused_input_ref_count: int
    out_of_scope_artifact_access: int
    scope_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskInputContractViolation(RuntimeError):
    def __init__(self, validation: TaskInputValidation) -> None:
        self.validation = validation
        super().__init__(
            "TASK_INPUT_CONTRACT_INVALID:"
            f"role={validation.functional_role}:"
            f"missing={','.join(validation.missing_inputs) or 'unknown'}"
        )


def task_input_contract_descriptor(functional_role: str | None) -> dict[str, Any]:
    role = str(functional_role or "GENERAL").strip().upper() or "GENERAL"
    contract = _ROLE_INPUT_CONTRACTS.get(role)
    if contract is None:
        return {
            "functional_role": role,
            "required": False,
            "required_inputs": [],
            "optional_inputs": [],
        }
    return {
        "functional_role": role,
        "required": True,
        "required_inputs": list(contract["required"]),
        "optional_inputs": list(contract["optional"]),
    }


def _refs(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        rows = (value,)
    elif isinstance(value, (list, tuple, set)):
        rows = value
    else:
        rows = ()
    return tuple(dict.fromkeys(
        str(item).strip()
        for item in rows
        if str(item).strip()
    ))


def _add(
    candidates: dict[str, list[tuple[str, str | None]]],
    label: str,
    ref: str,
    source_task_id: str | None,
) -> None:
    value = str(ref or "").strip()
    if not value:
        return
    row = (value, str(source_task_id or "").strip() or None)
    bucket = candidates.setdefault(label, [])
    if row not in bucket:
        bucket.append(row)


def resolve_task_input_contract(
    *,
    functional_role: str | None,
    task_input_refs: tuple[str, ...] | list[str] = (),
    parent_handoffs: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
) -> TaskInputValidation:
    descriptor = task_input_contract_descriptor(functional_role)
    role = str(descriptor["functional_role"])
    if not descriptor["required"]:
        return TaskInputValidation(
            functional_role=role,
            required=False,
            valid=True,
            required_inputs=(),
            optional_inputs=(),
            resolved_inputs={},
            missing_inputs=(),
            authorized_refs=(),
            source_task_ids=(),
            input_ref_count=0,
            unused_input_ref_count=0,
            out_of_scope_artifact_access=0,
            scope_sha256=sha256(b"no-input-contract").hexdigest(),
        )

    candidates: dict[str, list[tuple[str, str | None]]] = {}
    for ref in _refs(task_input_refs):
        _add(candidates, "incident_evidence", ref, None)
        if "candidate-spec" in ref.casefold():
            _add(candidates, "recovery_candidate_spec", ref, None)
        if "validation-plan" in ref.casefold():
            _add(candidates, "validation_plan", ref, None)

    for raw in parent_handoffs:
        if not isinstance(raw, dict):
            continue
        source_task_id = str(raw.get("task_id") or "").strip() or None
        source_role = str(raw.get("functional_role") or "").strip().upper()
        task_result_ref = str(raw.get("task_result_ref") or "").strip()
        label = _SOURCE_ROLE_LABEL.get(source_role)
        if label and task_result_ref:
            _add(candidates, label, task_result_ref, source_task_id)

        if source_role == "EVIDENCE":
            source_input_refs = _refs(raw.get("input_refs"))
            if source_input_refs:
                for ref in source_input_refs:
                    _add(
                        candidates,
                        "incident_evidence",
                        ref,
                        source_task_id,
                    )
            else:
                for ref in (
                    *_refs(raw.get("output_artifact_refs")),
                    *_refs(raw.get("evidence_refs")),
                ):
                    if ref.startswith("artifact:"):
                        _add(
                            candidates,
                            "incident_evidence",
                            ref,
                            source_task_id,
                        )

        result = raw.get("result")
        if isinstance(result, dict):
            candidate_ref = str(
                result.get("recovery_candidate_spec_ref") or ""
            ).strip()
            if candidate_ref:
                _add(
                    candidates,
                    "recovery_candidate_spec",
                    candidate_ref,
                    source_task_id,
                )
            applied_ref = str(
                result.get("applied_candidate_ref") or ""
            ).strip()
            if applied_ref:
                _add(
                    candidates,
                    "applied_candidate",
                    applied_ref,
                    source_task_id,
                )
            validation_ref = str(
                result.get("validation_plan_ref") or ""
            ).strip()
            if validation_ref:
                _add(
                    candidates,
                    "validation_plan",
                    validation_ref,
                    source_task_id,
                )

    required_inputs = tuple(descriptor["required_inputs"])
    optional_inputs = tuple(descriptor["optional_inputs"])
    resolved: dict[str, str] = {}
    source_ids: list[str] = []
    for label in (*required_inputs, *optional_inputs):
        rows = candidates.get(label) or []
        if not rows:
            continue
        ref, source_task_id = rows[0]
        resolved[label] = ref
        if source_task_id and source_task_id not in source_ids:
            source_ids.append(source_task_id)

    missing = tuple(
        label for label in required_inputs if label not in resolved
    )
    authorized_refs = tuple(dict.fromkeys(
        resolved[label]
        for label in (*required_inputs, *optional_inputs)
        if label in resolved
    ))
    scope_sha = sha256(json.dumps(
        {
            "role": role,
            "resolved_inputs": resolved,
            "source_task_ids": source_ids,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()

    return TaskInputValidation(
        functional_role=role,
        required=True,
        valid=not missing,
        required_inputs=required_inputs,
        optional_inputs=optional_inputs,
        resolved_inputs=resolved,
        missing_inputs=missing,
        authorized_refs=authorized_refs,
        source_task_ids=tuple(source_ids),
        input_ref_count=len(authorized_refs),
        unused_input_ref_count=0,
        out_of_scope_artifact_access=0,
        scope_sha256=scope_sha,
    )


def scope_task_context(
    context: dict[str, Any],
    validation: TaskInputValidation,
) -> dict[str, Any]:
    if not validation.required:
        return dict(context)

    authorized = set(validation.authorized_refs)
    source_ids = set(validation.source_task_ids)
    scoped_handoffs: list[dict[str, Any]] = []
    for raw in context.get("parent_handoffs") or ():
        if not isinstance(raw, dict):
            continue
        task_id = str(raw.get("task_id") or "").strip()
        refs = {
            str(raw.get("task_result_ref") or "").strip(),
            *_refs(raw.get("input_refs")),
            *_refs(raw.get("output_artifact_refs")),
            *_refs(raw.get("evidence_refs")),
        }
        refs.discard("")
        if task_id not in source_ids and not (refs & authorized):
            continue
        scoped_handoffs.append({
            "task_id": task_id,
            "functional_role": raw.get("functional_role"),
            "capability_id": raw.get("capability_id"),
            "agent_id": raw.get("agent_id"),
            "skill_id": raw.get("skill_id"),
            "task_result_ref": raw.get("task_result_ref"),
            "content_sha256": raw.get("content_sha256"),
            "result_summary": raw.get("result_summary"),
            "input_refs": [
                ref for ref in _refs(raw.get("input_refs"))
                if ref in authorized
            ],
            "output_artifact_refs": [
                ref for ref in _refs(raw.get("output_artifact_refs"))
                if ref in authorized
            ],
            "evidence_refs": [
                ref for ref in _refs(raw.get("evidence_refs"))
                if ref in authorized
            ],
            "source_task_ids": list(raw.get("source_task_ids") or ()),
            "direct_dependency": bool(raw.get("direct_dependency")),
            "result_omitted": "TYPED_INPUT_SCOPE",
        })

    scoped = dict(context)
    scoped["parent_handoffs"] = scoped_handoffs
    scoped["dependency_results"] = [
        {
            "task_id": item.get("task_id"),
            "task_result_ref": item.get("task_result_ref"),
            "content_sha256": item.get("content_sha256"),
            "direct_dependency": bool(item.get("direct_dependency")),
        }
        for item in scoped_handoffs
    ]
    scoped["input_artifacts"] = [
        dict(item)
        for item in (context.get("input_artifacts") or ())
        if isinstance(item, dict)
        and str(item.get("artifact_ref") or "").strip() in authorized
    ]
    scoped["evidence_refs"] = list(validation.authorized_refs)
    scoped["input_refs"] = list(validation.authorized_refs)
    scoped["authorized_task_input_refs"] = list(validation.authorized_refs)
    scoped["typed_inputs"] = dict(validation.resolved_inputs)
    scoped["typed_input_contract"] = validation.to_dict()
    scoped["TASK_INPUT_REF_COUNT"] = validation.input_ref_count
    scoped["UNUSED_INPUT_REF_COUNT"] = validation.unused_input_ref_count
    scoped["OUT_OF_SCOPE_ARTIFACT_ACCESS"] = (
        validation.out_of_scope_artifact_access
    )
    scoped["task_input_scope_sha256"] = validation.scope_sha256
    scoped.pop("transitive_dependency_refs", None)
    return scoped


def require_valid_task_inputs(
    *,
    functional_role: str | None,
    task_input_refs: tuple[str, ...] | list[str] = (),
    parent_handoffs: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
) -> TaskInputValidation:
    validation = resolve_task_input_contract(
        functional_role=functional_role,
        task_input_refs=task_input_refs,
        parent_handoffs=parent_handoffs,
    )
    if validation.required and not validation.valid:
        raise TaskInputContractViolation(validation)
    return validation
