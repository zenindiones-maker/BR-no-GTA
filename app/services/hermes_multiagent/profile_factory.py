from __future__ import annotations

from hashlib import sha256
import re
from typing import Mapping

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_collaboration_service import CollaborationPlan, RoutedCollaborationTask

from .contracts import HERMES_COORDINATION_TOOLS, HermesRuntimeProfile, HermesProfileIdentity


_PROFILE_RE = re.compile(r"[^a-z0-9-]+")


def _slug(value: str) -> str:
    value = _PROFILE_RE.sub("-", value.strip().lower().replace("_", "-")).strip("-")
    return value[:60] or "worker"


def _task_scoped_profile_name(*, runtime_role: str, task_id: str) -> str:
    role = _slug(runtime_role)
    if role.startswith("hermes-"):
        role = role.removeprefix("hermes-") or "worker"
    task = _slug(task_id)
    digest = sha256(task_id.encode("utf-8")).hexdigest()[:8]
    scoped = _slug(f"{role[:30]}-{task[:16]}-{digest}")
    return f"hermes-{scoped}"


class HermesProfileFactory:
    """Project Harness-routed work into Hermes runtime identities.

    The Global Capability Registry remains canonical. Runtime role names only
    label a worker lane for one mission and never define capabilities, actions,
    executors, or authority.
    """

    def __init__(self, *, registry=GLOBAL_CAPABILITY_REGISTRY) -> None:
        self.registry = registry

    def project_task(
        self,
        task: RoutedCollaborationTask,
        *,
        runtime_role: str | None = None,
    ) -> HermesRuntimeProfile:
        record = self.registry.get(task.capability_id)
        if record is None:
            raise ValueError(f"unknown routed capability: {task.capability_id}")
        if record.executor_binding != task.selected_executor_binding:
            raise PermissionError("Hermes profile projection executor drift")
        if record.agent_id != task.selected_agent_id:
            raise PermissionError("Hermes profile projection agent drift")
        if record.skill_id != task.selected_skill_id:
            raise PermissionError("Hermes profile projection skill drift")
        if task.action not in record.allowed_actions:
            raise PermissionError("Hermes profile task action is not Registry-authorized")

        role = _slug(
            runtime_role
            or task.selected_agent_id
            or f"{record.domain}-worker"
        )
        profile_name = _task_scoped_profile_name(
            runtime_role=role,
            task_id=task.task_id,
        )
        return HermesRuntimeProfile(
            profile_name=profile_name,
            task_id=task.task_id,
            runtime_role=role,
            capability_id=task.capability_id,
            domain=record.domain,
            action=task.action,
            canonical_agent_id=record.agent_id,
            canonical_skill_id=record.skill_id,
            executor_binding=str(record.executor_binding or ""),
            input_contract=record.input_contract,
            output_contract=record.output_contract,
            evidence_contract=str(record.evidence_contract or ""),
            evidence_expectations=task.evidence_expectations,
            allowed_tools=HERMES_COORDINATION_TOOLS,
        )

    def identity_for_task(self, task: RoutedCollaborationTask, *, mission_id: str, runtime_role: str | None = None, profile_home: str, worker_build_id: str, attempt_id: str | None = None) -> HermesProfileIdentity:
        profile = self.project_task(task, runtime_role=runtime_role)
        role = profile.runtime_role
        description = f"{role} executes {profile.capability_id} only inside an authorized Hermes delegated subgraph."
        return HermesProfileIdentity(
            profile_instance_id=profile.profile_name,
            profile_role=role,
            mission_id=mission_id,
            plan_task_id=task.task_id,
            attempt_id=attempt_id,
            worker_instance_id=f"{mission_id}:{task.task_id}:{attempt_id or 'initial'}",
            description=description,
            profile_home=profile_home,
            worker_build_id=worker_build_id,
            capability_ids=(profile.capability_id,),
        )

    def project_orchestrator(self) -> HermesRuntimeProfile:
        record = self.registry.get("collaboration.hermes.execute")
        if record is None:
            raise RuntimeError("Hermes runtime capability is not registered")
        return HermesRuntimeProfile(
            profile_name="hermes-orchestrator",
            task_id="__mission__",
            runtime_role="hermes-orchestrator",
            capability_id=record.capability_id,
            domain=record.domain,
            action="EXECUTION",
            canonical_agent_id=record.agent_id,
            canonical_skill_id=record.skill_id,
            executor_binding=str(record.executor_binding or ""),
            input_contract=record.input_contract,
            output_contract=record.output_contract,
            evidence_contract=str(record.evidence_contract or ""),
            evidence_expectations=("CollaborationPlan fidelity", "board lifecycle evidence"),
            allowed_tools=HERMES_COORDINATION_TOOLS,
        )

    def project_plan(
        self,
        plan: CollaborationPlan,
        *,
        role_by_task: Mapping[str, str] | None = None,
    ) -> tuple[HermesRuntimeProfile, ...]:
        roles = dict(role_by_task or {})
        unknown = set(roles) - {task.task_id for task in plan.tasks}
        if unknown:
            raise PermissionError(f"Hermes runtime role references unknown plan tasks: {sorted(unknown)}")
        profiles = tuple(
            self.project_task(task, runtime_role=roles.get(task.task_id))
            for task in plan.tasks
        )
        names = [profile.profile_name for profile in profiles]
        if len(names) != len(set(names)):
            raise ValueError("Hermes runtime profile names must be unique within a mission")
        return profiles

