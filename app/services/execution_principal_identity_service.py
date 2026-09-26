from __future__ import annotations
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.services.agent_session_service import stable_agent_instance_id
from app.services.harness_worker_registry_bridge import manifest_from_capability_registry

SCHEMA = "ExecutionPrincipalIdentity/v1"

def _bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")

@dataclass(frozen=True)
class ExecutionPrincipalIdentity:
    mission_id: str
    plan_id: str
    plan_revision: int | None
    task_id: str
    attempt_id: str | None
    functional_role: str
    execution_kind: str
    capability_id: str
    capability_version: str
    agent_id: str
    skill_id: str | None
    worker_id: str
    worker_build_id: str
    agent_instance_id: str
    executor_binding: str
    authorization_id: str
    session_ref: str
    session_content_sha256: str
    runtime_revision: str | None = None
    orchestration_version: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    authority: str = "NONE"
    schema: str = SCHEMA
    content_sha256: str = ""

    def sealed(self) -> "ExecutionPrincipalIdentity":
        raw = asdict(self)
        raw.pop("content_sha256", None)
        return ExecutionPrincipalIdentity(**{**raw, "content_sha256": sha256(_bytes(raw)).hexdigest()})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def principal_from_task(*, mission_id: str, plan_id: str, task: dict[str, Any],
                        authorization_id: str, session: dict[str, Any],
                        worker_build_id: str, plan_revision: int | None = None,
                        attempt_id: str | None = None, runtime_revision: str | None = None,
                        orchestration_version: str | None = None) -> ExecutionPrincipalIdentity:
    capability_id = str(task.get("capability_id") or "")
    manifest = manifest_from_capability_registry(capability_id, worker_build_id=worker_build_id)
    agent_id = str(task.get("selected_agent_id") or manifest.agent_id)
    skill_id = str(task.get("selected_skill_id") or "") or None
    expected_instance = stable_agent_instance_id(
        mission_id=mission_id, task_id=str(task.get("task_id") or ""),
        capability_id=capability_id, agent_id=agent_id, skill_id=skill_id,
    )
    observed_instance = str(session.get("AGENT_INSTANCE_ID") or "")
    if observed_instance != expected_instance:
        raise PermissionError("EXECUTION_PRINCIPAL_AGENT_SESSION_MISMATCH")
    session_ref = str(session.get("CHECKPOINT_REF") or "")
    if not session_ref:
        raise PermissionError("EXECUTION_PRINCIPAL_SESSION_REF_MISSING")
    session_sha = sha256(_bytes(session)).hexdigest()
    return ExecutionPrincipalIdentity(
        mission_id=mission_id, plan_id=plan_id, plan_revision=plan_revision,
        task_id=str(task.get("task_id") or ""), attempt_id=attempt_id,
        functional_role=str(task.get("functional_role") or "GENERAL").upper(),
        execution_kind=str(manifest.execution_kinds[0] if manifest.execution_kinds else "").upper(),
        capability_id=capability_id, capability_version=str(task.get("capability_version") or "1"),
        agent_id=agent_id, skill_id=skill_id, worker_id=manifest.worker_id,
        worker_build_id=manifest.worker_build_id, agent_instance_id=observed_instance,
        executor_binding=manifest.executor_binding, authorization_id=str(authorization_id),
        session_ref=session_ref, session_content_sha256=session_sha,
        runtime_revision=runtime_revision, orchestration_version=orchestration_version,
        provider_id=str(session.get("PROVIDER_ID") or "") or None,
        model_id=str(session.get("MODEL_ID") or "") or None,
    ).sealed()

def persist_execution_principal(principal: ExecutionPrincipalIdentity, *, artifact_dir: Path) -> dict[str, Any]:
    root=Path(artifact_dir); target=root/"execution-principals"/f"{principal.task_id}-{principal.content_sha256}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(principal.to_dict(), ensure_ascii=False, sort_keys=True)+"\n", encoding="utf-8")
    return {"ref":"artifact:"+target.relative_to(root).as_posix(),"sha256":principal.content_sha256}
