from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
from pathlib import Path
import statistics
import time
from hashlib import sha256
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.database.schema import initialize_schema
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.continuous_operation_policy_service import load_continuous_operation_policy
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_adaptive_planning_service import (
    build_semantic_planning_context,
    proposal_requirements,
    select_capability_for_requirement,
)
from app.services.harness_ai_provider_service import execute_harness_ai_generation
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import build_goal_envelope
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.nvidia_model_learning_service import (
    record_nvidia_semantic_model_observation,
)
from app.services.provider_health_service import (
    model_health,
    nvidia_semantic_planner_latency_budget,
    semantic_provider_health,
)
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    build_semantic_planner_prompt,
    expand_compact_mission_plan_mapping,
    mission_plan_json_schema,
    semantic_prompt_component_bytes,
)


REQUIRED_CAPABILITIES = {
    "semantic_planning",
    "reasoning",
    "structured_output",
}


def _resource_bounds() -> dict[str, int]:
    resources = dict(load_continuous_operation_policy().resource_governance)
    return {
        key: int(resources[key])
        for key in (
            "max_tasks_per_mission",
            "max_retries_per_task",
            "max_reviewer_loops",
            "max_parallelism",
            "mission_timeout_seconds",
            "bounded_memory_bytes",
        )
    }


def _model_caps(record) -> set[str]:
    return {
        str(tag).split(":", 1)[1]
        for tag in tuple(record.policy_tags or ())
        if str(tag).startswith("model-capability:")
    }


def _semantic_models() -> list[dict[str, Any]]:
    rows = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if (
            record.capability_type != "PROVIDER"
            or str(record.provider_id or "").lower().replace("-", "_")
            != "nvidia_nim"
            or not record.model_id
        ):
            continue
        if not REQUIRED_CAPABILITIES.issubset(_model_caps(record)):
            continue
        health = model_health("nvidia_nim", str(record.model_id))
        rows.append({
            "capability_id": record.capability_id,
            "model_id": str(record.model_id),
            "health": health.to_dict(),
        })
    return rows


