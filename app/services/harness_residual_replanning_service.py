from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any
from app.services.harness_executor_availability_service import evaluate_typed_requirement_feasibility

@dataclass(frozen=True)
class ResidualTaskRequirements:
    parent_task_id: str
    task_id: str
    task_class: str
    functional_role: str
    required_operations: tuple[str,...]
    required_input_artifact_schemas: tuple[str,...]
    expected_output_schema: str
    side_effect_class: str
    mutation_requirement: str
    review_requirement: str
    dependency_refs: tuple[str,...]
    already_completed_work_refs: tuple[str,...]
    forbidden_capabilities: tuple[dict[str,str],...]
    eligibility_snapshot_ref: str

    def to_task(self)->dict[str,Any]:
        return {
            "parent_task_id":self.parent_task_id,"task_id":self.task_id,
            "task_class":self.task_class,"functional_role":self.functional_role,
            "action":"DEVELOPMENT","domain":"development",
            "required_domains":["development"],
            "required_operations":list(self.required_operations),
            "expected_output":self.expected_output_schema,
            "risk_side_effect_class":self.side_effect_class,
            "candidate_requirement":self.mutation_requirement,
            "dependencies":list(self.dependency_refs),
            "input_refs":list(self.already_completed_work_refs),
        }

def resolve_residual_task(requirements: ResidualTaskRequirements)->dict[str,Any]:
    task=requirements.to_task()
    blocked={str(x.get("capability_id") or "") for x in requirements.forbidden_capabilities}
    feasibility=evaluate_typed_requirement_feasibility(task,blocked_capability_ids=blocked)
    candidates=list(feasibility.get("compatible_candidates") or ())
    candidates.sort(key=lambda x:(0 if str(x.get("health_state"))=="HEALTHY" else 1,str(x.get("capability_id"))))
    return {
        "schema":"residual-task-resolution/v1","authority":"DEEPSEEK_HARNESS",
        "requirements":asdict(requirements),"task":task,
        "eligibility":feasibility,"selected":candidates[0] if candidates else None,
        "residual_replan_performed":True,
    }
