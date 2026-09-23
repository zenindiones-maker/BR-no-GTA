from __future__ import annotations
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

TASK_RESULT_ENVELOPE_SCHEMA = "task-result-envelope/v1"

def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value

def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")

def _summary(result: Any) -> str:
    value = _jsonable(result)
    candidates = []
    if isinstance(value, dict):
        nested = value.get("result")
        if isinstance(nested, dict):
            candidates += [nested.get("summary"), nested.get("output"), nested.get("message")]
        candidates += [value.get("summary"), value.get("output"), value.get("message")]
    for candidate in candidates:
        text = " ".join(str(candidate or "").split()).strip()
        if text:
            return text[:4000]
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:4000]

def _collect_refs(result: Any):
    outputs, evidence, metrics = [], [], []
    def add(target, value):
        if isinstance(value, (list, tuple, set)):
            for item in value:
                add(target, item)
            return
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)
    def walk(value):
        if isinstance(value, dict):
            for raw_key, item in value.items():
                key = str(raw_key).casefold()
                if key in {"candidate_sha", "candidate_commit"}:
                    text = str(item or "").strip()
                    if text:
                        add(outputs, "git-commit:" + text)
                elif key in {
                    "candidate_diff_ref",
                    "patch_ref",
                    "candidate_patch_ref",
                    "output_ref",
                    "output_refs",
                    "output_path",
                    "artifact_ref",
                    "artifact_refs",
                }:
                    add(outputs, item)
                if key in {"evidence_ref", "evidence_refs", "input_refs"}:
                    add(evidence, item)
                if key in {"metrics_ref", "metrics_refs", "performance_ref", "performance_refs"} or ("metric" in key and key.endswith("_ref")):
                    add(metrics, item)
                walk(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)
    walk(_jsonable(result))
    return tuple(outputs), tuple(evidence), tuple(metrics)

@dataclass(frozen=True)
class TaskResultEnvelope:
    schema: str
    mission_id: str
    task_id: str
    capability_id: str
    agent_id: str | None
    skill_id: str | None
    executor_binding: str
    status: str
    started_at: str
    completed_at: str
    elapsed_ms: float
    result_summary: str
    result_payload: Any
    output_artifact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    metrics_refs: tuple[str, ...]
    source_task_ids: tuple[str, ...]
    authorization_lineage_ref: str
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def build_task_result_envelope(*, mission_id: str, task_id: str, capability_id: str,
                               agent_id: str | None, skill_id: str | None,
                               executor_binding: str, status: str, started_at: str,
                               completed_at: str, elapsed_ms: float, result: Any,
                               source_task_ids, authorization_id: str) -> TaskResultEnvelope:
    normalized = _jsonable(result)
    output_refs, evidence_refs, metrics_refs = _collect_refs(normalized)
    base = {
        "schema": TASK_RESULT_ENVELOPE_SCHEMA,
        "mission_id": str(mission_id),
        "task_id": str(task_id),
        "capability_id": str(capability_id),
        "agent_id": str(agent_id) if agent_id else None,
        "skill_id": str(skill_id) if skill_id else None,
        "executor_binding": str(executor_binding or ""),
        "status": str(status or ""),
        "started_at": str(started_at),
        "completed_at": str(completed_at),
        "elapsed_ms": round(float(elapsed_ms), 3),
        "result_summary": _summary(normalized),
        "result_payload": normalized,
        "output_artifact_refs": output_refs,
        "evidence_refs": evidence_refs,
        "metrics_refs": metrics_refs,
        "source_task_ids": tuple(dict.fromkeys(str(x) for x in source_task_ids if str(x))),
        "authorization_lineage_ref": "authorization:" + str(authorization_id),
    }
    return TaskResultEnvelope(**base, content_sha256=sha256(_canonical_bytes(base)).hexdigest())

def persist_task_result_envelope(envelope: TaskResultEnvelope, *, artifact_dir: Path, index: int) -> dict[str, Any]:
    root = Path(artifact_dir)
    (root / "task-results").mkdir(parents=True, exist_ok=True)
    relative = Path("task-results") / f"{envelope.task_id}-{index}.json"
    payload = envelope.to_dict()
    (root / relative).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {**payload, "task_result_ref": "artifact:" + relative.as_posix()}

def load_task_result_envelope(*, artifact_dir: Path, task_result_ref: str) -> dict[str, Any]:
    if not str(task_result_ref).startswith("artifact:"):
        raise ValueError("TaskResultEnvelope ref must use artifact: scheme")
    root = Path(artifact_dir).resolve()
    target = (root / str(task_result_ref)[len("artifact:"):]).resolve()
    if root not in target.parents:
        raise PermissionError("TaskResultEnvelope ref escaped artifact directory")
    if not target.is_file():
        raise FileNotFoundError(str(target))
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("schema") != TASK_RESULT_ENVELOPE_SCHEMA:
        raise ValueError("TaskResultEnvelope schema mismatch")
    expected = str(payload.get("content_sha256") or "")
    check = dict(payload)
    check.pop("content_sha256", None)
    if not expected or sha256(_canonical_bytes(check)).hexdigest() != expected:
        raise PermissionError("TaskResultEnvelope content hash mismatch")
    return payload

class DependencyArtifactMissing(RuntimeError):
    def __init__(self, *, task_id: str, dependency_task_id: str,
                 expected_artifact_type: str = TASK_RESULT_ENVELOPE_SCHEMA,
                 resolution_attempts=()):
        self.task_id = task_id
        self.dependency_task_id = dependency_task_id
        self.expected_artifact_type = expected_artifact_type
        self.resolution_attempts = tuple(resolution_attempts)
        super().__init__(
            "DEPENDENCY_ARTIFACT_MISSING:"
            f"TASK_ID={task_id}:MISSING_DEPENDENCY_TASK_ID={dependency_task_id}:"
            f"EXPECTED_ARTIFACT_TYPE={expected_artifact_type}:"
            f"RESOLUTION_ATTEMPTS={','.join(self.resolution_attempts) or 'none'}"
        )
