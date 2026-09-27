from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

VERIFICATION_KINDS = frozenset({
    "TEST",
    "STATIC_ANALYSIS",
    "SCHEMA_VALIDATION",
    "ARTIFACT_INSPECTION",
    "STATE_QUERY",
    "BROWSER_ASSERTION",
    "MEDIA_ASSERTION",
    "SEMANTIC_REVIEW",
    "INDEPENDENT_REVIEW",
    "HUMAN_GATE",
})
PLAN_SCHEMA = "TaskVerificationPlan/v1"
RESULT_SCHEMA = "TaskVerificationResult/v1"

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

def _criterion_id(task_id: str, index: int, criterion: str) -> str:
    digest = sha256(
        _canon({
            "task_id": task_id,
            "index": index,
            "criterion": criterion,
        })
    ).hexdigest()[:16]
    return f"criterion-{index:02d}-{digest}"

@dataclass(frozen=True)
class VerificationStep:
    criterion_id: str
    criterion: str
    verification_kind: str
    verifier_capability: str
    required_evidence: tuple[str, ...]
    success_predicate: str
    failure_predicate: str
    authority_boundary: str
    human_gate: bool = False
    schema: str = "TaskVerificationStep/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class TaskVerificationPlan:
    mission_id: str
    task_id: str
    steps: tuple[VerificationStep, ...]
    human_gate_required: bool
    terminal_success_requires_all_steps: bool
    no_agent_self_attestation: bool
    authority: str
    content_sha256: str
    schema: str = PLAN_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data

@dataclass(frozen=True)
class TaskVerificationResult:
    mission_id: str
    task_id: str
    status: str
    step_results: tuple[dict[str, Any], ...]
    evidence_refs: tuple[str, ...]
    human_intervention_required: bool
    terminal_success: bool
    authority: str
    content_sha256: str
    schema: str = RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _default_kind(task: Mapping[str, Any]) -> tuple[str, str, str]:
    human_gate = str(task.get("human_gate_policy") or "NONE").upper()
    evidence_contract = str(task.get("evidence_contract") or "").casefold()
    review_policy = str(task.get("review_policy") or "").upper()
    write_scope = _texts(task.get("write_scope"))

    if human_gate not in {"", "NONE", "NOT_REQUIRED"}:
        return "HUMAN_GATE", "human", "human_approved"
    if "browserqa" in evidence_contract or "browser" in evidence_contract:
        return "BROWSER_ASSERTION", "browser.qa.validate", "verifier_pass"
    if any(token in evidence_contract for token in ("media", "ffmpeg", "master")):
        return "MEDIA_ASSERTION", "harness.media-verifier", "verifier_pass"
    if (
        review_policy in {"REQUIRED", "INDEPENDENT_REQUIRED"}
        or write_scope
    ):
        return (
            "INDEPENDENT_REVIEW",
            "harness.independent-review",
            "verifier_accept",
        )
    if evidence_contract:
        return (
            "ARTIFACT_INSPECTION",
            "harness.artifact-verifier",
            "artifact_evidence_present",
        )
    return (
        "SEMANTIC_REVIEW",
        "harness.semantic-review",
        "verifier_pass",
    )

def compile_task_verification_plan(
    task: Mapping[str, Any],
    *,
    mission_id: str,
) -> TaskVerificationPlan:
    mission_id = str(mission_id or "").strip()
    task_id = str(task.get("task_id") or "").strip()
    if not mission_id or not task_id:
        raise ValueError("task verification requires mission_id and task_id")
    criteria = _texts(task.get("acceptance_criteria"))
    if not criteria:
        expected = str(task.get("expected_output") or "").strip()
        criteria = (
            (f"produce {expected}",)
            if expected
            else ("produce verified task evidence",)
        )

    raw_specs = task.get("verification_specs") or ()
    specs: dict[int, Mapping[str, Any]] = {}
    if not isinstance(raw_specs, (list, tuple)):
        raise ValueError("verification_specs must be a list")
    for raw in raw_specs:
        if not isinstance(raw, Mapping):
            raise ValueError("verification spec must be an object")
        if "status" in raw or "result" in raw or "passed" in raw:
            raise ValueError(
                "verification spec cannot self-attest an outcome"
            )
        index = int(raw.get("criterion_index") or 0)
        if not 1 <= index <= len(criteria):
            raise ValueError("verification criterion_index is invalid")
        if index in specs:
            raise ValueError("duplicate verification criterion_index")
        specs[index] = raw

    default_kind, default_verifier, default_predicate = _default_kind(task)
    steps: list[VerificationStep] = []
    for index, criterion in enumerate(criteria, start=1):
        spec = specs.get(index, {})
        kind = str(
            spec.get("verification_kind") or default_kind
        ).strip().upper()
        if kind not in VERIFICATION_KINDS:
            raise ValueError(
                f"unsupported verification kind: {kind}"
            )
        verifier = str(
            spec.get("verifier_capability") or default_verifier
        ).strip()
        if not verifier:
            raise ValueError("verification verifier capability is required")
        required = _texts(spec.get("required_evidence"))
        if not required:
            evidence_contract = str(
                task.get("evidence_contract") or ""
            ).strip()
            required = (
                (evidence_contract,)
                if evidence_contract
                else ("typed_verification_evidence",)
            )
        success = str(
            spec.get("success_predicate")
            or (
                "human_approved"
                if kind == "HUMAN_GATE"
                else default_predicate
            )
        ).strip()
        failure = str(
            spec.get("failure_predicate")
            or "explicit_verifier_failure"
        ).strip()
        boundary = str(
            spec.get("authority_boundary")
            or (
                "HUMAN"
                if kind == "HUMAN_GATE"
                else "DEEPSEEK_HARNESS"
            )
        ).strip().upper()
        steps.append(
            VerificationStep(
                criterion_id=_criterion_id(task_id, index, criterion),
                criterion=criterion,
                verification_kind=kind,
                verifier_capability=verifier,
                required_evidence=required,
                success_predicate=success,
                failure_predicate=failure,
                authority_boundary=boundary,
                human_gate=kind == "HUMAN_GATE",
            )
        )

    logical = {
        "schema": PLAN_SCHEMA,
        "mission_id": mission_id,
        "task_id": task_id,
        "steps": [step.to_dict() for step in steps],
        "human_gate_required": any(step.human_gate for step in steps),
        "terminal_success_requires_all_steps": True,
        "no_agent_self_attestation": True,
        "authority": "DEEPSEEK_HARNESS",
    }
    return TaskVerificationPlan(
        mission_id=mission_id,
        task_id=task_id,
        steps=tuple(steps),
        human_gate_required=logical["human_gate_required"],
        terminal_success_requires_all_steps=True,
        no_agent_self_attestation=True,
        authority="DEEPSEEK_HARNESS",
        content_sha256=sha256(_canon(logical)).hexdigest(),
    )

