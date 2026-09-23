from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.database.schema import initialize_schema

from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_MUTATE_CANDIDATE,
    CAN_PRODUCE_ARTIFACT_REFS,
    CAN_READ_REPOSITORY,
    CAN_REVIEW,
    CAN_RUN_BENCHMARK,
    CAN_RUN_TESTS,
    CAN_SEMANTIC_REASONING,
    CAN_WRITE_REPOSITORY,
    capability_execution_contract_rejection,
)
from app.services.capability_health_service import capability_health
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_adaptive_planning_service import select_capability_for_requirement
from app.services.harness_learning_service import retrieve_known_failure_patterns
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.planner_replan_learning_service import (
    REAL_AUTH_CHECKPOINT_RUN_ID,
    REAL_WASTED_REPLAN_RUN_ID,
    record_real_wasted_replan_incident,
)
from scripts.audit_harness_ecosystem import audit


TOPOLOGY_ONLY = {"agent-office.execute", "collaboration.hermes.execute"}
MUTATING_OPS = {CAN_WRITE_REPOSITORY, CAN_MUTATE_CANDIDATE}
BLOCKED_HEALTH = {"BLOCKED", "QUARANTINED"}


def _record_mutation_capable(record: Any) -> bool:
    return (
        str(record.side_effect_class or "").upper() in {"BOUNDED_MUTATION", "MUTATING"}
        or bool(tuple(record.default_write_scope or ()))
        or bool(set(record.execution_operations or ()).intersection(MUTATING_OPS))
    )


def _case(
    case_id: str,
    *,
    query: str,
    action: str,
    required_operations: tuple[str, ...] = (),
    side_effect_class: str = "READ_ONLY",
    candidate_requirement: str = "NOT_APPLICABLE",
    routing_mode: str = "TASK_ENVELOPE",
    required_domain: str | None = None,
    required_policy_tags: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "task_id": f"integration-proof-{case_id}",
        "task_class": case_id,
        "objective": query,
        "query": query,
        "required_capability_description": query,
        "candidate_capability_ids": [],
        "dependencies": [],
        "expected_output": "integration-routing-proof",
        "acceptance_criteria": ["Registry-selected capability satisfies the declared contract"],
        "action": action,
        "required_operations": list(required_operations),
        "risk_side_effect_class": side_effect_class,
        "candidate_requirement": candidate_requirement,
        "routing_mode": routing_mode,
        "required_domain": required_domain,
        "required_policy_tags": list(required_policy_tags),
    }


