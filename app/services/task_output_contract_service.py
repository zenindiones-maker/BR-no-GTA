from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any


CANONICAL_FUNCTIONAL_ROLES = frozenset({
    "DIAGNOSIS",
    "ROOT_CAUSE",
    "PROPOSAL",
    "REVIEW",
})

_ROLE_SCHEMA = {
    "DIAGNOSIS": (
        "IncidentDiagnosisEvidence",
        ("failure_class", "observed_evidence", "localization", "confidence", "evidence_refs"),
    ),
    "ROOT_CAUSE": (
        "RootCauseEvidence",
        ("root_cause", "causal_chain", "evidence_refs", "alternatives_rejected", "confidence"),
    ),
    "PROPOSAL": (
        "RecoveryProposalEvidence",
        ("root_cause_ref", "proposed_change", "scope", "expected_effect", "risk", "validation_plan", "evidence_refs"),
    ),
    "REVIEW": (
        "IndependentReviewEvidence",
        ("verdict", "proposal_ref", "root_cause_ref", "reasons", "risks", "required_changes", "evidence_refs"),
    ),
}

_TOOL_LINE_RE = re.compile(
    r"(?im)^\s*(?:br_harness_(?:capability_request|status|submit_evidence)|kanban_[a-z0-9_]+)\b"
)


@dataclass(frozen=True)
class TaskOutputValidation:
    functional_role: str
    required: bool
    expected_schema: str | None
    final_output_schema: str | None
    final_output_valid: bool
    structured_output_found: bool
    unresolved_tool_request: bool
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskOutputContractViolation(RuntimeError):
    def __init__(self, validation: TaskOutputValidation) -> None:
        self.validation = validation
        super().__init__(
            "TASK_OUTPUT_CONTRACT_INVALID:"
            f"role={validation.functional_role}:"
            f"schema={validation.expected_schema}:"
            f"errors={','.join(validation.errors) or 'unknown'}"
        )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return {
            str(name): _jsonable(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _parse_exact_json_text(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if text.startswith("~~~") and text.endswith("~~~"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _iter_dicts(value: Any):
    normalized = _jsonable(value)
    if isinstance(normalized, dict):
        yield normalized
        for child in normalized.values():
            yield from _iter_dicts(child)
    elif isinstance(normalized, list):
        for child in normalized:
            yield from _iter_dicts(child)
    elif isinstance(normalized, str):
        parsed = _parse_exact_json_text(normalized)
        if parsed is not None:
            yield from _iter_dicts(parsed)


def _iter_strings(value: Any):
    normalized = _jsonable(value)
    if isinstance(normalized, dict):
        for child in normalized.values():
            yield from _iter_strings(child)
    elif isinstance(normalized, list):
        for child in normalized:
            yield from _iter_strings(child)
    elif isinstance(normalized, str):
        yield normalized


def _has_unresolved_tool_request(value: Any) -> bool:
    for item in _iter_dicts(value):
        if any(key in item for key in ("tool_request", "tool_call_request", "requested_tool")):
            return True
        kind = str(item.get("type") or item.get("kind") or "").strip().casefold()
        if kind in {"tool_request", "tool_call", "capability_request"}:
            return True
    return any(_TOOL_LINE_RE.search(text or "") for text in _iter_strings(value))


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _candidate_for_schema(value: Any, expected_schema: str) -> dict[str, Any] | None:
    for item in _iter_dicts(value):
        if str(item.get("schema") or "").strip() == expected_schema:
            return item
    return None


def validate_task_output_contract(*, functional_role: str | None, result: Any) -> TaskOutputValidation:
    role = str(functional_role or "GENERAL").strip().upper() or "GENERAL"
    contract = _ROLE_SCHEMA.get(role)
    if contract is None:
        return TaskOutputValidation(
            functional_role=role,
            required=False,
            expected_schema=None,
            final_output_schema=None,
            final_output_valid=True,
            structured_output_found=False,
            unresolved_tool_request=False,
            errors=(),
        )

    expected_schema, required_fields = contract
    unresolved_tool = _has_unresolved_tool_request(result)
    candidate = _candidate_for_schema(result, expected_schema)
    errors: list[str] = []
    if unresolved_tool:
        errors.append("UNRESOLVED_TOOL_REQUEST")
    if candidate is None:
        errors.append("FINAL_STRUCTURED_OUTPUT_MISSING")
    else:
        for field in required_fields:
            if field not in candidate:
                errors.append(f"MISSING_FIELD:{field}")
            elif field != "required_changes" and not _nonempty(candidate.get(field)):
                errors.append(f"EMPTY_FIELD:{field}")

        refs = candidate.get("evidence_refs")
        if "evidence_refs" in candidate and not isinstance(refs, (list, tuple)):
            errors.append("INVALID_TYPE:evidence_refs")
        elif isinstance(refs, (list, tuple)) and not all(
            isinstance(item, str) and item.strip() for item in refs
        ):
            errors.append("INVALID_VALUE:evidence_refs")

        if role in {"DIAGNOSIS", "ROOT_CAUSE"} and "confidence" in candidate:
            confidence = candidate.get("confidence")
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
                errors.append("INVALID_TYPE:confidence")
            elif not 0.0 <= float(confidence) <= 1.0:
                errors.append("INVALID_RANGE:confidence")

        if role == "REVIEW" and candidate.get("verdict") not in {"ACCEPT", "REVISE", "REJECT"}:
            errors.append("INVALID_VERDICT")

    return TaskOutputValidation(
        functional_role=role,
        required=True,
        expected_schema=expected_schema,
        final_output_schema=(str(candidate.get("schema")) if candidate is not None else None),
        final_output_valid=not errors,
        structured_output_found=candidate is not None,
        unresolved_tool_request=unresolved_tool,
        errors=tuple(errors),
    )



def task_output_contract_descriptor(functional_role: str | None) -> dict[str, Any]:
    role = str(functional_role or "GENERAL").strip().upper() or "GENERAL"
    contract = _ROLE_SCHEMA.get(role)
    if contract is None:
        return {
            "functional_role": role,
            "required": False,
            "schema": None,
            "required_fields": [],
            "allowed_verdicts": [],
        }
    schema, fields = contract
    return {
        "functional_role": role,
        "required": True,
        "schema": schema,
        "required_fields": list(fields),
        "allowed_verdicts": (
            ["ACCEPT", "REVISE", "REJECT"] if role == "REVIEW" else []
        ),
    }

def task_output_json_schema(functional_role: str | None) -> dict[str, Any] | None:
    descriptor = task_output_contract_descriptor(functional_role)
    if not descriptor["required"]:
        return None
    role = str(descriptor["functional_role"])
    expected_schema = str(descriptor["schema"])
    required_fields = list(descriptor["required_fields"])
    properties: dict[str, Any] = {
        "schema": {"type": "string", "const": expected_schema},
    }
    for field in required_fields:
        properties[field] = {}
    if "confidence" in properties:
        properties["confidence"] = {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        }
    if "evidence_refs" in properties:
        properties["evidence_refs"] = {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        }
    if role == "REVIEW":
        properties["verdict"] = {
            "type": "string",
            "enum": ["ACCEPT", "REVISE", "REJECT"],
        }
    return {
        "type": "object",
        "properties": properties,
        "required": ["schema", *required_fields],
        "additionalProperties": False,
    }


def require_valid_task_output(*, functional_role: str | None, result: Any) -> TaskOutputValidation:
    validation = validate_task_output_contract(functional_role=functional_role, result=result)
    if validation.required and not validation.final_output_valid:
        raise TaskOutputContractViolation(validation)
    return validation
