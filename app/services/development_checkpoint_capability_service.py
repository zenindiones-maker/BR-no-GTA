from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.development_continuity_policy_service import validate_recovery_ref
from app.services.development_recovery_checkpoint_service import DevelopmentRecoveryCheckpointService
from app.services.harness_authorization_service import validate_harness_authorization


CAPABILITY_ID = "development.checkpoint.persist"


def execute_development_checkpoint_persist_capability(
    *,
    authorization: Any,
    repo_root: str | Path,
    ledger: dict[str, Any],
    checkpoint_request: dict[str, Any],
) -> dict[str, Any]:
    request = dict(checkpoint_request)
    recovery_ref = validate_recovery_ref(str(request.get("recovery_ref") or ""))
    auth = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=CAPABILITY_ID,
    )
    if str(request.get("mission_id") or "") != str(ledger.get("mission_id") or ""):
        raise ValueError("checkpoint mission_id must match DevelopmentProgressLedger")
    service = DevelopmentRecoveryCheckpointService(Path(repo_root))
    return service.persist(
        ledger=ledger,
        mission_id=str(request["mission_id"]),
        task_id=str(request["task_id"]),
        checkpoint_kind=str(request["checkpoint_kind"]),
        canonical_branch=str(request["canonical_branch"]),
        canonical_base_sha=str(request["canonical_base_sha"]),
        recovery_ref=recovery_ref,
        workspace_id=str(request["workspace_id"]),
        sprite_id=(None if request.get("sprite_id") is None else str(request["sprite_id"])),
        runtime_namespace=str(request["runtime_namespace"]),
        agent_execution_identity=str(request["agent_execution_identity"]),
        authorization_id=auth.authorization_id,
        included_paths=[str(x) for x in request.get("included_paths", [])],
        excluded_paths=[str(x) for x in request.get("excluded_paths", [])],
        side_effect_state=dict(request.get("side_effect_state") or {}),
        failure_state=dict(request.get("failure_state") or {}),
        resume_instructions=request.get("resume_instructions"),
        expected_previous_remote_oid=request.get("expected_previous_remote_oid"),
    )