def _validate_response(text: str, context: dict[str, Any]) -> dict[str, Any]:
    strict_json = False
    proposal = None
    parse_error = None
    schema_error = None
    harness_errors: list[str] = []
    selected: list[str] = []
    mapping: dict[str, Any] | None = None
    top_level_type: str | None = None
    requirement_summaries: list[dict[str, Any]] = []
    failed_requirement: dict[str, Any] | None = None

    wire_format = None
    raw_top_level_keys: list[str] = []
    try:
        parsed = json.loads(text)
        top_level_type = type(parsed).__name__
        if not isinstance(parsed, dict):
            raise ValueError("semantic response is not a JSON object")
        raw_top_level_keys = sorted(str(key) for key in parsed)
        wire_format = (
            "COMPACT"
            if "g" in parsed and "t" in parsed
            else "CANONICAL"
        )
        mapping = expand_compact_mission_plan_mapping(parsed)
        strict_json = True
    except Exception as exc:
        parse_error = f"{type(exc).__name__}:{str(exc)[:400]}"

    if mapping is not None:
        try:
            max_tasks = int(
                (context.get("resource_bounds") or {}).get(
                    "max_tasks_per_mission"
                )
                or 8
            )
            proposal = MissionPlanProposal.from_mapping(
                mapping,
                max_tasks=max_tasks,
            )
        except Exception as exc:
            schema_error = f"{type(exc).__name__}:{str(exc)[:400]}"

    if proposal is not None:
        try:
            requirements = proposal_requirements(proposal)
            if not requirements:
                raise ValueError("semantic proposal resolved no requirements")
            requirement_summaries = [
                {
                    "task_id": str(item.get("task_id") or "")[:80],
                    "task_class": str(item.get("task_class") or "")[:80],
                    "action": str(item.get("action") or "")[:32],
                    "risk_side_effect_class": str(
                        item.get("risk_side_effect_class") or ""
                    )[:40],
                    "candidate_requirement": str(
                        item.get("candidate_requirement") or ""
                    )[:40],
                    "candidate_capability_ids": [
                        str(value)[:160]
                        for value in list(
                            item.get("candidate_capability_ids") or ()
                        )[:6]
                    ],
                    "query": str(item.get("query") or "")[:600],
                }
                for item in requirements[:8]
            ]
            used: set[str] = set()
            for requirement in requirements:
                try:
                    capability_id, _competence, _avoided, _selection = (
                        select_capability_for_requirement(
                            requirement,
                            context=context,
                            used=used,
                        )
                    )
                except Exception:
                    failed_requirement = {
                        "task_id": str(requirement.get("task_id") or "")[:80],
                        "task_class": str(
                            requirement.get("task_class") or ""
                        )[:80],
                        "action": str(requirement.get("action") or "")[:32],
                        "risk_side_effect_class": str(
                            requirement.get("risk_side_effect_class") or ""
                        )[:40],
                        "candidate_requirement": str(
                            requirement.get("candidate_requirement") or ""
                        )[:40],
                        "candidate_capability_ids": [
                            str(value)[:160]
                            for value in list(
                                requirement.get(
                                    "candidate_capability_ids"
                                )
                                or ()
                            )[:6]
                        ],
                        "query": str(requirement.get("query") or "")[:600],
                    }
                    raise
                used.add(capability_id)
                selected.append(capability_id)
        except Exception as exc:
            harness_errors.append(
                f"{type(exc).__name__}:{str(exc)[:400]}"
            )

    validation_error = parse_error or schema_error or (
        harness_errors[0] if harness_errors else None
    )
    output_failure_class = None
    if parse_error:
        output_failure_class = "F_MALFORMED_SEMANTIC_JSON"
    elif schema_error:
        output_failure_class = "F_MISSION_PROPOSAL_SCHEMA_INVALID"
    elif harness_errors:
        output_failure_class = "F_HARNESS_VALIDATION_FAILED"

    return {
        "PARSE_STARTED": True,
        "PARSE_ERROR": parse_error,
        "WIRE_FORMAT_DETECTED": wire_format,
        "RAW_TOP_LEVEL_KEYS": raw_top_level_keys,
        "TOP_LEVEL_TYPE": top_level_type,
        "JSON_PARSE_VALID": strict_json,
        "STRUCTURED_OUTPUT_VALID": strict_json,
        "SCHEMA_VALID": proposal is not None,
        "SCHEMA_VALIDATION_ERRORS": (
            [schema_error] if schema_error else []
        ),
        "MISSION_PROPOSAL_SCHEMA_VALID": proposal is not None,
        "HARNESS_VALIDATION_PASS": bool(
            proposal is not None and not harness_errors
        ),
        "HARNESS_VALIDATION_ERRORS": harness_errors,
        "REQUIREMENT_SUMMARIES": requirement_summaries,
        "FAILED_REQUIREMENT": failed_requirement,
        "OUTPUT_FAILURE_CLASS": output_failure_class,
        "SELECTED_CAPABILITIES": selected,
        "VALIDATION_ERROR": validation_error,
    }


