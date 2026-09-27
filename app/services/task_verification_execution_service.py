from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from app.services.task_output_contract_service import (
    validate_task_output_contract,
)
from app.services.task_verification_service import (
    evaluate_task_verification,
)


EVIDENCE_SCHEMA = "TaskVerificationEvidence/v1"
EXECUTION_SCHEMA = "TaskVerificationExecution/v1"


def _canon(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _task_value(task: Any, key: str, default: Any = None) -> Any:
    if isinstance(task, Mapping):
        return task.get(key, default)
    return getattr(task, key, default)


def _write_hashed_json(
    *,
    artifact_dir: Path,
    relative: Path,
    payload: dict[str, Any],
) -> tuple[str, str]:
    logical = dict(payload)
    logical.pop("content_sha256", None)
    digest = sha256(_canon(logical)).hexdigest()
    body = {**logical, "content_sha256": digest}
    target = artifact_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return "artifact:" + relative.as_posix(), digest


def _local_artifact_exists(
    artifact_dir: Path,
    ref: str,
) -> bool:
    if not str(ref).startswith("artifact:"):
        return False
    root = artifact_dir.resolve()
    target = (
        root / str(ref)[len("artifact:"):].lstrip("/")
    ).resolve()
    if target == root or root not in target.parents:
        return False
    return target.is_file()


def _schema_evidence(
    *,
    task: Any,
    task_result: Mapping[str, Any],
    criterion_id: str,
    artifact_dir: Path,
    index: int,
) -> dict[str, Any]:
    validation = validate_task_output_contract(
        functional_role=_task_value(task, "functional_role", "GENERAL"),
        result=task_result.get("result_payload"),
    )
    status = (
        "PASS"
        if validation.required and validation.final_output_valid
        else "FAIL"
        if validation.required
        else "INCOMPLETE"
    )
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "mission_id": str(task_result.get("mission_id") or ""),
        "task_id": str(task_result.get("task_id") or ""),
        "criterion_id": criterion_id,
        "verification_kind": "SCHEMA_VALIDATION",
        "verifier_capability": "harness.task-output-schema-validator",
        "authority": "DEEPSEEK_HARNESS",
        "source": "TRUSTED_TASK_OUTPUT_CONTRACT_VALIDATOR",
        "status": status,
        "validation": validation.to_dict(),
    }
    relative = (
        Path("task-verification-evidence")
        / f"{payload['task_id']}-{index}-{criterion_id}.json"
    )
    ref, digest = _write_hashed_json(
        artifact_dir=artifact_dir,
        relative=relative,
        payload=payload,
    )
    return {
        "status": status,
        "authority": "DEEPSEEK_HARNESS",
        "source": payload["source"],
        "evidence_refs": [ref],
        "evidence_sha256": digest,
    }


def _artifact_evidence(
    *,
    task_result: Mapping[str, Any],
    criterion_id: str,
    artifact_dir: Path,
    index: int,
) -> dict[str, Any]:
    refs = tuple(dict.fromkeys(
        str(item).strip()
        for item in (
            task_result.get("output_artifact_refs") or ()
        )
        if str(item).strip()
    ))
    local_refs = tuple(
        ref for ref in refs
        if ref.startswith("artifact:")
    )
    verified = bool(refs) and len(local_refs) == len(refs) and all(
        _local_artifact_exists(artifact_dir, ref)
        for ref in local_refs
    )
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "mission_id": str(task_result.get("mission_id") or ""),
        "task_id": str(task_result.get("task_id") or ""),
        "criterion_id": criterion_id,
        "verification_kind": "ARTIFACT_INSPECTION",
        "verifier_capability": "harness.artifact-verifier",
        "authority": "DEEPSEEK_HARNESS",
        "source": "TRUSTED_LOCAL_ARTIFACT_INSPECTOR",
        "status": "PASS" if verified else "INCOMPLETE",
        "observed_output_refs": list(refs),
        "verified_local_refs": list(local_refs) if verified else [],
    }
    relative = (
        Path("task-verification-evidence")
        / f"{payload['task_id']}-{index}-{criterion_id}.json"
    )
    ref, digest = _write_hashed_json(
        artifact_dir=artifact_dir,
        relative=relative,
        payload=payload,
    )
    return {
        "status": payload["status"],
        "authority": "DEEPSEEK_HARNESS",
        "source": payload["source"],
        "evidence_refs": [ref],
        "evidence_sha256": digest,
    }


def execute_trusted_task_verification(
    *,
    task: Any,
    task_result: Mapping[str, Any],
    artifact_dir: str | Path,
    index: int,
) -> dict[str, Any]:
    root = Path(artifact_dir)
    plan = dict(_task_value(task, "verification_plan", {}) or {})
    if plan.get("schema") != "TaskVerificationPlan/v1":
        raise PermissionError(
            "TaskProtocol/vNext requires TaskVerificationPlan/v1"
        )
    if plan.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError(
            "task verification plan escaped Harness authority"
        )

    evidence: dict[str, dict[str, Any]] = {}
    for step in plan.get("steps") or ():
        if not isinstance(step, Mapping):
            raise ValueError("task verification step must be an object")
        criterion_id = str(step.get("criterion_id") or "").strip()
        kind = str(
            step.get("verification_kind") or ""
        ).strip().upper()
        if not criterion_id:
            raise ValueError("task verification criterion_id is required")
        if kind == "SCHEMA_VALIDATION":
            evidence[criterion_id] = _schema_evidence(
                task=task,
                task_result=task_result,
                criterion_id=criterion_id,
                artifact_dir=root,
                index=index,
            )
        elif kind == "ARTIFACT_INSPECTION":
            evidence[criterion_id] = _artifact_evidence(
                task_result=task_result,
                criterion_id=criterion_id,
                artifact_dir=root,
                index=index,
            )

    result = evaluate_task_verification(
        plan,
        task_result=task_result,
        verification_evidence=evidence,
    )
    relative = (
        Path("task-verification")
        / f"{result.task_id}-{index}.json"
    )
    ref, persisted_hash = _write_hashed_json(
        artifact_dir=root,
        relative=relative,
        payload=result.to_dict(),
    )
    if persisted_hash != result.content_sha256:
        raise PermissionError(
            "TaskVerificationResult content hash drift"
        )
    return {
        "schema": EXECUTION_SCHEMA,
        **result.to_dict(),
        "verification_ref": ref,
        "verification_evidence": evidence,
        "NO_AGENT_SELF_ATTESTED_SUCCESS": True,
        "HARNESS_RETAINS_AUTHORITY": True,
    }