def _evidence_passes(
    step: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    task_result: Mapping[str, Any],
) -> tuple[str, tuple[str, ...], str]:
    authority = str(item.get("authority") or "").upper()
    source = str(item.get("source") or "").upper()
    if authority in {"AGENT", "LLM", "MODEL"} or source in {
        "AGENT_SELF_ATTESTATION",
        "MODEL_SELF_ATTESTATION",
    }:
        return "INCOMPLETE", (), "SELF_ATTESTATION_FORBIDDEN"

    refs = _texts(item.get("evidence_refs"))
    status = str(item.get("status") or "").upper()
    kind = str(step.get("verification_kind") or "")
    if kind != "HUMAN_GATE" and authority != "DEEPSEEK_HARNESS":
        return "INCOMPLETE", refs, "UNTRUSTED_VERIFIER_AUTHORITY"
    if status in {"FAIL", "FAILED", "REJECT"}:
        return "FAIL", refs, "EXPLICIT_VERIFIER_FAILURE"
    if kind == "HUMAN_GATE":
        if authority == "HUMAN" and item.get("human_approved") is True and refs:
            return "PASS", refs, "HUMAN_APPROVAL_OBSERVED"
        return "WAITING_HUMAN", refs, "HUMAN_APPROVAL_REQUIRED"
    if kind == "ARTIFACT_INSPECTION":
        output_refs = _texts(task_result.get("output_artifact_refs"))
        if output_refs and refs:
            return "PASS", refs, "ARTIFACT_EVIDENCE_PRESENT"
        return "INCOMPLETE", refs, "ARTIFACT_EVIDENCE_MISSING"
    if status in {"PASS", "PASSED", "ACCEPT", "ACCEPTED"} and refs:
        return "PASS", refs, "VERIFIER_PASS"
    return "INCOMPLETE", refs, "VERIFIER_EVIDENCE_MISSING"

def evaluate_task_verification(
    plan: Mapping[str, Any],
    *,
    task_result: Mapping[str, Any],
    verification_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> TaskVerificationResult:
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("TaskVerificationPlan/v1 is required")
    mission_id = str(plan.get("mission_id") or "")
    task_id = str(plan.get("task_id") or "")
    if str(task_result.get("mission_id") or "") != mission_id:
        raise PermissionError("TASK_VERIFICATION_MISSION_ID_DRIFT")
    if str(task_result.get("task_id") or "") != task_id:
        raise PermissionError("TASK_VERIFICATION_TASK_ID_DRIFT")

    supplied = verification_evidence or {}
    results: list[dict[str, Any]] = []
    refs: list[str] = []
    any_fail = False
    any_human = False
    any_incomplete = False
    for step in plan.get("steps") or ():
        cid = str(step.get("criterion_id") or "")
        item = supplied.get(cid, {})
        state, evidence_refs, reason = _evidence_passes(
            step,
            item,
            task_result=task_result,
        )
        refs.extend(ref for ref in evidence_refs if ref not in refs)
        any_fail = any_fail or state == "FAIL"
        any_human = any_human or state == "WAITING_HUMAN"
        any_incomplete = any_incomplete or state == "INCOMPLETE"
        results.append({
            "criterion_id": cid,
            "verification_kind": step.get("verification_kind"),
            "verifier_capability": step.get("verifier_capability"),
            "status": state,
            "reason": reason,
            "evidence_refs": list(evidence_refs),
        })

    if any_fail:
        status = "VERIFIED_FAIL"
    elif any_human:
        status = "WAITING_HUMAN"
    elif any_incomplete or not results:
        status = "TASK_VERIFICATION_INCOMPLETE"
    else:
        status = "VERIFIED_PASS"
    terminal_success = status == "VERIFIED_PASS"
    logical = {
        "schema": RESULT_SCHEMA,
        "mission_id": mission_id,
        "task_id": task_id,
        "status": status,
        "step_results": results,
        "evidence_refs": refs,
        "human_intervention_required": status == "WAITING_HUMAN",
        "terminal_success": terminal_success,
        "authority": "DEEPSEEK_HARNESS",
    }
    return TaskVerificationResult(
        mission_id=mission_id,
        task_id=task_id,
        status=status,
        step_results=tuple(results),
        evidence_refs=tuple(refs),
        human_intervention_required=logical[
            "human_intervention_required"
        ],
        terminal_success=terminal_success,
        authority="DEEPSEEK_HARNESS",
        content_sha256=sha256(_canon(logical)).hexdigest(),
    )