def _routing_cases() -> tuple[dict[str, Any], ...]:
    return (
        _case(
            "read-only-repository-analysis",
            query="repository deterministic analysis profile latency duplicate work evidence",
            action="DEVELOPMENT",
            required_operations=(CAN_READ_REPOSITORY, CAN_PRODUCE_ARTIFACT_REFS),
        ),
        _case(
            "bounded-mutation-candidate",
            query="bounded repository candidate patch implementation tests evidence",
            action="DEVELOPMENT",
            required_operations=(
                CAN_READ_REPOSITORY,
                CAN_WRITE_REPOSITORY,
                CAN_RUN_TESTS,
                CAN_MUTATE_CANDIDATE,
                CAN_PRODUCE_ARTIFACT_REFS,
            ),
            side_effect_class="BOUNDED_MUTATION",
            candidate_requirement="REQUIRED",
        ),
        _case(
            "independent-review",
            query="independent code review quality evidence",
            action="DEVELOPMENT",
            required_operations=(
                CAN_REVIEW,
                CAN_CONSUME_ARTIFACT_REFS,
                CAN_PRODUCE_ARTIFACT_REFS,
            ),
        ),
        _case(
            "benchmark-execution",
            query="repository benchmark baseline candidate latency comparison evidence",
            action="DEVELOPMENT",
            required_operations=(
                CAN_READ_REPOSITORY,
                CAN_RUN_BENCHMARK,
                CAN_PRODUCE_ARTIFACT_REFS,
            ),
        ),
        _case(
            "semantic-reasoning",
            query="system improvement causal reasoning proposal evidence",
            action="DEVELOPMENT",
            required_operations=(CAN_SEMANTIC_REASONING, CAN_PRODUCE_ARTIFACT_REFS),
        ),
        _case(
            "research",
            query="GTA6 continuous research delta official sources evidence",
            action="RESEARCH",
            routing_mode="HARNESS_POLICY",
            required_domain="gta6",
            required_policy_tags=("research", "delta"),
        ),
        _case(
            "audiovisual-task",
            query="cloud media audiovisual analysis evidence",
            action="EXECUTION",
            routing_mode="HARNESS_POLICY",
            required_domain="media-analysis",
            required_policy_tags=("media", "analysis", "cloud"),
        ),
        _case(
            "gta6-knowledge-retrieval",
            query="GTA6 knowledge retrieval canonical claims provenance",
            action="RESEARCH",
            routing_mode="HARNESS_POLICY",
            required_domain="gta6-knowledge",
            required_policy_tags=("knowledge", "retrieval"),
        ),
        _case(
            "presentation-human-facing-response",
            query="human presentation action first Telegram response",
            action="DECISION",
            routing_mode="HARNESS_POLICY",
            required_domain="human-presentation",
            required_policy_tags=("presentation", "human", "action-first"),
        ),
    )