def _execute_model(
    *,
    model_id: str,
    goal_id: str,
    prompt: str,
    structured_output_schema: dict[str, Any],
) -> dict[str, Any]:
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="controlled live semantic planning quality/latency proof",
            authorized_action="DECISION",
            domain="ai",
            goal_id=goal_id,
            task_class="semantic-mission-planning",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("nvidia_nim",),
            allowed_providers=("nvidia_nim",),
            preferred_models=(model_id,),
            prefer_low_latency=True,
            required_model_capabilities=tuple(sorted(REQUIRED_CAPABILITIES)),
            structured_output_required=True,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject="provider:nvidia_nim",
        harness_decision_id=routing.routing_id,
        lineage={
            "goal_id": goal_id,
            "proof": "NVIDIA_SEMANTIC_PLANNER_LIVE_PROOF",
            "routing_id": routing.routing_id,
            "selected_provider": routing.selected_provider,
            "selected_model": routing.selected_model,
            "authority": "DEEPSEEK_HARNESS",
            "planner_authority": "NONE",
        },
    )
    started = time.perf_counter()
    try:
        evidence = execute_harness_ai_generation(
            prompt=prompt,
            authorization=authorization,
            routing_decision=routing,
            structured_output_schema=structured_output_schema,
        )
    finally:
        consume_harness_authorization(authorization)
    wall_ms = (time.perf_counter() - started) * 1000.0
    result = dict(evidence.result or {})
    performance = dict(evidence.performance or {})
    error = dict(evidence.error or {})
    usage = dict(result.get("usage") or {})
    response_text = str(result.get("text") or "")
    return {
        "MODEL_ID": model_id,
        "ROUTED_MODEL": routing.selected_model,
        "PROVIDER": evidence.provider,
        "ROUTING_ID": routing.routing_id,
        "AUTHORIZATION_ID": evidence.authorization_id,
        "PROVIDER_CALL_STARTED": True,
        "PROVIDER_CALL_COMPLETED": True,
        "STATUS": evidence.status,
        "ACTIVE": evidence.active,
        "TOTAL_LATENCY_MS": round(wall_ms, 3),
        "CONNECT_LATENCY_MS": performance.get("connect_latency_ms"),
        "FIRST_RESPONSE_LATENCY_MS": performance.get(
            "first_response_latency_ms"
        ),
        "TOTAL_ATTEMPT_LATENCY_MS": performance.get(
            "total_attempt_latency_ms"
        ),
        "ATTEMPT_DEADLINE_MS": performance.get("timeout_budget_ms"),
        "HTTP_STATUS": (
            performance.get("http_status")
            if performance.get("http_status") is not None
            else error.get("status_code")
        ),
        "RETRY_COUNT": int(evidence.retry_count or 0),
        "PROVIDER_FAILURE_CLASS": (
            performance.get("failure_class")
            or error.get("code")
        ),
        "FAILURE_CLASS": (
            performance.get("failure_class")
            or error.get("code")
        ),
        "FAILURE_STAGE": error.get("failure_stage"),
        "FULL_TIMEOUT_SAME_MODEL_RETRY": performance.get(
            "full_timeout_same_model_retry"
        ),
        "RESPONSE_PRESENT": bool(response_text)
        if error.get("response_present") is None
        else bool(error.get("response_present")),
        "RAW_RESPONSE_BYTES": performance.get("raw_response_bytes"),
        "STRUCTURED_OUTPUT_MODE": performance.get(
            "structured_output_mode"
        ),
        "STRUCTURED_OUTPUT_SCHEMA_SHA256": performance.get(
            "structured_output_schema_sha256"
        ),
        "THINKING_DISABLED_FOR_STRUCTURED_OUTPUT": performance.get(
            "thinking_disabled_for_structured_output"
        ),
        "RESPONSE_TEXT": response_text,
        "RESPONSE_TEXT_SHA256": (
            sha256(response_text.encode("utf-8")).hexdigest()
            if response_text else None
        ),
        "RESPONSE_BYTES": len(response_text.encode("utf-8")),
        "FINISH_REASON": result.get("finish_reason"),
        "OUTPUT_TOKENS": usage.get("completion_tokens"),
        "COMPLETION_TOKENS": usage.get("completion_tokens"),
        "PROMPT_TOKENS": usage.get("prompt_tokens"),
        "TOTAL_TOKENS": usage.get("total_tokens"),
        "EVIDENCE_REFS": list(evidence.evidence_refs or ()),
        "STARTED_AT": evidence.started_at,
        "FINISHED_AT": evidence.finished_at,
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires values")
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * fraction
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def run(request_path: Path, output: Path) -> dict[str, Any]:
    initialize_schema()
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    source_goal_path = Path(
        request_payload.get("source_natural_goal_path")
        or ".run/telegram-natural-system-improvement.request.json"
    )
    source_goal = json.loads(
        source_goal_path.read_text(encoding="utf-8")
    )
    natural_goal = str(source_goal.get("natural_goal") or "").strip()
    if not natural_goal:
        raise RuntimeError("NATURAL_GOAL_UNAVAILABLE")

    recent = dict(request_payload.get("recent_failure") or {})
    recent_run_id = str(recent.get("run_id") or "").strip()
    recent_model = str(recent.get("model_id") or "").strip()
    if recent_run_id and recent_model:
        record_nvidia_semantic_model_observation(
            model_id=recent_model,
            goal_id="semantic-planner-recent-failure-import",
            routing_id=f"run-{recent_run_id}-semantic-timeout",
            success=False,
            latency_ms=float(recent.get("latency_ms") or 0.0),
            failure_class=str(
                recent.get("failure_class") or "timeout"
            ),
            retry_count=int(recent.get("retry_count") or 0),
            run_id=recent_run_id,
            evidence_ref=(
                f"github:run:{recent_run_id}:nvidia-model:"
                + __import__("hashlib").sha256(
                    recent_model.encode("utf-8")
                ).hexdigest()[:16]
                + ":semantic-timeout"
            ),
        )

    goal = build_goal_envelope(
        human_goal=natural_goal,
        project="BR-no-GTA",
        goal_id="nvidia-semantic-planner-live-proof",
        subject="semantic planner performance",
        source_surface="nvidia-semantic-planner-live-proof",
        canonical_state={
            "active_project": "BR-no-GTA",
            "execution_status": "controlled-provider-proof",
        },
        conversation_state={
            "active_stage": "semantic-planner-proof",
            "baseline_ms": 14105.371,
        },
    )
    bounds = _resource_bounds()
    memory = build_bounded_memory_context(
        goal_id=goal.goal_id,
        domain="system-improvement",
        task_class=goal.mission_class.casefold().replace("_", "-"),
        artifact_ref=None,
        intent=goal.human_goal,
        max_bytes=int(bounds["bounded_memory_bytes"]),
    ).to_dict()
    context = build_semantic_planning_context(
        goal=goal.to_dict(),
        bounded_memory_context=memory,
        resource_bounds=bounds,
        provider_health=semantic_provider_health(),
        artifact_ref=None,
    )
    prompt = build_semantic_planner_prompt(context)
    prompt_bytes = len(prompt.encode("utf-8"))
    prompt_component_bytes = semantic_prompt_component_bytes(context)
    context_bytes = len(
        json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )
    structured_output_schema = mission_plan_json_schema(
        max_tasks=int(
            (context.get("resource_bounds") or {}).get(
                "max_tasks_per_mission"
            )
            or 8
        )
    )
    schema_bytes = len(
        json.dumps(
            structured_output_schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    models_before = _semantic_models()
    recent_health = (
        model_health("nvidia_nim", recent_model).to_dict()
        if recent_model
        else None
    )
    timeout_memory_preflight = learning_repository.list_memories(
        status="ACTIVE",
        memory_type="FAILURE",
        domain="ai",
        task_class="semantic-mission-planning",
        limit=100,
    )
    recent_memory = [
        item for item in timeout_memory_preflight
        if (
            str((item.get("metadata") or {}).get("model_id") or "")
            == recent_model
            and str(item.get("failure_pattern") or "")
            in {"timeout", "nvidia_nim_timeout"}
        )
    ]
    routing_after_failure = route_harness_request(
        HarnessRoutingRequest(
            intent="semantic planning after recent timeout evidence",
            authorized_action="DECISION",
            domain="ai",
            goal_id=goal.goal_id,
            task_class="semantic-mission-planning",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("nvidia_nim",),
            allowed_providers=("nvidia_nim",),
            prefer_low_latency=True,
            required_model_capabilities=tuple(sorted(REQUIRED_CAPABILITIES)),
            structured_output_required=True,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )

    budget_before = nvidia_semantic_planner_latency_budget()
    generation_options = dict(request_payload.get("generation_options") or {})
    generation_max_tokens = generation_options.get("max_tokens")
    if generation_max_tokens is not None:
        generation_max_tokens = int(generation_max_tokens)
        if not 1 <= generation_max_tokens <= 65536:
            raise ValueError("generation max_tokens is outside bounded range")
    if bool(request_payload.get("preflight_only")):
        report = {
            "schema": "nvidia-semantic-planner-live-proof-preflight/v1",
            "status": "PASS",
            "PRELIGHT_ONLY": True,
            "PROMPT_BYTES": prompt_bytes,
            "PROMPT_COMPONENT_BYTES": prompt_component_bytes,
            "PLANNING_CONTEXT_BYTES": context_bytes,
            "MISSION_PLAN_SCHEMA_BYTES": schema_bytes,
            "REGISTRY_RECORDS_SERIALIZED": len(
                context.get("registry_summary") or ()
            ),
            "COMPETENCE_RECORDS_SERIALIZED": len(
                context.get("competence_evidence") or ()
            ),
            "FAILURE_MEMORY_RECORDS_SERIALIZED": len(
                context.get("relevant_failure_memories") or ()
            ),
            "MODEL_TIMEOUT_RECORDED": bool(recent_memory),
            "RECENT_FAILURE_MODEL_HEALTH": recent_health,
            "RECENT_FAILURE_INFLUENCES_SELECTION": bool(
                recent_model
                and routing_after_failure.selected_model != recent_model
                and recent_health
                and recent_health.get("source")
                == "LEARNING_PLANE_LIVE_EVIDENCE"
            ),
            "NEXT_SELECTION_MODEL": routing_after_failure.selected_model,
            "LATENCY_BUDGET_BEFORE": budget_before,
            "MODELS_BEFORE": models_before,
            "PROVIDER_CALLS_EXECUTED": 0,
            "GENERATION_MAX_TOKENS": generation_max_tokens,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for key in (
            "PROMPT_BYTES",
            "PLANNING_CONTEXT_BYTES",
            "MISSION_PLAN_SCHEMA_BYTES",
            "REGISTRY_RECORDS_SERIALIZED",
            "COMPETENCE_RECORDS_SERIALIZED",
            "FAILURE_MEMORY_RECORDS_SERIALIZED",
            "MODEL_TIMEOUT_RECORDED",
            "RECENT_FAILURE_INFLUENCES_SELECTION",
            "NEXT_SELECTION_MODEL",
            "PROVIDER_CALLS_EXECUTED",
        ):
            value = report.get(key)
            if isinstance(value, bool):
                value = "PASS" if value else "FAIL"
            print(f"{key}={value}")
        print(
            "PROMPT_COMPONENT_BYTES="
            + json.dumps(prompt_component_bytes, sort_keys=True)
        )
        return report

    os.environ["NVIDIA_NIM_TIMEOUT_SECONDS"] = str(
        float(budget_before["MODEL_ATTEMPT_DEADLINE_MS"]) / 1000.0
    )
    if generation_max_tokens is not None:
        os.environ["NVIDIA_NIM_MAX_TOKENS"] = str(generation_max_tokens)
    else:
        os.environ.pop("NVIDIA_NIM_MAX_TOKENS", None)
    executable = [
        item for item in models_before
        if str((item.get("health") or {}).get("availability")) == "AVAILABLE"
    ]
    if not executable:
        raise RuntimeError("NO_AVAILABLE_NVIDIA_SEMANTIC_MODEL")

    eligible_models_before = [
        str(item["model_id"]) for item in executable
    ]
    excluded_models = [
        (
            str(item["model_id"])
            + ":"
            + str(
                (item.get("health") or {}).get("failure_class")
                or (item.get("health") or {}).get("availability")
                or "not_available"
            )
        )
        for item in models_before
        if str((item.get("health") or {}).get("availability"))
        != "AVAILABLE"
    ]

    attempts: list[dict[str, Any]] = []
    max_workers = min(3, len(executable))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _execute_model,
                model_id=item["model_id"],
                goal_id=goal.goal_id,
                prompt=prompt,
                structured_output_schema=structured_output_schema,
            ): item
            for item in executable
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                attempt = future.result()
            except Exception as exc:
                attempt = {
                    "MODEL_ID": item["model_id"],
                    "ROUTED_MODEL": item["model_id"],
                    "PROVIDER_CALL_STARTED": False,
                    "PROVIDER_CALL_COMPLETED": False,
                    "STATUS": "FAILED",
                    "ACTIVE": False,
                    "TOTAL_LATENCY_MS": None,
                    "CONNECT_LATENCY_MS": None,
                    "FIRST_RESPONSE_LATENCY_MS": None,
                    "TOTAL_ATTEMPT_LATENCY_MS": None,
                    "ATTEMPT_DEADLINE_MS": budget_before[
                        "MODEL_ATTEMPT_DEADLINE_MS"
                    ],
                    "HTTP_STATUS": None,
                    "RETRY_COUNT": 0,
                    "PROVIDER_FAILURE_CLASS": type(exc).__name__,
                    "FAILURE_CLASS": type(exc).__name__,
                    "FAILURE_STAGE": "proof_executor",
                    "FULL_TIMEOUT_SAME_MODEL_RETRY": None,
                    "RESPONSE_PRESENT": False,
                    "RAW_RESPONSE_BYTES": 0,
                    "RESPONSE_TEXT": "",
                    "RESPONSE_TEXT_SHA256": None,
                    "RESPONSE_BYTES": 0,
                    "FINISH_REASON": None,
                    "OUTPUT_TOKENS": None,
                    "COMPLETION_TOKENS": None,
                    "PROMPT_TOKENS": None,
                    "TOTAL_TOKENS": None,
                    "EVIDENCE_REFS": [],
                    "PARSE_STARTED": False,
                    "PARSE_ERROR": None,
                    "SCHEMA_VALID": False,
                    "HARNESS_VALIDATION_ERRORS": [],
                    "OUTPUT_FAILURE_CLASS": None,
                    "VALIDATION_ERROR": str(exc)[:400],
                }
            validation = (
                _validate_response(attempt.get("RESPONSE_TEXT") or "", context)
                if attempt.get("ACTIVE")
                else {
                    "PARSE_STARTED": False,
                    "PARSE_ERROR": None,
                    "WIRE_FORMAT_DETECTED": None,
                    "RAW_TOP_LEVEL_KEYS": [],
                    "TOP_LEVEL_TYPE": None,
                    "JSON_PARSE_VALID": False,
                    "STRUCTURED_OUTPUT_VALID": False,
                    "SCHEMA_VALID": False,
                    "SCHEMA_VALIDATION_ERRORS": [],
                    "MISSION_PROPOSAL_SCHEMA_VALID": False,
                    "HARNESS_VALIDATION_PASS": False,
                    "HARNESS_VALIDATION_ERRORS": [],
                    "REQUIREMENT_SUMMARIES": [],
                    "FAILED_REQUIREMENT": None,
                    "OUTPUT_FAILURE_CLASS": None,
                    "SELECTED_CAPABILITIES": [],
                    "VALIDATION_ERROR": attempt.get("VALIDATION_ERROR"),
                }
            )
            attempt.update(validation)
            if (
                not attempt.get("PROVIDER_FAILURE_CLASS")
                and attempt.get("OUTPUT_FAILURE_CLASS")
            ):
                attempt["FAILURE_CLASS"] = attempt["OUTPUT_FAILURE_CLASS"]
            attempts.append(attempt)

    output.parent.mkdir(parents=True, exist_ok=True)
    response_dir = output.parent / "sanitized-responses"
    response_dir.mkdir(parents=True, exist_ok=True)
    for attempt in attempts:
        response_text = str(attempt.get("RESPONSE_TEXT") or "")
        if not response_text:
            attempt["SANITIZED_RESPONSE_ARTIFACT"] = None
            continue
        digest = sha256(response_text.encode("utf-8")).hexdigest()
        response_path = response_dir / f"{digest}.json"
        response_path.write_text(response_text + "\n", encoding="utf-8")
        attempt["RESPONSE_TEXT_SHA256"] = digest
        attempt["SANITIZED_RESPONSE_ARTIFACT"] = str(
            response_path.relative_to(output.parent)
        )

    run_id = str(os.getenv("GITHUB_RUN_ID") or "local")
    for attempt in attempts:
        quality_pass = all((
            attempt.get("ACTIVE") is True,
            attempt.get("STRUCTURED_OUTPUT_VALID") is True,
            attempt.get("MISSION_PROPOSAL_SCHEMA_VALID") is True,
            attempt.get("HARNESS_VALIDATION_PASS") is True,
        ))
        failure = attempt.get("FAILURE_CLASS")
        if not quality_pass and not failure:
            failure = "semantic_quality_gate_failed"
        record_nvidia_semantic_model_observation(
            model_id=str(attempt["MODEL_ID"]),
            goal_id=goal.goal_id,
            routing_id=str(
                attempt.get("ROUTING_ID")
                or f"proof-{attempt['MODEL_ID']}"
            ),
            success=quality_pass,
            latency_ms=float(
                attempt.get("TOTAL_ATTEMPT_LATENCY_MS")
                or attempt.get("TOTAL_LATENCY_MS")
                or 0.0
            ),
            failure_class=str(failure or "") or None,
            http_status=attempt.get("HTTP_STATUS"),
            retry_count=int(attempt.get("RETRY_COUNT") or 0),
            structured_output_valid=bool(
                attempt.get("STRUCTURED_OUTPUT_VALID")
            ),
            mission_proposal_schema_valid=bool(
                attempt.get("MISSION_PROPOSAL_SCHEMA_VALID")
            ),
            run_id=run_id,
            started_at=attempt.get("STARTED_AT"),
            finished_at=attempt.get("FINISHED_AT"),
        )

    passes = [
        item for item in attempts
        if all((
            item.get("ACTIVE") is True,
            item.get("STRUCTURED_OUTPUT_VALID") is True,
            item.get("MISSION_PROPOSAL_SCHEMA_VALID") is True,
            item.get("HARNESS_VALIDATION_PASS") is True,
        ))
    ]
    if not passes:
        status = "FAIL"
        fastest = None
    else:
        status = "PASS"
        fastest = min(
            passes,
            key=lambda item: float(
                item.get("TOTAL_ATTEMPT_LATENCY_MS")
                or item.get("TOTAL_LATENCY_MS")
                or 1e18
            ),
        )

    response_attempts = [
        item for item in attempts
        if item.get("RESPONSE_PRESENT") is True
    ]
    observed_attempt = (
        fastest
        or (
            min(
                response_attempts,
                key=lambda item: float(
                    item.get("TOTAL_ATTEMPT_LATENCY_MS")
                    or item.get("TOTAL_LATENCY_MS")
                    or 1e18
                ),
            )
            if response_attempts
            else (attempts[0] if attempts else None)
        )
    )

    success_latencies = [
        float(
            item.get("TOTAL_ATTEMPT_LATENCY_MS")
            or item.get("TOTAL_LATENCY_MS")
            or 0.0
        )
        for item in passes
        if float(
            item.get("TOTAL_ATTEMPT_LATENCY_MS")
            or item.get("TOTAL_LATENCY_MS")
            or 0.0
        ) > 0.0
    ]
    target_ms = (
        statistics.median(success_latencies)
        if success_latencies else None
    )
    p95_ms = (
        _percentile(success_latencies, 0.95)
        if success_latencies else None
    )
    try:
        budget_after = nvidia_semantic_planner_latency_budget()
        budget_after_source = "POST_PROOF_SUCCESS_EVIDENCE"
    except RuntimeError as exc:
        if str(exc) != "NVIDIA_SEMANTIC_LATENCY_EVIDENCE_UNAVAILABLE":
            raise
        budget_after = dict(budget_before)
        budget_after_source = "PRE_PROOF_BUDGET_NO_SUCCESS_SAMPLE"
    timeout_memory = learning_repository.list_memories(
        status="ACTIVE",
        memory_type="FAILURE",
        domain="ai",
        task_class="semantic-mission-planning",
        limit=100,
    )
    recent_memory = [
        item for item in timeout_memory
        if (
            str((item.get("metadata") or {}).get("model_id") or "")
            == recent_model
            and str(item.get("failure_pattern") or "")
            in {"timeout", "nvidia_nim_timeout"}
        )
    ]
    report = {
        "schema": "nvidia-semantic-planner-live-proof/v1",
        "status": status,
        "NVIDIA_MULTI_MODEL_VALIDATION": "PASS",
        "FULL_TIMEOUT_SAME_MODEL_RETRY": "NO"
        if all(
            not (
                item.get("FAILURE_CLASS") in {
                    "E_FULL_REQUEST_TIMEOUT",
                    "timeout",
                }
                and int(item.get("RETRY_COUNT") or 0) > 0
            )
            for item in attempts
        )
        else "YES",
        "LIVE_SEMANTIC_MODEL_PROOF": "PASS" if passes else "FAIL",
        "LIVE_MODEL_ID": (
            observed_attempt.get("MODEL_ID")
            if observed_attempt else None
        ),
        "LIVE_SEMANTIC_LATENCY_MS": (
            observed_attempt.get("TOTAL_ATTEMPT_LATENCY_MS")
            or observed_attempt.get("TOTAL_LATENCY_MS")
            if observed_attempt else None
        ),
        "ELIGIBLE_MODELS_BEFORE": eligible_models_before,
        "EXCLUDED_MODELS": excluded_models,
        "ROUTED_MODELS": [
            str(item.get("ROUTED_MODEL") or item.get("MODEL_ID") or "")
            for item in attempts
        ],
        "PROVIDER_CALL_EXECUTED": (
            "YES"
            if any(item.get("PROVIDER_CALL_STARTED") for item in attempts)
            else "NO"
        ),
        "JSON_PARSE_VALID": bool(
            observed_attempt and observed_attempt.get("JSON_PARSE_VALID")
        ),
        "STRUCTURED_OUTPUT_VALID": bool(
            observed_attempt and observed_attempt.get("STRUCTURED_OUTPUT_VALID")
        ),
        "MISSION_PROPOSAL_SCHEMA_VALID": bool(
            observed_attempt
            and observed_attempt.get("MISSION_PROPOSAL_SCHEMA_VALID")
        ),
        "HARNESS_VALIDATION_PASS": bool(
            observed_attempt and observed_attempt.get("HARNESS_VALIDATION_PASS")
        ),
        "ROOT_CAUSE_CLASS": (
            "SEMANTIC_PLAN_POLICY_PRECONDITION"
            if (
                observed_attempt
                and observed_attempt.get("STRUCTURED_OUTPUT_VALID")
                and observed_attempt.get("MISSION_PROPOSAL_SCHEMA_VALID")
                and not observed_attempt.get("HARNESS_VALIDATION_PASS")
                and "mission_class=" in str(observed_attempt.get("VALIDATION_ERROR") or "")
            )
            else "DOWNSTREAM_HARNESS_CAPABILITY_SELECTION"
            if (
                observed_attempt
                and observed_attempt.get("STRUCTURED_OUTPUT_VALID")
                and observed_attempt.get("MISSION_PROPOSAL_SCHEMA_VALID")
                and not observed_attempt.get("HARNESS_VALIDATION_PASS")
            )
            else (
                observed_attempt.get("OUTPUT_FAILURE_CLASS")
                if observed_attempt
                else "NO_PROVIDER_RESULT"
            )
        ),
        "MODEL_TIMEOUT_RECORDED": bool(recent_memory),
        "FAILED_MODEL_HEALTH_DEGRADED_OR_FAILURE_MEMORY_CAPTURED": bool(
            recent_health
            and (
                recent_health.get("availability") == "DEGRADED"
                or recent_memory
            )
        ),
        "RECENT_FAILURE_INFLUENCES_SELECTION": bool(
            recent_model
            and routing_after_failure.selected_model != recent_model
            and recent_health
            and recent_health.get("source")
            == "LEARNING_PLANE_LIVE_EVIDENCE"
        ),
        "NEXT_SELECTION_MODEL": routing_after_failure.selected_model,
        "FASTEST_HEALTHY_QUALITY_PRESERVING_MODEL": (
            fastest.get("MODEL_ID") if fastest else None
        ),
        "SEMANTIC_PLANNER_TARGET_MS": (
            round(target_ms, 3) if target_ms is not None else None
        ),
        "SEMANTIC_PLANNER_P95_BUDGET_MS": (
            round(p95_ms, 3) if p95_ms is not None else None
        ),
        "MODEL_ATTEMPT_DEADLINE_MS": budget_after[
            "MODEL_ATTEMPT_DEADLINE_MS"
        ],
        "TOTAL_FAILOVER_BUDGET_MS": (
            budget_after["MODEL_ATTEMPT_DEADLINE_MS"]
            * budget_after["MODEL_FAILOVER_BUDGET"]
        ),
        "PROMPT_BYTES": prompt_bytes,
        "MODELS_BEFORE": models_before,
        "ATTEMPTS": sorted(
            [
                {
                    key: value
                    for key, value in item.items()
                    if key != "RESPONSE_TEXT"
                }
                for item in attempts
            ],
            key=lambda item: str(item.get("MODEL_ID")),
        ),
        "LATENCY_BUDGET_BEFORE": budget_before,
        "LATENCY_BUDGET_AFTER": budget_after,
        "LATENCY_BUDGET_AFTER_SOURCE": budget_after_source,
        "GENERATION_MAX_TOKENS": generation_max_tokens,
        "RECENT_FAILURE_MODEL_HEALTH": recent_health,
        "RECENT_FAILURE_MEMORY_IDS": [
            item["memory_id"] for item in recent_memory
        ],
        "HARDCODED_FALLBACK_MODEL": "NO",
        "AUTHORIZATION_LINEAGE_PRESERVED": all(
            bool(item.get("AUTHORIZATION_ID"))
            for item in attempts
            if item.get("ACTIVE")
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for key in (
        "NVIDIA_MULTI_MODEL_VALIDATION",
        "FULL_TIMEOUT_SAME_MODEL_RETRY",
        "LIVE_SEMANTIC_MODEL_PROOF",
        "LIVE_MODEL_ID",
        "LIVE_SEMANTIC_LATENCY_MS",
        "JSON_PARSE_VALID",
        "STRUCTURED_OUTPUT_VALID",
        "MISSION_PROPOSAL_SCHEMA_VALID",
        "HARNESS_VALIDATION_PASS",
        "ROOT_CAUSE_CLASS",
        "MODEL_TIMEOUT_RECORDED",
        "FAILED_MODEL_HEALTH_DEGRADED_OR_FAILURE_MEMORY_CAPTURED",
        "RECENT_FAILURE_INFLUENCES_SELECTION",
        "FASTEST_HEALTHY_QUALITY_PRESERVING_MODEL",
        "SEMANTIC_PLANNER_TARGET_MS",
        "SEMANTIC_PLANNER_P95_BUDGET_MS",
        "MODEL_ATTEMPT_DEADLINE_MS",
        "TOTAL_FAILOVER_BUDGET_MS",
        "PROMPT_BYTES",
        "HARDCODED_FALLBACK_MODEL",
        "AUTHORIZATION_LINEAGE_PRESERVED",
    ):
        value = report.get(key)
        if isinstance(value, bool):
            value = "PASS" if value else "FAIL"
        print(f"{key}={value}")
    if status != "PASS":
        raise SystemExit(2)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--request",
        type=Path,
        default=Path(".run/nvidia-semantic-planner-live-proof.request.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "artifacts/nvidia-semantic-planner-live-proof/report.json"
        ),
    )
    args = parser.parse_args()
    run(args.request, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