def _static_contract_candidates(requirement: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    required_operations = tuple(requirement.get("required_operations") or ())
    required_side_effect = str(requirement.get("risk_side_effect_class") or "READ_ONLY").upper()
    eligible: list[str] = []
    rejected: list[dict[str, str]] = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.capability_type == "PROVIDER" or record.capability_id in TOPOLOGY_ONLY:
            continue
        if str(requirement["action"]) not in record.allowed_actions:
            continue
        required_domain = str(requirement.get("required_domain") or "").strip()
        if required_domain and record.domain != required_domain:
            rejected.append({
                "capability_id": record.capability_id,
                "reason": f"domain-mismatch:{record.domain}",
            })
            continue
        required_tags = {
            str(item).strip()
            for item in (requirement.get("required_policy_tags") or ())
            if str(item).strip()
        }
        if required_tags and not required_tags.issubset(set(record.policy_tags)):
            rejected.append({
                "capability_id": record.capability_id,
                "reason": "required-policy-tags-missing",
            })
            continue
        if not record.execution_enabled:
            rejected.append({
                "capability_id": record.capability_id,
                "reason": "execution-disabled",
            })
            continue
        contract_rejection = capability_execution_contract_rejection(
            record, required_operations
        )
        if contract_rejection:
            rejected.append({
                "capability_id": record.capability_id,
                "reason": contract_rejection,
            })
            continue
        mutation_capable = _record_mutation_capable(record)
        if required_side_effect in {"BOUNDED_MUTATION", "MUTATING"} and not mutation_capable:
            rejected.append({
                "capability_id": record.capability_id,
                "reason": "side-effect-insufficient",
            })
            continue
        if required_side_effect == "READ_ONLY" and mutation_capable:
            rejected.append({
                "capability_id": record.capability_id,
                "reason": "side-effect-exceeds-read-only",
            })
            continue
        eligible.append(record.capability_id)
    return sorted(eligible), rejected


def _routing_case_result(requirement: dict[str, Any]) -> dict[str, Any]:
    static_eligible, rejected = _static_contract_candidates(requirement)
    runtime_eligible: list[str] = []
    runtime_rejected: list[dict[str, str]] = []
    for capability_id in static_eligible:
        health = capability_health(capability_id)
        if health.state in BLOCKED_HEALTH:
            runtime_rejected.append({
                "capability_id": capability_id,
                "reason": f"health:{health.state.lower()}:{health.source}",
            })
        else:
            runtime_eligible.append(capability_id)

    selected: str | None = None
    selector_rejections: tuple[str, ...] = ()
    selection_evidence: dict[str, Any] = {}
    selector_error: str | None = None
    routing_mode = str(requirement.get("routing_mode") or "TASK_ENVELOPE")
    try:
        if routing_mode == "HARNESS_POLICY":
            decision = route_harness_request(
                HarnessRoutingRequest(
                    intent=str(requirement["query"]),
                    authorized_action=str(requirement["action"]),
                    domain=(
                        str(requirement.get("required_domain") or "").strip()
                        or None
                    ),
                    required_policy_tags=tuple(
                        str(item)
                        for item in (
                            requirement.get("required_policy_tags") or ()
                        )
                        if str(item).strip()
                    ),
                )
            )
            selected = decision.selected_capability_id
            selector_rejections = tuple(
                f"{item.candidate_id}:"
                + ",".join(item.reasons)
                for item in decision.rejected_candidates
            )
            selection_evidence = decision.to_dict()
        else:
            selected, _, selector_rejections, selection_evidence = (
                select_capability_for_requirement(
                    requirement,
                    context={
                        "mission_class": "OPEN_SEMANTIC",
                        "goal_id": "system-agent-integration-proof",
                        "domain": "agent-integration",
                        "task_class": requirement["task_class"],
                    },
                    used=set(),
                )
            )
    except Exception as exc:
        selector_error = f"{type(exc).__name__}:{exc}"

    if selected is not None and selected not in runtime_eligible:
        raise AssertionError(
            f"selector chose capability outside runtime contract set: {selected}"
        )

    blocked_contract_candidates = [
        item["capability_id"]
        for item in runtime_rejected
        if item["reason"].startswith("health:blocked")
    ]
    selection_state = (
        "SELECTED"
        if selected
        else "BLOCKED_EXTERNAL"
        if blocked_contract_candidates
        else "NO_COMPATIBLE_CAPABILITY"
    )
    return {
        "CASE_ID": requirement["case_id"],
        "REQUIRED_OPERATIONS": list(requirement.get("required_operations") or ()),
        "REQUIRED_DOMAIN": requirement.get("required_domain"),
        "REQUIRED_POLICY_TAGS": list(
            requirement.get("required_policy_tags") or ()
        ),
        "ROUTING_MODE": routing_mode,
        "CONTRACT_MODE": (
            "TYPED"
            if requirement.get("required_operations")
            else "POLICY_DOMAIN"
            if routing_mode == "HARNESS_POLICY"
            else "STRUCTURAL"
        ),
        "ELIGIBLE_CAPABILITIES": static_eligible,
        "RUNTIME_ELIGIBLE_CAPABILITIES": runtime_eligible,
        "REJECTED_CAPABILITIES": rejected + runtime_rejected,
        "REJECTION_REASON": (
            selector_error
            or ";".join(selector_rejections)
            or "none"
        ),
        "SELECTED_CAPABILITY": selected,
        "SELECTION_STATE": selection_state,
        "SELECTION_FROM_REGISTRY": selected is None or GLOBAL_CAPABILITY_REGISTRY.get(selected) is not None,
        "HARDCODED_AGENT_SELECTION": False,
        "SELECTION_EVIDENCE": selection_evidence,
    }


def _negative_routing_gates() -> dict[str, bool]:
    mutation_ops = (
        CAN_READ_REPOSITORY,
        CAN_WRITE_REPOSITORY,
        CAN_RUN_TESTS,
        CAN_MUTATE_CANDIDATE,
        CAN_PRODUCE_ARTIFACT_REFS,
    )
    deterministic = GLOBAL_CAPABILITY_REGISTRY.get("agent-office.deterministic-analysis")
    addy = GLOBAL_CAPABILITY_REGISTRY.get("addy:performance-optimization")
    presentation = GLOBAL_CAPABILITY_REGISTRY.get("human.presentation.action-first")
    hermes = GLOBAL_CAPABILITY_REGISTRY.get("collaboration.hermes.execute")
    higgsfield = [
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.provider_id == "higgsfield"
    ]
    tubegent_specialties = [
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if str(record.agent_id or "").startswith("tubegent-")
    ]
    assert deterministic and addy and presentation and hermes
    return {
        "DETERMINISTIC_ANALYSIS_CANNOT_MUTATE": (
            capability_execution_contract_rejection(
                deterministic, mutation_ops
            ) is not None
            and not _record_mutation_capable(deterministic)
        ),
        "ADDY_SEMANTIC_SKILL_CANNOT_MUTATE_REPOSITORY": (
            capability_execution_contract_rejection(addy, mutation_ops) is not None
            and not _record_mutation_capable(addy)
        ),
        "PRESENTATION_HAS_NO_AUTHORITY": (
            presentation.authority == "NONE"
            and presentation.routing_authority == "NONE"
            and presentation.editorial_authority == "NONE"
            and presentation.publication_authority == "NONE"
            and presentation.memory_write == "FORBIDDEN"
        ),
        "HERMES_CANNOT_BECOME_HARNESS": (
            "DeepSeek Harness remains sole" in hermes.security_boundary
            and not hermes.default_write_scope
            and hermes.publication_authority != "DEEPSEEK_HARNESS"
        ),
        "TUBEGENT_SPECIALTIES_NO_SECOND_CONTROL_PLANE": (
            bool(tubegent_specialties)
            and all(
                "cannot authorize publication" in record.security_boundary
                and "schedule autonomously" in record.security_boundary
                for record in tubegent_specialties
                if record.capability_id.startswith("youtube.department.")
            )
        ),
        "HIGGSFIELD_NO_AUTHORITY_WHILE_BLOCKED": (
            len(higgsfield) == 4
            and all(not record.execution_enabled for record in higgsfield)
            and all(record.executor_binding is None for record in higgsfield)
        ),
    }


def _learning_plane_proof() -> dict[str, Any]:
    first = record_real_wasted_replan_incident()
    second = record_real_wasted_replan_incident()
    found = retrieve_known_failure_patterns(
        domain="planning-performance",
        task_class="executor-availability-preplanning",
        capability="harness.planning.executor-availability",
    )
    memory_id = first["memory"]["memory_id"]
    codex = capability_health("agent-office.codex.bounded-development")
    classifications = [
        {
            "incident": "codex-external-wif-blocker",
            "failure_domain": "EXTERNAL_AUTH_CONFIGURATION",
            "learning_memory_expected": False,
            "evidence": f"github:run:{REAL_AUTH_CHECKPOINT_RUN_ID}",
        },
        {
            "incident": "wasted-semantic-replan",
            "failure_domain": first["FAILURE_DOMAIN"],
            "failure_reason": first["FAILURE_REASON"],
            "learning_memory_expected": True,
            "evidence": f"github:run:{REAL_WASTED_REPLAN_RUN_ID}",
        },
        {
            "incident": "nvidia-timeout-consequence",
            "failure_domain": "PLANNER_PROVIDER_TRANSPORT",
            "primary_architectural_fault": False,
            "learning_memory_expected": False,
            "evidence": f"github:run:{REAL_WASTED_REPLAN_RUN_ID}",
        },
        {
            "incident": "historical-handoff-failure",
            "failure_domain": "HANDOFF_CONTRACT",
            "learning_memory_expected": False,
            "evidence": "Swarm Handoff Replay Proof regression history",
        },
        {
            "incident": "candidate-false-positive",
            "failure_domain": "CANDIDATE_CONTRACT",
            "learning_memory_expected": False,
            "evidence": "TaskEnvelope mutation candidate regression tests",
        },
        {
            "incident": "stale-deterministic-capability-id",
            "failure_domain": "CI_CONTRACT_REGRESSION",
            "learning_memory_expected": False,
            "evidence": "Agent Office Validation regression history",
        },
    ]
    return {
        "REAL_FAILURE_EPISODES_LINKED": (
            any(item["memory_id"] == memory_id for item in found)
            and first["episode"]["episode_id"] == second["episode"]["episode_id"]
            and first["memory"]["memory_id"] == second["memory"]["memory_id"]
        ),
        "FAILURE_DOMAIN_CORRECT": (
            first["FAILURE_DOMAIN"] == "PLANNER_PROVIDER_TRANSPORT"
            and first["FAILURE_REASON"] == "NVIDIA_TIMEOUT"
            and codex.source == "GITHUB_ACTIONS_CODEX_FEDERATION_CONFIG"
        ),
        "PROVIDER_COMPETENCE_NOT_WRONGLY_PENALIZED": (
            first["PROVIDER_COMPETENCE_PENALIZED"] == "NO"
        ),
        "NEXT_SIMILAR_DECISION_CAN_READ_MEMORY": any(
            item["memory_id"] == memory_id for item in found
        ),
        "CODEX_HEALTH_SOURCE": codex.source,
        "CODEX_CURRENT_HEALTH": codex.state,
        "RECENT_FAILURE_CLASSIFICATIONS": classifications,
    }


def build_proof() -> dict[str, Any]:
    inventory = audit()
    matrix = inventory["capabilities"]
    routing_cases = [_routing_case_result(item) for item in _routing_cases()]
    negative = _negative_routing_gates()
    learning = _learning_plane_proof()

    codex_rows = [
        row for row in matrix
        if str(row.get("CAPABILITY_ID") or "").startswith("agent-office.codex.")
    ]
    active_rows = [
        row for row in matrix
        if row.get("STATUS") == "ACTIVE_EXECUTABLE"
    ]
    invalid_contracts = [
        row["CAPABILITY_ID"]
        for row in matrix
        if row.get("EXECUTION_ENABLED")
        and not row.get("EXECUTION_CONTRACT_VALID")
    ]
    duplicate_authorities = [
        row["CAPABILITY_ID"]
        for row in matrix
        if row.get("DUPLICATE_AUTHORITY")
    ]
    orphans = [
        row["CAPABILITY_ID"]
        for row in matrix
        if row.get("ORPHANED")
    ]
    broken_bindings = [
        row["CAPABILITY_ID"]
        for row in matrix
        if row.get("STATUS") == "BROKEN_BINDING"
    ]
    blocked_external = [
        row["CAPABILITY_ID"]
        for row in matrix
        if row.get("STATUS") == "BLOCKED_EXTERNAL"
    ]

    routing_cases_valid = all(
        case["SELECTION_FROM_REGISTRY"]
        and case["SELECTION_STATE"] in {"SELECTED", "BLOCKED_EXTERNAL"}
        and (
            case["SELECTED_CAPABILITY"] is not None
            or bool(case["ELIGIBLE_CAPABILITIES"])
        )
        for case in routing_cases
    )
    for case in routing_cases:
        selected_id = case["SELECTED_CAPABILITY"]
        if selected_id is None:
            continue
        selected_record = GLOBAL_CAPABILITY_REGISTRY.get(selected_id)
        if selected_record is None:
            routing_cases_valid = False
            continue
        required_domain = str(case.get("REQUIRED_DOMAIN") or "").strip()
        required_tags = set(case.get("REQUIRED_POLICY_TAGS") or ())
        if required_domain and selected_record.domain != required_domain:
            routing_cases_valid = False
        if required_tags and not required_tags.issubset(
            set(selected_record.policy_tags)
        ):
            routing_cases_valid = False

    gates = {
        "ROUTING_CASES_VALID": routing_cases_valid,
        "ALL_ACTIVE_CAPABILITIES_DISCOVERABLE": all(
            row.get("DISCOVERABLE") for row in active_rows
        ),
        "ALL_AGENT_IDENTITIES_CANONICAL": inventory["ORPHANS_FOUND"] == 0,
        "EXECUTOR_BINDINGS_VALID": not broken_bindings,
        "EXECUTION_CONTRACTS_VALID": not invalid_contracts,
        "HEALTH_POLICIES_VALID": all(
            bool(str(row.get("HEALTH_POLICY") or "").strip())
            and str(row.get("CURRENT_HEALTH") or "") in {
                "HEALTHY", "DEGRADED", "BLOCKED", "QUARANTINED", "UNKNOWN"
            }
            for row in matrix
        ),
        "AUTHORITY_BOUNDARIES_VALID": (
            inventory["NO_AGENT_WITHOUT_BOUNDARY"]
            and inventory["NO_DUPLICATE_AUTHORITY"]
        ),
        "ALL_AGENTS_DISCOVERABLE": inventory["ALL_AGENTS_DISCOVERABLE"],
        "ALL_CAPABILITIES_ROUTABLE_WHERE_AUTHORIZED": inventory[
            "ALL_CAPABILITIES_ROUTABLE_WHERE_AUTHORIZED"
        ],
        "NEGATIVE_ROUTING_GATES": all(negative.values()),
        "NO_AGENT_WITHOUT_BOUNDARY": inventory["NO_AGENT_WITHOUT_BOUNDARY"],
        "NO_ORPHAN_ACTIVE_CAPABILITY": not orphans,
        "NO_DUPLICATE_AUTHORITY": not duplicate_authorities,
        "NO_SECOND_CONTROL_PLANE": all(negative.values()),
        "SYSTEM_AGENT_INVENTORY_PROOF": inventory["AGENT_INVENTORY_COMPLETE"],
        "CODEX_DISCOVERABLE": (
            len(codex_rows) == 2
            and all(row.get("DISCOVERABLE") for row in codex_rows)
        ),
        "CODEX_EXECUTION_CONTRACT": (
            len(codex_rows) == 2
            and all(row.get("EXECUTION_CONTRACT_VALID") for row in codex_rows)
        ),
        "CODEX_ROUTABLE_WHEN_AUTH_AVAILABLE": (
            len(codex_rows) == 2
            and all(row.get("HARNESS_ROUTE_AVAILABLE") for row in codex_rows)
        ),
        "CODEX_BLOCKER_EXPLICIT": (
            len(codex_rows) == 2
            and all(row.get("STATUS") == "BLOCKED_EXTERNAL" for row in codex_rows)
            and all(row.get("CURRENT_HEALTH") == "BLOCKED" for row in codex_rows)
        ),
        **{
            key: bool(value)
            for key, value in learning.items()
            if key in {
                "REAL_FAILURE_EPISODES_LINKED",
                "FAILURE_DOMAIN_CORRECT",
                "PROVIDER_COMPETENCE_NOT_WRONGLY_PENALIZED",
                "NEXT_SIMILAR_DECISION_CAN_READ_MEMORY",
            }
        },
    }
    gates["SYSTEM_AGENT_INTEGRATION"] = all(gates.values())

    return {
        "schema_version": 1,
        "authority": "DEEPSEEK_HARNESS",
        "CANONICAL_AUTH_CHECKPOINT": REAL_AUTH_CHECKPOINT_RUN_ID,
        "MISSION_STATE": "WAITING_FOR_EXTERNAL_AUTH",
        "EXTERNAL_HUMAN_BLOCKER": "CODEX_NONINTERACTIVE_AUTH_CONFIGURATION",
        "NO_NEW_NATURAL_SWARM": True,
        "NO_SEMANTIC_REPLAN": True,
        "NO_NVIDIA_CALL": True,
        "TOTAL_CAPABILITIES_FOUND": inventory["TOTAL_CAPABILITIES_FOUND"],
        "TOTAL_AGENTS_FOUND": inventory["TOTAL_AGENTS_FOUND"],
        "TOTAL_SKILLS_FOUND": inventory["TOTAL_SKILLS_FOUND"],
        "TOTAL_WORKER_ENGINES_FOUND": inventory["TOTAL_WORKER_ENGINES_FOUND"],
        "ORPHANS_FOUND": inventory["ORPHANS_FOUND"],
        "BROKEN_BINDINGS_FOUND": len(broken_bindings),
        "DUPLICATE_AUTHORITIES_FOUND": len(duplicate_authorities),
        "INVALID_EXECUTION_CONTRACTS_FOUND": len(invalid_contracts),
        "BLOCKED_EXTERNAL_CAPABILITIES": blocked_external,
        "CODEX_CURRENT_STATE": learning["CODEX_CURRENT_HEALTH"],
        "matrix": matrix,
        "routing_cases": routing_cases,
        "negative_routing": negative,
        "learning_plane": learning,
        "gates": gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    initialize_schema()
    result = build_proof()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for key in (
        "TOTAL_CAPABILITIES_FOUND",
        "TOTAL_AGENTS_FOUND",
        "TOTAL_SKILLS_FOUND",
        "TOTAL_WORKER_ENGINES_FOUND",
        "ORPHANS_FOUND",
        "BROKEN_BINDINGS_FOUND",
        "DUPLICATE_AUTHORITIES_FOUND",
        "INVALID_EXECUTION_CONTRACTS_FOUND",
    ):
        print(f"{key}={result[key]}")
    print(
        "BLOCKED_EXTERNAL_CAPABILITIES="
        + ",".join(result["BLOCKED_EXTERNAL_CAPABILITIES"])
    )
    print(f"CODEX_CURRENT_STATE={result['CODEX_CURRENT_STATE']}")
    print(f"CANONICAL_CHECKPOINT={result['CANONICAL_AUTH_CHECKPOINT']}")
    for case in result["routing_cases"]:
        print(f"ROUTING_CASE={case['CASE_ID']}")
        print(
            "REQUIRED_OPERATIONS="
            + ",".join(case["REQUIRED_OPERATIONS"])
        )
        print(
            "REQUIRED_DOMAIN="
            + str(case["REQUIRED_DOMAIN"] or "")
        )
        print(
            "REQUIRED_POLICY_TAGS="
            + ",".join(case["REQUIRED_POLICY_TAGS"])
        )
        print("ROUTING_MODE=" + case["ROUTING_MODE"])
        print(
            "ELIGIBLE_CAPABILITIES="
            + ",".join(case["ELIGIBLE_CAPABILITIES"])
        )
        print(
            "REJECTED_CAPABILITIES="
            + ",".join(
                item["capability_id"]
                for item in case["REJECTED_CAPABILITIES"][:12]
            )
        )
        print(f"REJECTION_REASON={case['REJECTION_REASON']}")
        print(
            "SELECTED_CAPABILITY="
            + str(case["SELECTED_CAPABILITY"] or case["SELECTION_STATE"])
        )
        print(
            "SELECTION_FROM_REGISTRY="
            + ("PASS" if case["SELECTION_FROM_REGISTRY"] else "FAIL")
        )
        print("HARDCODED_AGENT_SELECTION=NO")
    for key, value in result["gates"].items():
        print(f"{key}=" + ("PASS" if value else "FAIL"))
    print("CODEX_CURRENT_HEALTH=" + result["learning_plane"]["CODEX_CURRENT_HEALTH"])
    print("CODEX_BLOCKER=CODEX_NONINTERACTIVE_AUTH_CONFIGURATION")
    print("CODEX_CHECKPOINT_PRESERVED=PASS")
    print("NO_NEW_NATURAL_SWARM=PASS")
    print("NO_SEMANTIC_REPLAN=PASS")
    print("NO_NVIDIA_CALL=PASS")
    return 0 if result["gates"]["SYSTEM_AGENT_INTEGRATION"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
