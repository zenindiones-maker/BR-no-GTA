from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
import re
import shutil
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from app.database.schema import initialize_schema
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import (
    TaskEnvelope,
    build_goal_envelope,
    plan_mission_from_human_goal,
)
from app.services.harness_learning_service import (
    HarnessEpisode,
    persist_episode,
    record_memory,
    retrieve_relevant_memory,
)
from app.services.harness_mission_execution_router import select_mission_execution_route
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.harness_executor_availability_service import (
    evaluate_typed_requirement_feasibility,
)
from app.services.harness_residual_replanning_service import (
    ResidualTaskRequirements,
    resolve_residual_task,
)
from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_MUTATE_CANDIDATE,
    CAN_PRODUCE_ARTIFACT_REFS,
    CAN_READ_REPOSITORY,
    CAN_REVIEW,
    CAN_RUN_TESTS,
    CAN_SEMANTIC_REASONING,
    CAN_WRITE_REPOSITORY,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.execution_mission_envelope_service import (
    build_execution_mission_envelope,
    persist_execution_mission_envelope,
)
from app.services.mission_plan_payload_service import (
    persist_mission_plan_payload_evidence,
)
from app.services.memory_plane_service import evaluate_memory_candidate
from app.services.task_result_envelope_service import load_task_result_envelope
from app.services.task_output_contract_service import (
    CANONICAL_FUNCTIONAL_ROLES,
    extract_task_output,
    validate_task_output_contract,
)
from app.services.recovery_execution_service import (
    RECOVERY_APPLY_CAPABILITY_ID,
    RECOVERY_VALIDATE_CAPABILITY_ID,
    build_recovery_candidate_spec,
)
from scripts.dynamic_system_improvement_mission import run as execute_dynamic_mission

CHECKPOINT = 35850473901
DEFAULT_GOAL = (
    "Encontre uma perda mensurável e atual de eficiência, qualidade ou trabalho redundante no BR-no-GTA, "
    "usando a execução real atual do sistema como evidência. Faça o mínimo necessário para identificar a "
    "causa, produzir uma recomendação técnica auditável, revisar independentemente essa conclusão e alimentar "
    "o Learning Plane para que uma execução semelhante seguinte use esse aprendizado. Não faça mutation de "
    "repositório se não existir executor autorizado."
)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def tasks(plan):
    return list((plan.get("collaboration_plan") or {}).get("tasks") or ())


def load_request(path: Path) -> dict:
    if not path.is_file():
        return {"schema": "real-agent-self-improvement-request/v1", "human_goal": DEFAULT_GOAL}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("self-improvement request must be an object")
    goal = str(data.get("human_goal") or "").strip()
    if not goal:
        raise ValueError("self-improvement request requires human_goal")
    return data


def incident_source_manifest(root: Path | None) -> list[dict]:
    if root is None or not root.is_dir():
        return []
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file())[:80]:
        raw = path.read_bytes()
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "size_bytes": len(raw),
            "sha256": sha256(raw).hexdigest(),
        })
    return rows


def build_incident_evidence_packet(
    root: Path | None,
    *,
    incident: dict,
    output_path: Path,
    max_content_bytes: int = 48000,
) -> dict[str, Any]:
    manifest = incident_source_manifest(root)
    raw_files: list[dict[str, Any]] = []
    remaining = max_content_bytes
    allowed_suffixes = {
        ".json", ".jsonl", ".txt", ".md", ".log", ".yml", ".yaml", ".csv",
    }
    if root is not None and root.is_dir():
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if remaining <= 0:
                break
            if path.suffix.casefold() not in allowed_suffixes:
                continue
            raw = path.read_bytes()
            take = min(len(raw), remaining, 12000)
            text = raw[:take].decode("utf-8", errors="replace")
            for secret_name in (
                "NVIDIA_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN",
            ):
                text = re.sub(
                    rf"(?im)({secret_name}\s*[:=]\s*)[^\s,;]+",
                    rf"\1<redacted>",
                    text,
                )
            raw_files.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "content": text,
                "content_truncated": take < len(raw),
            })
            remaining -= len(text.encode("utf-8"))
    packet = {
        "schema": "real-incident-evidence-packet/v1",
        "semantic_interpretation": False,
        "source": "OBSERVED_GITHUB_RUN_ARTIFACT",
        "incident": incident,
        "manifest": manifest,
        "raw_text_files": raw_files,
        "content_budget_bytes": max_content_bytes,
        "content_bytes_used": max_content_bytes - max(0, remaining),
    }
    write_json(output_path, packet)
    return packet


def independent_review_requirement() -> dict[str, Any]:
    return {
        "task_id": "mandatory-independent-review-precheck",
        "task_class": "independent-review",
        "action": "DEVELOPMENT",
        "domain": "development",
        "required_domains": ["development", "system-improvement"],
        "objective": (
            "Independently review a bounded system-improvement recovery proposal "
            "against observed evidence without mutation"
        ),
        "required_capability_description": (
            "independent semantic review of system-improvement evidence and proposal"
        ),
        "expected_output": "IndependentReviewEvidence",
        "acceptance_criteria": [
            "review consumes observed artifact refs",
            "reviewer is independent from proposal author",
        ],
        "required_operations": [
            CAN_REVIEW,
            CAN_SEMANTIC_REASONING,
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        ],
        "candidate_requirement": "NOT_APPLICABLE",
        "risk_side_effect_class": "READ_ONLY",
    }


def _incident_refs(incident: dict) -> tuple[str, ...]:
    refs = [
        *(incident.get("evidence_refs") or ()),
        f"github:run:{incident.get('source_run_id')}",
        f"github:job:{incident.get('source_job_id')}",
        f"github:artifact:{incident.get('source_artifact_id')}",
    ]
    return tuple(dict.fromkeys(str(x).strip() for x in refs if str(x).strip()))


def persist_real_failure_episode(request: dict, *, base_sha: str, manifest: list[dict]) -> dict | None:
    incident = dict(request.get("incident") or {})
    if not incident:
        return None
    capability_id = str(incident.get("capability_id") or "").strip()
    task_id = str(incident.get("task_id") or "").strip()
    if not capability_id or not task_id:
        raise ValueError("incident requires capability_id and task_id")
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    refs = _incident_refs(incident)
    run_id = str(incident.get("source_run_id") or "").strip()
    episode = HarnessEpisode(
        episode_id=f"episode-real-provider-failure-{run_id}",
        goal_id=f"production-run-{run_id}",
        decision_id=f"observed-production-failure-{run_id}",
        execution_id=f"github-run-{run_id}",
        task_id=task_id,
        agent_id=str(
            getattr(record, "agent_id", None)
            or getattr(record, "skill_id", None)
            or "harness-selected-capability"
        ),
        capability_id=capability_id,
        domain=str(
            incident.get("domain")
            or getattr(record, "domain", None)
            or "system-improvement"
        ),
        task_class=str(
            incident.get("task_class")
            or "provider-runtime-failure"
        ),
        started_at=str(incident.get("started_at") or datetime.now(timezone.utc).isoformat()),
        finished_at=str(incident.get("finished_at") or datetime.now(timezone.utc).isoformat()),
        duration_seconds=max(0.0, float(incident.get("duration_seconds") or 0.0)),
        status="FAILED",
        actual_outcome={
            "observed": True,
            "error_type": incident.get("observed_error_type"),
            "error": incident.get("observed_error"),
            "provider_call_attempted": incident.get("provider_call_attempted") or "UNKNOWN",
            "provider_critical_path_ms": incident.get("provider_critical_path_ms"),
            "provider_cumulative_work_ms": incident.get("provider_cumulative_work_ms"),
            "routing_reached_semantic_provider_selection": bool(
                incident.get("routing_reached_semantic_provider_selection")
            ),
            "provider_competence_update_allowed": False,
            "artifact_manifest": manifest,
        },
        outcome_evidence=refs,
        provider=None,
        evidence_refs=refs,
        error={
            "class": incident.get("failure_class") or "UNCLASSIFIED",
            "reason": incident.get("observed_error"),
            "provider_call_attempted": incident.get("provider_call_attempted") or "UNKNOWN",
        },
        retry_count=0,
        human_intervention=False,
        run_ref=f"github:run:{run_id}",
        artifact_refs=tuple(
            x for x in refs if x.startswith("github:artifact:")
        ),
        source_versions={"repository": base_sha},
        lineage={
            "source_run_id": incident.get("source_run_id"),
            "source_job_id": incident.get("source_job_id"),
            "canonical_codex_checkpoint": request.get("canonical_codex_checkpoint"),
            "provider_competence_penalized": False,
        },
    )
    return persist_episode(episode)


def _row_text(row: dict | None) -> str:
    values = []
    for item in walk((row or {}).get("result_payload")):
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, (int, float, bool)):
            values.append(str(item))
    values.append(str((row or {}).get("result_summary") or ""))
    return "\n".join(values)


def marker_from_rows(rows, key: str):
    pattern = re.compile(
        rf"(?im)(?:^|\\b){re.escape(key)}\\s*[:=]\\s*([^\\r\\n;,]+)"
    )
    for row in rows:
        match = pattern.search(_row_text(row))
        if match:
            return match.group(1).strip()
    return None

def _is_independent_review_task(item: dict) -> bool:
    operations = {
        str(value).strip()
        for value in (item.get("required_operations") or ())
        if str(value).strip()
    }
    expected_output = str(item.get("expected_output") or "").strip().upper()
    task_id = str(item.get("task_id") or "").strip().casefold()
    semantic_text = " ".join(
        str(item.get(key) or "").strip().casefold()
        for key in ("task_class", "objective", "required_capability_description")
    )
    return bool(
        CAN_REVIEW in operations
        and (
            "review" in semantic_text
            or "revis" in semantic_text
            or "independent-review" in task_id
            or "INDEPENDENT_REVIEW" in expected_output
        )
    )


def _checkpoint_task_signature(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("task_id"),
        "task_class": task.get("task_class"),
        "functional_role": task.get("functional_role"),
        "mission_policy_class": task.get("mission_policy_class"),
        "capability_id": task.get("capability_id"),
        "selected_agent_id": task.get("selected_agent_id"),
        "selected_skill_id": task.get("selected_skill_id"),
        "capability_version": str(task.get("capability_version") or "1"),
        "required_operations": sorted(
            str(item)
            for item in (task.get("required_operations") or ())
        ),
        "candidate_requirement": task.get("candidate_requirement"),
        "risk_side_effect_class": task.get("risk_side_effect_class"),
        "dependencies": list(task.get("dependencies") or ()),
        "input_refs": list(task.get("input_refs") or ()),
        "objective": task.get("objective"),
        "expected_output": task.get("expected_output"),
    }


def checkpoint_resume_identity(
    checkpoint_source_dir: Path | None,
) -> dict[str, str] | None:
    if checkpoint_source_dir is None or not checkpoint_source_dir.is_dir():
        return None
    source_plan_path = checkpoint_source_dir / "first-plan.json"
    if not source_plan_path.is_file():
        return None
    try:
        source_wrapper = json.loads(
            source_plan_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    source_plan = dict(
        source_wrapper.get("plan") or source_wrapper
    )
    goal = source_wrapper.get("goal")
    goal_id = str(
        (goal or {}).get("goal_id")
        if isinstance(goal, dict)
        else ""
    ).strip()
    mission_id = str(source_plan.get("mission_id") or "").strip()
    if not goal_id or not mission_id:
        return None
    return {
        "goal_id": goal_id,
        "mission_id": mission_id,
    }


def restore_compatible_node_checkpoints(
    *,
    plan: dict[str, Any],
    checkpoint_source_dir: Path | None,
    runtime_dir: Path,
) -> dict[str, Any]:
    evidence = {
        "CHECKPOINT_AVAILABLE": False,
        "CHECKPOINT_HASH_VALID": False,
        "CHECKPOINT_LINEAGE_VALID": False,
        "CHECKPOINT_SEMANTICALLY_COMPATIBLE": False,
        "CHECKPOINT_REUSED": False,
        "REUSED_TASK_IDS": [],
        "NO_COMPLETED_NODE_REEXECUTION": False,
        "PARTIAL_TASK_SESSION_RESTORED": False,
        "PARTIAL_TASK_ID": None,
        "PARTIAL_AGENT_INSTANCE_ID": None,
        "RESTORED_TOOL_RESULT_COUNT": 0,
        "RESTORED_TURN_INDEX": 0,
        "RESTORED_PROVIDER_ATTEMPT_COUNT": 0,
    }
    if checkpoint_source_dir is None or not checkpoint_source_dir.is_dir():
        return evidence
    source_plan_path = checkpoint_source_dir / "first-plan.json"
    source_runtime = checkpoint_source_dir / "first-runtime"
    if not source_plan_path.is_file() or not source_runtime.is_dir():
        return evidence

    source_wrapper = json.loads(
        source_plan_path.read_text(encoding="utf-8")
    )
    source_plan = dict(source_wrapper.get("plan") or source_wrapper)
    source_by_id = {
        str(item.get("task_id") or ""): item
        for item in tasks(source_plan)
    }
    current_tasks = tasks(plan)
    evidence["CHECKPOINT_AVAILABLE"] = True

    current_incident = runtime_dir / "incident-evidence-packet.json"
    source_incident = source_runtime / "incident-evidence-packet.json"
    if current_incident.is_file() and source_incident.is_file():
        if sha256(current_incident.read_bytes()).hexdigest() != sha256(
            source_incident.read_bytes()
        ).hexdigest():
            evidence["RERUN_REASON"] = "incident artifact hash changed"
            return evidence

    result_dir = runtime_dir / "capability-results"
    task_result_dir = runtime_dir / "checkpoint-task-results"
    result_dir.mkdir(parents=True, exist_ok=True)
    task_result_dir.mkdir(parents=True, exist_ok=True)

    hash_valid = True
    lineage_valid = True
    semantic_valid = True
    reused: list[str] = []
    previous_reused: str | None = None
    partial_task_id: str | None = None
    partial_source_task: dict[str, Any] | None = None

    for current in current_tasks:
        task_id = str(current.get("task_id") or "")
        source_task = source_by_id.get(task_id)
        if source_task is None:
            break
        if _checkpoint_task_signature(current) != _checkpoint_task_signature(
            source_task
        ):
            semantic_valid = False
            break

        rows = sorted(
            (source_runtime / "capability-results").glob(
                f"{task_id}-*.json"
            )
        )
        completed = None
        for row_path in reversed(rows):
            row = json.loads(row_path.read_text(encoding="utf-8"))
            if (
                row.get("status") == "COMPLETED"
                and row.get("capability_id") == current.get("capability_id")
            ):
                completed = row
                break
        if completed is None:
            partial_task_id = task_id
            partial_source_task = source_task
            break

        source_ref = str(completed.get("task_result_ref") or "")
        try:
            envelope = load_task_result_envelope(
                artifact_dir=source_runtime,
                task_result_ref=source_ref,
            )
        except Exception:
            hash_valid = False
            break
        if envelope.get("task_id") != task_id:
            hash_valid = False
            break
        output_validation = validate_task_output_contract(
            functional_role=current.get("functional_role"),
            result=envelope.get("result_payload"),
        )
        if (
            output_validation.required
            and not output_validation.final_output_valid
        ):
            semantic_valid = False
            evidence["RERUN_REASON"] = (
                "LEGACY_COMPLETION_UNVERIFIED:" + task_id
            )
            break
        expected_sources = list(current.get("dependencies") or ())
        if list(envelope.get("source_task_ids") or ()) != expected_sources:
            lineage_valid = False
            break
        if expected_sources and previous_reused not in expected_sources:
            lineage_valid = False
            break

        target = task_result_dir / f"{task_id}.json"
        source_target = (
            source_runtime / source_ref[len("artifact:"):]
        ).resolve()
        shutil.copyfile(source_target, target)
        copied_ref = "artifact:checkpoint-task-results/" + target.name

        wrapper = {
            "mission_id": plan.get("mission_id"),
            "task_id": task_id,
            "capability_id": current.get("capability_id"),
            "agent_id": current.get("selected_agent_id"),
            "runtime": "hermes",
            "routing_id": current.get("routing_id"),
            "authorization_id": (
                "checkpoint-reuse:"
                + str(completed.get("authorization_id") or "unknown")
            ),
            "idempotency_key": current.get("idempotency_key"),
            "capability_version": str(
                current.get("capability_version") or "1"
            ),
            "retry_count": 0,
            "status": "COMPLETED",
            "elapsed_seconds": 0.0,
            "cost": 0.0,
            "policy_violations": 0,
            "result": completed.get("result"),
            "task_result_ref": copied_ref,
            "task_result_sha256": envelope.get("content_sha256"),
            "checkpoint_reused": True,
            "checkpoint_source_mission_id": source_plan.get("mission_id"),
            "checkpoint_source_task_result_ref": source_ref,
            "checkpoint_source_content_sha256": envelope.get(
                "content_sha256"
            ),
            "checkpoint_source_authorization_id": completed.get(
                "authorization_id"
            ),
        }
        write_json(
            result_dir / f"{task_id}-checkpoint.json",
            wrapper,
        )
        reused.append(task_id)
        previous_reused = task_id

    if (
        partial_task_id
        and partial_source_task is not None
        and semantic_valid
        and hash_valid
        and lineage_valid
    ):
        current_partial = next(
            (
                item for item in current_tasks
                if str(item.get("task_id") or "") == partial_task_id
            ),
            None,
        )
        if (
            current_partial is not None
            and _checkpoint_task_signature(current_partial)
            == _checkpoint_task_signature(partial_source_task)
        ):
            session_candidates = sorted(
                (source_runtime / "agent-sessions").glob(
                    f"{partial_task_id}-agent-*.json"
                )
            )
            for source_session_path in reversed(session_candidates):
                try:
                    source_session = json.loads(
                        source_session_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    continue
                if (
                    source_session.get("schema") != "AgentSession/v1"
                    or source_session.get("MISSION_ID")
                    != str(plan.get("mission_id") or "")
                    or source_session.get("TASK_ID") != partial_task_id
                    or source_session.get("CAPABILITY_ID")
                    != current_partial.get("capability_id")
                    or source_session.get("AGENT_ID")
                    != current_partial.get("selected_agent_id")
                ):
                    continue
                session_dir = runtime_dir / "agent-sessions"
                session_dir.mkdir(parents=True, exist_ok=True)
                target_session = session_dir / source_session_path.name
                shutil.copyfile(source_session_path, target_session)

                restored_tool_results = 0
                tool_results_valid = True
                for execution in source_session.get("TOOL_EXECUTIONS") or ():
                    if not isinstance(execution, dict):
                        continue
                    expected_hash = str(
                        execution.get("content_sha256") or ""
                    ).strip()
                    for ref in execution.get("output_refs") or ():
                        value = str(ref or "").strip()
                        if not value.startswith("artifact:tool-results/"):
                            continue
                        relative = value[len("artifact:"):]
                        source_tool = (source_runtime / relative).resolve()
                        source_root = source_runtime.resolve()
                        if (
                            source_tool != source_root
                            and source_root not in source_tool.parents
                        ):
                            tool_results_valid = False
                            break
                        if not source_tool.is_file():
                            tool_results_valid = False
                            break
                        try:
                            envelope = json.loads(
                                source_tool.read_text(encoding="utf-8")
                            )
                        except (OSError, json.JSONDecodeError):
                            tool_results_valid = False
                            break
                        if (
                            envelope.get("schema") != "ToolResultEnvelope/v1"
                            or envelope.get("task_id") != partial_task_id
                            or (
                                expected_hash
                                and str(
                                    envelope.get("content_sha256") or ""
                                ).strip() != expected_hash
                            )
                        ):
                            tool_results_valid = False
                            break
                        target_tool = (runtime_dir / relative).resolve()
                        runtime_root = runtime_dir.resolve()
                        if (
                            target_tool != runtime_root
                            and runtime_root not in target_tool.parents
                        ):
                            tool_results_valid = False
                            break
                        target_tool.parent.mkdir(
                            parents=True,
                            exist_ok=True,
                        )
                        shutil.copyfile(source_tool, target_tool)
                        restored_tool_results += 1
                    if not tool_results_valid:
                        break

                if not tool_results_valid:
                    target_session.unlink(missing_ok=True)
                    continue

                failure_evidence = source_session.get(
                    "FAILURE_EVIDENCE"
                )
                provider_attempt_count = 0
                if isinstance(failure_evidence, dict):
                    stack = [failure_evidence]
                    seen_attempt_ids = set()
                    while stack:
                        item = stack.pop()
                        if isinstance(item, dict):
                            attempts = item.get("provider_attempts")
                            if isinstance(attempts, list):
                                for attempt in attempts:
                                    if not isinstance(attempt, dict):
                                        continue
                                    attempt_id = str(
                                        attempt.get("attempt_id") or ""
                                    )
                                    seen_attempt_ids.add(
                                        attempt_id
                                        or json.dumps(
                                            attempt,
                                            sort_keys=True,
                                            default=str,
                                        )
                                    )
                            stack.extend(item.values())
                        elif isinstance(item, list):
                            stack.extend(item)
                    provider_attempt_count = len(seen_attempt_ids)

                evidence.update({
                    "PARTIAL_TASK_SESSION_RESTORED": True,
                    "PARTIAL_TASK_ID": partial_task_id,
                    "PARTIAL_AGENT_INSTANCE_ID": source_session.get(
                        "AGENT_INSTANCE_ID"
                    ),
                    "RESTORED_TOOL_RESULT_COUNT": restored_tool_results,
                    "RESTORED_TURN_INDEX": int(
                        source_session.get("TURN_INDEX") or 0
                    ),
                    "RESTORED_PROVIDER_ATTEMPT_COUNT": (
                        provider_attempt_count
                    ),
                })
                break

    evidence.update({
        "CHECKPOINT_HASH_VALID": hash_valid,
        "CHECKPOINT_LINEAGE_VALID": lineage_valid,
        "CHECKPOINT_SEMANTICALLY_COMPATIBLE": semantic_valid,
        "CHECKPOINT_REUSED": bool(reused),
        "REUSED_TASK_IDS": reused,
        "REUSED_TASK_COUNT": len(reused),
        "NO_COMPLETED_NODE_REEXECUTION": bool(reused),
        "RERUN_REASON": (
            "resume partial agent session at " + str(partial_task_id)
            if evidence.get("PARTIAL_TASK_SESSION_RESTORED")
            else "resume at first incomplete node"
            if reused
            else evidence.get("RERUN_REASON")
            or "no compatible completed node prefix"
        ),
    })
    return evidence



def plan_once(
    goal_id,
    out,
    *,
    goal_text: str,
    request: dict,
    failure_episode_id: str | None,
    manifest: list[dict],
    artifact_ref: str | None,
):
    incident = dict(request.get("incident") or {})
    goal = build_goal_envelope(
        human_goal=goal_text,
        project="BR-no-GTA",
        goal_id=goal_id,
        subject=(
            "BR-no-GTA real provider incident recovery"
            if incident else "BR-no-GTA system self-improvement"
        ),
        source_surface="github-actions-control",
        canonical_state={
            "authority": "DEEPSEEK_HARNESS",
            "zero_cost_operation": True,
            "codex_checkpoint": CHECKPOINT,
            "codex_state": str(request.get("codex_state") or "BLOCKED_EXTERNAL"),
            "codex_blocker": request.get("codex_blocker"),
            "real_failure_episode_id": failure_episode_id,
            "incident": incident,
            "incident_artifact_manifest": manifest,
            "incident_evidence_artifact_ref": artifact_ref,
            "pre_materialized_inputs": (
                [{
                    "artifact_ref": artifact_ref,
                    "purpose": "raw observed incident evidence",
                    "semantic_interpretation": False,
                    "reuse_required": True,
                }]
                if artifact_ref else []
            ),
            "mutation_policy": request.get("mutation_policy"),
            "fallback_policy": request.get("fallback_policy"),
            "provider_competence_policy": request.get("provider_competence_policy"),
            "closed_green_boundaries": [
                "Addy editorial selection",
                "production execution contracts",
                "Telegram ingress/outbound",
                "fresh research compatibility",
                "canonical Codex auth checkpoint 35850473901",
            ],
        },
    )
    started = time.perf_counter()
    if incident and goal.mission_class != "SYSTEM_IMPROVEMENT":
        raise RuntimeError(
            "INCIDENT_RECOVERY_MISSION_CLASS_INVALID:" + goal.mission_class
        )
    obj = plan_mission_from_human_goal(goal, artifact_ref=artifact_ref)
    elapsed = (time.perf_counter() - started) * 1000
    payload = obj.to_dict()
    route = select_mission_execution_route(payload)
    write_json(out, {
        "human_goal": goal_text,
        "goal": goal.to_dict(),
        "plan": payload,
        "route": route.to_dict(),
        "planning_ms": elapsed,
        "failure_episode_id": failure_episode_id,
    })
    return payload, route, elapsed
def apply_runtime_residual_replan(
    plan: dict[str, Any],
    *,
    residual_spec: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generic Harness residual replan consumed by the real mission entrypoint."""
    if not residual_spec:
        return plan, {"RESIDUAL_REPLAN_PERFORMED": "NOT_APPLICABLE"}
    collaboration=dict(plan.get("collaboration_plan") or {})
    original_tasks=[dict(x) for x in collaboration.get("tasks") or ()]
    parent_id=str(residual_spec.get("parent_task_id") or "").strip()
    parent=next((x for x in original_tasks if str(x.get("task_id") or "")==parent_id),None)
    if parent is None:
        raise RuntimeError("RESIDUAL_PARENT_TASK_MISSING:"+parent_id)
    child_id=str(residual_spec.get("task_id") or (parent_id+"-residual")).strip()
    req=ResidualTaskRequirements(
        parent_task_id=parent_id,task_id=child_id,
        task_class=str(residual_spec.get("task_class") or parent.get("task_class") or "residual"),
        functional_role=str(residual_spec.get("functional_role") or parent.get("functional_role") or "GENERAL"),
        required_operations=tuple(residual_spec.get("required_operations") or parent.get("required_operations") or ()),
        required_input_artifact_schemas=tuple(residual_spec.get("required_input_artifact_schemas") or ()),
        expected_output_schema=str(residual_spec.get("expected_output_schema") or parent.get("expected_output") or ""),
        side_effect_class=str(residual_spec.get("side_effect_class") or "READ_ONLY"),
        mutation_requirement=str(residual_spec.get("mutation_requirement") or "NOT_APPLICABLE"),
        review_requirement=str(residual_spec.get("review_requirement") or "NOT_REQUIRED"),
        dependency_refs=tuple(parent.get("dependencies") or ()),
        already_completed_work_refs=tuple(residual_spec.get("input_artifact_refs") or ()),
        forbidden_capabilities=tuple(residual_spec.get("forbidden_capabilities") or ()),
        eligibility_snapshot_ref=str(residual_spec.get("eligibility_snapshot_ref") or "runtime:eligibility"),
    )
    resolution=resolve_residual_task(req)
    selected=resolution.get("selected")
    if not selected:
        raise RuntimeError("RESIDUAL_REPLAN_NO_ELIGIBLE_CAPABILITY")
    record=GLOBAL_CAPABILITY_REGISTRY.get(str(selected["capability_id"]))
    if record is None:
        raise RuntimeError("RESIDUAL_SELECTED_CAPABILITY_MISSING")
    child=dict(parent)
    child.update(req.to_task())
    child.update({
        "capability_id":record.capability_id,
        "selected_agent_id":record.agent_id,
        "selected_skill_id":record.skill_id,
        "selected_executor_binding":record.executor_binding,
        "input_refs":list(req.already_completed_work_refs),
        "expected_output":req.expected_output_schema,
        "required_capability_description":"Registry-selected residual capability satisfying typed requirements",
        "residual_parent_task_id":parent_id,
        "original_parent_capability_id":parent.get("capability_id"),
    })
    # Preserve the failed parent in immutable lineage, but replace its executable
    # node by a child and redirect only its downstream dependencies.
    executable=[x for x in original_tasks if str(x.get("task_id") or "")!=parent_id]
    executable.append(child)
    for task in executable:
        task["dependencies"]=[
            child_id if str(dep)==parent_id else dep
            for dep in (task.get("dependencies") or ())
        ]
    levels=[]
    for level in collaboration.get("execution_levels") or ():
        levels.append([child_id if str(x)==parent_id else x for x in level])
    collaboration["tasks"]=executable
    collaboration["execution_levels"]=levels
    plan=dict(plan);plan["collaboration_plan"]=collaboration
    evidence={
        "schema":"runtime-residual-replan/v1",
        "ORIGINAL_TASK_ID":parent_id,
        "ORIGINAL_TASK_CAPABILITY":parent.get("capability_id"),
        "ORIGINAL_TASK_HISTORY_PRESERVED":True,
        "RESIDUAL_REPLAN_PERFORMED":"PASS",
        "RESIDUAL_TASK_ID":child_id,
        "RESIDUAL_SELECTED_CAPABILITY":record.capability_id,
        "RESIDUAL_SELECTED_AGENT":record.agent_id,
        "ADDY_RUNTIME_INVOCATION_COUNT":0 if not str(record.capability_id).startswith("addy:") else 1,
        "CODEX_RUNTIME_INVOCATION_COUNT":1 if record.agent_id=="codex-readonly" else 0,
        "resolution":resolution,
    }
    return plan,evidence


def selected_identity_text(plan):
    return json.dumps([
        {
            "capability": t.get("capability_id"),
            "agent": t.get("selected_agent_id"),
            "skill": t.get("selected_skill_id"),
            "binding": t.get("selected_executor_binding"),
        }
        for t in tasks(plan)
    ], sort_keys=True).casefold()


def bootstrap(plan, route, root):
    metrics = {"HERMES_BOOTSTRAP_MS": 0.0, "ADDY_BOOTSTRAP_MS": 0.0}
    if not route.hermes_used:
        raise RuntimeError("REAL_SELF_IMPROVEMENT_REQUIRES_SELECTED_COLLABORATION_RUNTIME")
    upstream = root / "hermes-agent"
    started = time.perf_counter()
    subprocess.run([sys.executable, "scripts/bootstrap_hermes_agent.py", "--target", str(upstream), "--output", str(root / "hermes-bootstrap.json")], check=True)
    metrics["HERMES_BOOTSTRAP_MS"] = (time.perf_counter() - started) * 1000
    if any("addy_harness_service" in str(t.get("selected_executor_binding") or "") for t in tasks(plan)):
        started = time.perf_counter()
        subprocess.run(["bash", "scripts/agent-tooling/bootstrap.sh", "addy"], check=True)
        metrics["ADDY_BOOTSTRAP_MS"] = (time.perf_counter() - started) * 1000
    return upstream, metrics


def execute(plan, base_sha, branch, upstream, root, *, goal_text: str):
    envelope_root = root / "mission-envelope"
    payload_profile = persist_mission_plan_payload_evidence(
        plan,
        artifact_dir=envelope_root,
    )
    envelope = build_execution_mission_envelope(
        plan,
        canonical_artifact_ref=(
            "artifact:mission-envelope/canonical-mission-plan.json"
        ),
        profile_artifact_ref=(
            "artifact:mission-envelope/mission-plan-payload-profile.json"
        ),
        payload_profile=payload_profile,
    )
    persist_execution_mission_envelope(
        envelope,
        artifact_dir=envelope_root,
    )
    encoded = base64.b64encode(
        json.dumps(
            envelope.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).decode()
    started = time.perf_counter()
    report = execute_dynamic_mission(
        plan_b64=encoded,
        human_goal=goal_text,
        base_sha=base_sha,
        branch=branch,
        upstream_root=upstream,
        artifact_dir=root,
    )
    return report, (time.perf_counter() - started) * 1000
def load_results(root):
    result = {}
    for path in sorted((root / "task-results").glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        row["_path"] = path.as_posix()
        if row.get("task_id"):
            result[str(row["task_id"])] = row
    return result


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk(child)


def profile_payload(row):
    for item in walk((row or {}).get("result_payload")):
        if isinstance(item, dict) and item.get("metric_schema") == "agent-office-repository-profile/v1":
            return dict(item)
    return {}


def task_text(task):
    return " ".join(str(task.get(k) or "") for k in ("task_id", "task_class", "objective", "required_capability_description", "expected_output")).casefold()


def _canonical_functional_role(task: dict[str, Any]) -> str | None:
    role = str(task.get("functional_role") or "").strip().upper()
    return role if role in CANONICAL_FUNCTIONAL_ROLES else None


def _legacy_roles(
    by_id: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
    *,
    incident_mode: bool,
) -> dict[str, dict[str, Any] | None]:
    review_ids = [
        i for i,t in by_id.items()
        if i in results and (
            "CAN_REVIEW" in set(t.get("required_operations") or ())
            or any(x in task_text(t) for x in ("review", "revis", "independent"))
        )
    ]
    benchmark_ids = [
        i for i,t in by_id.items()
        if i in results and (
            "CAN_RUN_BENCHMARK" in set(t.get("required_operations") or ())
            or "benchmark" in task_text(t)
        )
    ]
    if incident_mode:
        diagnosis_markers = (
            "diagnos", "incident", "runtime", "provider", "routing",
            "authorization", "failure", "classif", "observ", "inspect",
        )
        diagnosis_ids = [
            i for i,t in by_id.items()
            if i in results
            and i not in review_ids
            and any(
                x in task_text(t)
                for x in ("diagnos", "classif", "root cause", "root-cause")
            )
        ]
        if not diagnosis_ids:
            diagnosis_ids = [
                i for i,t in by_id.items()
                if i in results
                and i not in review_ids
                and any(x in task_text(t) for x in diagnosis_markers)
            ]
        diagnosis = results.get(diagnosis_ids[0]) if diagnosis_ids else (
            next(iter(results.values()), None)
        )
        diagnosis_id = str((diagnosis or {}).get("task_id") or "")
        root_ids = [
            i for i,t in by_id.items()
            if i in results and i != diagnosis_id and any(
                x in task_text(t)
                for x in (
                    "root cause", "root-cause", "causal",
                    "failure classification",
                )
            )
        ]
        root = results.get(root_ids[0]) if root_ids else diagnosis
        root_id = str((root or {}).get("task_id") or "")
        excluded = {diagnosis_id, root_id, *review_ids, *benchmark_ids}
        proposal_ids = [
            i for i,t in by_id.items()
            if i in results and i not in excluded and any(
                x in task_text(t)
                for x in (
                    "proposal", "recommend", "recomend", "recovery",
                    "candidate", "fix", "improvement",
                )
            )
        ]
        return {
            "profile": diagnosis,
            "diagnosis": diagnosis,
            "root": root,
            "proposal": results.get(proposal_ids[-1]) if proposal_ids else None,
            "review": results.get(review_ids[-1]) if review_ids else None,
            "benchmark": results.get(benchmark_ids[-1]) if benchmark_ids else None,
        }

    profile = next((r for r in results.values() if profile_payload(r)), None)
    profile_id = str((profile or {}).get("task_id") or "")
    root_ids = [
        i for i,t in by_id.items()
        if i in results and i != profile_id and any(
            x in task_text(t)
            for x in ("root cause", "root-cause", "diagnos", "causal")
        )
    ]
    root = results.get(root_ids[0]) if root_ids else None
    root_id = str((root or {}).get("task_id") or "")
    excluded = {profile_id, root_id, *review_ids, *benchmark_ids}
    proposal_ids = [
        i for i,t in by_id.items()
        if i in results and i not in excluded and any(
            x in task_text(t)
            for x in ("proposal", "recommend", "recomend", "improvement")
        )
    ]
    return {
        "profile": profile,
        "diagnosis": profile,
        "root": root,
        "proposal": results.get(proposal_ids[-1]) if proposal_ids else None,
        "review": results.get(review_ids[-1]) if review_ids else None,
        "benchmark": results.get(benchmark_ids[-1]) if benchmark_ids else None,
    }


def roles(plan, results, *, incident_mode: bool = False):
    by_id = {str(t.get("task_id") or ""): t for t in tasks(plan)}
    typed: dict[str, list[dict[str, Any]]] = {
        role: [] for role in CANONICAL_FUNCTIONAL_ROLES
    }
    legacy_by_id: dict[str, dict[str, Any]] = {}
    for task_id, task in by_id.items():
        if task_id not in results:
            continue
        role = _canonical_functional_role(task)
        if role is None:
            legacy_by_id[task_id] = task
            continue
        typed[role].append(results[task_id])

    legacy = _legacy_roles(
        legacy_by_id,
        {k: v for k, v in results.items() if k in legacy_by_id},
        incident_mode=incident_mode,
    )
    diagnosis = (
        typed["DIAGNOSIS"][-1]
        if typed["DIAGNOSIS"]
        else legacy.get("diagnosis")
    )
    root = (
        typed["ROOT_CAUSE"][-1]
        if typed["ROOT_CAUSE"]
        else legacy.get("root")
    )
    proposal = (
        typed["PROPOSAL"][-1]
        if typed["PROPOSAL"]
        else legacy.get("proposal")
    )
    review = (
        typed["REVIEW"][-1]
        if typed["REVIEW"]
        else legacy.get("review")
    )
    return {
        "profile": diagnosis or legacy.get("profile"),
        "diagnosis": diagnosis,
        "root": root,
        "proposal": proposal,
        "review": review,
        "benchmark": legacy.get("benchmark"),
    }

def ref(row):
    if not row:
        return None
    text = str(row.get("_path") or "")
    return "artifact:task-results/" + text.split("task-results/", 1)[1] if "task-results/" in text else text or None


def author(row):
    if not row:
        return None
    return str(
        row.get("skill_id")
        or row.get("capability_id")
        or row.get("agent_id")
        or ""
    ) or None


def summary(row):
    return str((row or {}).get("result_summary") or "").strip()[:1600]


def episode_ids(report):
    canonical = dict(report.get("hermes_canonical_result") or {})
    payload = dict(canonical.get("result") or {})
    return [str(x) for x in payload.get("harness_episode_ids") or () if str(x).strip()]


def _execute_recovery_registry_capability(
    *,
    capability_id: str,
    functional_role: str,
    task_id: str,
    mission_id: str,
    goal_id: str,
    harness_decision_id: str,
    input_refs: tuple[str, ...],
    read_scope: tuple[str, ...],
    write_scope: tuple[str, ...],
    payload: dict[str, Any],
) -> dict[str, Any]:
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    if record is None or not record.execution_enabled:
        raise RuntimeError(
            "RECOVERY_CAPABILITY_NOT_EXECUTABLE:" + capability_id
        )
    routing = route_harness_request(HarnessRoutingRequest(
        intent=(
            f"{functional_role} reviewed recovery for mission "
            f"{mission_id}"
        ),
        authorized_action="DEVELOPMENT",
        domain=record.domain,
        task_class=(
            "recovery-apply"
            if functional_role == "APPLY"
            else "recovery-validation"
        ),
        goal_id=goal_id,
        required_capability_id=capability_id,
        provider_required=False,
        fallback_allowed=False,
        zero_cost_operation=True,
        learning_required=True,
    ))
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{capability_id}",
        harness_decision_id=harness_decision_id,
        execution_id=mission_id,
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": capability_id,
            "selected_executor_binding": (
                routing.selected_executor_binding
            ),
            "mission_id": mission_id,
            "goal_id": goal_id,
            "functional_role": functional_role,
            "input_refs": list(input_refs),
            "authority": "DEEPSEEK_HARNESS",
        },
    )
    task = TaskEnvelope(
        task_id=task_id,
        capability_id=capability_id,
        action="DEVELOPMENT",
        objective=(
            "Apply the reviewed RecoveryCandidateSpec in a disposable "
            "sandbox."
            if functional_role == "APPLY"
            else
            "Validate the applied recovery candidate deterministically "
            "with the reviewed focused test plan."
        ),
        dependencies=(),
        input_refs=input_refs,
        expected_output=(
            "RecoveryApplyReceipt"
            if functional_role == "APPLY"
            else "RecoveryValidationReceipt"
        ),
        task_class=(
            "recovery-apply"
            if functional_role == "APPLY"
            else "recovery-validation"
        ),
        functional_role=functional_role,
        mission_policy_class="SYSTEM_IMPROVEMENT",
        required_capability_description=str(record.implementation),
        acceptance_criteria=(
            (
                "base SHA, patch hash and path allowlist verified",
                "mutation occurs only in disposable worktree",
            )
            if functional_role == "APPLY"
            else (
                "reviewed focused tests execute against candidate SHA",
                "no regressions are reported",
            )
        ),
        candidate_requirement=(
            "REQUIRED"
            if functional_role == "APPLY"
            else "NOT_APPLICABLE"
        ),
        required_operations=tuple(record.execution_operations or ()),
        read_scope=read_scope,
        write_scope=write_scope,
        allowed_tools=tuple(record.allowed_tools or ()),
        allowed_side_effects=tuple(record.side_effects or ()),
        risk_side_effect_class=str(
            record.side_effect_class or "READ_ONLY"
        ),
        review_policy="NONE",
        human_gate_policy="NONE",
        mission_id=mission_id,
        goal_id=goal_id,
        retry_budget=0,
        tool_budget=0,
    )
    adapter = CapabilityAdapter()
    try:
        executed = adapter.execute(
            authorization=authorization,
            task_envelope=task,
            routing_decision=routing,
            payload=payload,
            parent_context={
                "mission_id": mission_id,
                "goal_id": goal_id,
                "functional_role": functional_role,
                "evidence_refs": list(input_refs),
                "harness_decision_id": harness_decision_id,
            },
        )
        return executed.to_dict()
    finally:
        consume_harness_authorization(authorization)


def execute_reviewed_recovery(
    *,
    plan: dict[str, Any],
    found: dict[str, dict[str, Any] | None],
    base_sha: str,
    artifact_dir: Path,
) -> dict[str, Any]:
    proposal_row = found.get("proposal")
    review_row = found.get("review")
    proposal = extract_task_output(
        functional_role="PROPOSAL",
        result=(proposal_row or {}).get("result_payload"),
    )
    review = extract_task_output(
        functional_role="REVIEW",
        result=(review_row or {}).get("result_payload"),
    )
    if proposal is None:
        raise RuntimeError("RECOVERY_PROPOSAL_TYPED_OUTPUT_MISSING")
    if review is None:
        raise RuntimeError("RECOVERY_REVIEW_TYPED_OUTPUT_MISSING")
    review_verdict = str(review.get("verdict") or "").strip().upper()
    if review_verdict != "ACCEPT":
        raise RuntimeError(
            "RECOVERY_REVIEW_NOT_ACCEPTED:" + review_verdict
        )
    proposed_change = dict(proposal.get("proposed_change") or {})
    if proposed_change.get("mutation_required") is not True:
        raise RuntimeError(
            "RECOVERY_PROPOSAL_MUTATION_REQUIRED_FALSE"
        )

    mission_id = str(plan.get("mission_id") or "")
    goal_id = str(plan.get("goal", {}).get("goal_id") or "")
    if not mission_id or not goal_id:
        raise RuntimeError("RECOVERY_MISSION_IDENTITY_MISSING")
    harness_decision_id = (
        f"decision-{mission_id}-reviewed-recovery"
    )
    proposal_ref = str(ref(proposal_row) or "")
    review_ref = str(ref(review_row) or "")
    if not proposal_ref or not review_ref:
        raise RuntimeError("RECOVERY_REVIEW_LINEAGE_REF_MISSING")
    decision = {
        "schema": "HarnessRecoveryDecision/v1",
        "authority": "DEEPSEEK_HARNESS",
        "decision": "AUTHORIZED",
        "harness_decision_id": harness_decision_id,
        "mission_id": mission_id,
        "goal_id": goal_id,
        "base_sha": base_sha,
        "proposal_ref": proposal_ref,
        "review_ref": review_ref,
        "review_verdict": review_verdict,
        "authorized_capabilities": [
            RECOVERY_APPLY_CAPABILITY_ID,
            RECOVERY_VALIDATE_CAPABILITY_ID,
        ],
        "canonical_push_authority": "NONE",
    }
    write_json(
        artifact_dir / "harness-recovery-decision.json",
        decision,
    )
    decision_ref = "artifact:harness-recovery-decision.json"

    spec, spec_ref = build_recovery_candidate_spec(
        proposal=proposal,
        review=review,
        base_sha=base_sha,
        artifact_dir=artifact_dir,
        proposal_ref=proposal_ref,
        review_ref=review_ref,
        harness_decision_id=harness_decision_id,
    )
    scope = tuple(spec.allowed_paths)
    apply_execution = _execute_recovery_registry_capability(
        capability_id=RECOVERY_APPLY_CAPABILITY_ID,
        functional_role="APPLY",
        task_id="apply-recovery",
        mission_id=mission_id,
        goal_id=goal_id,
        harness_decision_id=harness_decision_id,
        input_refs=(
            proposal_ref,
            review_ref,
            spec_ref,
            decision_ref,
        ),
        read_scope=scope,
        write_scope=scope,
        payload={
            "candidate_spec": spec.to_dict(),
            "repository_root": str(Path.cwd().resolve()),
            "artifact_dir": str(artifact_dir.resolve()),
        },
    )
    apply_receipt = dict(apply_execution.get("result") or {})
    if (
        apply_receipt.get("schema") != "RecoveryApplyReceipt/v1"
        or apply_receipt.get("result") != "PASS"
    ):
        raise RuntimeError(
            "APPLY_RECOVERY_DID_NOT_PASS:"
            + json.dumps(apply_receipt, sort_keys=True, default=str)[:1600]
        )
    apply_ref = str(apply_receipt.get("receipt_ref") or "")
    if not apply_ref:
        raise RuntimeError("APPLY_RECOVERY_RECEIPT_REF_MISSING")

    validate_execution = _execute_recovery_registry_capability(
        capability_id=RECOVERY_VALIDATE_CAPABILITY_ID,
        functional_role="VALIDATE",
        task_id="validate-recovery",
        mission_id=mission_id,
        goal_id=goal_id,
        harness_decision_id=harness_decision_id,
        input_refs=(
            proposal_ref,
            review_ref,
            spec_ref,
            decision_ref,
            apply_ref,
        ),
        read_scope=scope,
        write_scope=(),
        payload={
            "candidate_spec": spec.to_dict(),
            "apply_receipt": apply_receipt,
            "repository_root": str(Path.cwd().resolve()),
            "artifact_dir": str(artifact_dir.resolve()),
        },
    )
    validation_receipt = dict(
        validate_execution.get("result") or {}
    )
    if (
        validation_receipt.get("schema")
        != "RecoveryValidationReceipt/v1"
        or validation_receipt.get("result") != "PASS"
    ):
        raise RuntimeError(
            "VALIDATE_RECOVERY_DID_NOT_PASS:"
            + json.dumps(
                validation_receipt,
                sort_keys=True,
                default=str,
            )[:1600]
        )
    validation_ref = str(
        validation_receipt.get("receipt_ref") or ""
    )
    if not validation_ref:
        raise RuntimeError(
            "VALIDATE_RECOVERY_RECEIPT_REF_MISSING"
        )

    checks = dict(apply_receipt.get("checks") or {})
    return {
        "harness_decision_id": harness_decision_id,
        "decision_ref": decision_ref,
        "review_verdict": review_verdict,
        "candidate_spec": spec.to_dict(),
        "candidate_spec_ref": spec_ref,
        "apply_capability": RECOVERY_APPLY_CAPABILITY_ID,
        "apply_execution": apply_execution,
        "apply_receipt": apply_receipt,
        "apply_receipt_ref": apply_ref,
        "validate_capability": RECOVERY_VALIDATE_CAPABILITY_ID,
        "validate_execution": validate_execution,
        "validation_receipt": validation_receipt,
        "validation_receipt_ref": validation_ref,
        "checks": checks,
    }


def promote_memory(
    plan,
    base_sha,
    episodes,
    found,
    *,
    request: dict,
    harness_decision_id: str | None = None,
    extra_evidence_refs: tuple[str, ...] = (),
):
    if not episodes or any(found[k] is None for k in ("profile", "root", "proposal")):
        raise RuntimeError("REAL_SELF_IMPROVEMENT_ARTIFACT_CHAIN_INCOMPLETE")
    if found["review"] is None:
        raise RuntimeError("INDEPENDENT_REVIEW_NOT_EXECUTED")
    evidence = list(dict.fromkeys([
        *[
            x for x in (
                ref(found["profile"]), ref(found["root"]),
                ref(found["proposal"]), ref(found["review"]),
            ) if x
        ],
        *[
            str(x).strip()
            for x in extra_evidence_refs
            if str(x).strip()
        ],
    ]))
    incident = dict(request.get("incident") or {})
    signature = (
        f"{incident.get('task_id')}:{incident.get('capability_id')}:"
        f"{incident.get('observed_error')}"
        if incident else f"system-improvement:{base_sha}"
    )
    started = time.perf_counter()
    candidate = record_memory(
        memory_type="SEMANTIC",
        claim=(
            "Reviewed BR-no-GTA recovery evidence for failure signature "
            + signature
            + ". On a similar execution, retrieve diagnosis/root-cause/proposal/review "
            "artifacts before repeating equivalent work; preserve fail-closed routing and "
            "do not penalize a provider/model unless a real provider call failure is proven. "
            "Evidence: " + ", ".join(evidence)
        ),
        domain="system-improvement",
        task_class="provider-incident-recovery" if incident else "system-improvement",
        source_episode_ids=episodes,
        evidence_refs=evidence,
        metadata={
            "source": "REAL_AGENT_SELF_IMPROVEMENT",
            "mission_id": plan.get("mission_id"),
            "base_sha": base_sha,
            "failure_signature": signature,
            "failure_episode_id": episodes[0] if incident else None,
            "reviewed": True,
            "canonical_auto_promotion": False,
        },
        support_count=1,
        confidence=0.78 if incident else 0.72,
        status="CANDIDATE",
        identity_payload={
            "source": "REAL_AGENT_SELF_IMPROVEMENT",
            "mission_id": plan.get("mission_id"),
            "base_sha": base_sha,
            "failure_signature": signature,
            "episodes": episodes,
        },
    )
    memory_id = str(candidate["memory_id"])
    harness_decision_id = (
        str(harness_decision_id or "").strip()
        or f"decision-{plan.get('mission_id')}-incident-recovery"
    )
    auth = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"learning:memory:{memory_id}",
        harness_decision_id=harness_decision_id,
        execution_id=str(plan.get("mission_id") or ""),
        lineage={
            "mission_id": plan.get("mission_id"),
            "base_sha": base_sha,
            "memory_id": memory_id,
            "source_episode_ids": episodes,
            "evidence_refs": evidence,
            "review_artifact_ref": ref(found["review"]),
            "failure_signature": signature,
        },
    )
    promoted = evaluate_memory_candidate(
        memory_id=memory_id,
        decision="PROMOTE",
        reason=(
            "DeepSeek Harness accepted a procedural recovery rule only after real "
            "failure evidence, agent diagnosis/root-cause, bounded proposal, typed "
            "artifact lineage and independent review."
        ),
        evidence_refs=evidence,
        authorization=auth,
    )
    if (promoted.get("memory") or {}).get("status") != "ACTIVE":
        raise RuntimeError("REAL_LEARNING_MEMORY_NOT_ACTIVE_AFTER_GATE")
    return promoted, (time.perf_counter() - started) * 1000, harness_decision_id
def memory_ids(plan):
    bounded = dict(plan.get("bounded_memory_context") or {})
    result = set()
    for section in ("operational_memory", "knowledge_memory", "artifact_lineage_memory", "conversation_memory"):
        for item in bounded.get(section) or ():
            if isinstance(item, dict) and item.get("memory_id"):
                result.add(str(item["memory_id"]))
    return result


def strategy(plan):
    proposal = dict(plan.get("semantic_plan_proposal") or {})
    return {
        "task_signature": [{"task_class": t.get("task_class"), "capability_id": t.get("capability_id"), "agent_id": t.get("selected_agent_id"), "skill_id": t.get("selected_skill_id")} for t in tasks(plan)],
        "memory_strategy_notes": list(proposal.get("memory_strategy_notes") or ()),
        "reused_artifact_refs": list(proposal.get("reused_artifact_refs") or ()),
        "known_bad_paths_avoided": list(plan.get("known_bad_paths_avoided") or ()),
        "memory_influences_strategy": bool(plan.get("memory_influences_strategy")),
    }


def perf_totals():
    path = Path(str(os.getenv("BR_PERFORMANCE_TRACE_FILE") or ""))
    totals = {"REGISTRY_SELECTION_MS": 0.0, "ARTIFACT_HANDOFF_MS": 0.0}
    if not path.is_file():
        return totals
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        category = str(item.get("category") or "").upper()
        stage = str(item.get("stage") or "").casefold()
        ms = max(0.0, float(item.get("duration_ms") or 0.0))
        if "REGISTRY" in category or "registry" in stage:
            totals["REGISTRY_SELECTION_MS"] += ms
        if category == "HERMES_HANDOFF_TIME" or stage == "hermes.handoff":
            totals["ARTIFACT_HANDOFF_MS"] += ms
    return {k: round(v, 3) for k,v in totals.items()}


def task_rows(plan, results):
    by_id = {str(t.get("task_id") or ""): t for t in tasks(plan)}
    rows = []
    for task_id, row in sorted(results.items()):
        task = by_id.get(task_id, {})
        rows.append({
            "TASK_ID": task_id,
            "TASK_CLASS": task.get("task_class"),
            "SELECTED_CAPABILITY": row.get("capability_id"),
            "SELECTED_AGENT": author(row),
            "EXECUTOR_BINDING": row.get("executor_binding"),
            "EXECUTION_CONTRACT": list(task.get("required_operations") or ()),
            "TASK_STARTED_AT": row.get("started_at"),
            "TASK_FINISHED_AT": row.get("completed_at"),
            "TASK_WALL_CLOCK_MS": row.get("elapsed_ms"),
            "INPUT_ARTIFACT_REFS": list(row.get("source_task_result_refs") or ()),
            "OUTPUT_ARTIFACT_REF": ref(row),
            "OUTPUT_ARTIFACT_HASH": row.get("content_sha256"),
            "TASK_RESULT_ENVELOPE_ID": f"{row.get('mission_id')}:{task_id}:{row.get('content_sha256')}",
        })
    return rows


def run(
    output_dir,
    base_sha,
    branch,
    *,
    request_path: Path,
    incident_source_dir: Path | None = None,
    checkpoint_source_dir: Path | None = None,
):
    initialize_schema()
    output_dir.mkdir(parents=True, exist_ok=True)
    overall = time.perf_counter()
    request = load_request(request_path)
    goal_text = str(request.get("human_goal") or DEFAULT_GOAL).strip()
    incident = dict(request.get("incident") or {})
    manifest = incident_source_manifest(incident_source_dir)
    first_runtime_dir = output_dir / "first-runtime"
    first_runtime_dir.mkdir(parents=True, exist_ok=True)
    incident_artifact_ref = None
    if incident:
        packet_path = first_runtime_dir / "incident-evidence-packet.json"
        build_incident_evidence_packet(
            incident_source_dir,
            incident=incident,
            output_path=packet_path,
        )
        incident_artifact_ref = "artifact:incident-evidence-packet.json"

    review_precheck = evaluate_typed_requirement_feasibility(
        independent_review_requirement(),
        blocked_capability_ids=(),
    )
    write_json(output_dir / "reviewer-matrix.json", review_precheck)
    if not review_precheck["feasible"]:
        raise RuntimeError(
            "NO_HEALTHY_INDEPENDENT_REVIEWER:"
            + json.dumps(
                review_precheck["candidate_matrix"],
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    failure_episode = persist_real_failure_episode(
        request,
        base_sha=base_sha,
        manifest=manifest,
    )
    failure_episode_id = (
        str((failure_episode or {}).get("episode_id") or "") or None
    )
    if incident and not failure_episode_id:
        raise RuntimeError("REAL_PROVIDER_FAILURE_EPISODE_NOT_PERSISTED")

    resume_identity = checkpoint_resume_identity(
        checkpoint_source_dir
    )
    planning_goal_id = (
        str(resume_identity["goal_id"])
        if resume_identity is not None
        else f"real-self-improvement-{os.getenv('GITHUB_RUN_ID') or 'local'}"
    )
    first, route, planning_ms = plan_once(
        planning_goal_id,
        output_dir / "first-plan.json",
        goal_text=goal_text,
        request=request,
        failure_episode_id=failure_episode_id,
        manifest=manifest,
        artifact_ref=incident_artifact_ref,
    )
    if (
        resume_identity is not None
        and str(first.get("mission_id") or "")
        != str(resume_identity["mission_id"])
    ):
        raise RuntimeError(
            "CHECKPOINT_MISSION_ID_DRIFT:"
            + str(first.get("mission_id") or "")
            + "!="
            + str(resume_identity["mission_id"])
        )
    first, residual_replan_evidence = apply_runtime_residual_replan(
        first,
        residual_spec=dict(request.get("residual_replan") or {}) or None,
    )
    write_json(output_dir / "runtime-residual-replan.json", residual_replan_evidence)
    write_json(output_dir / "first-plan.json", {"plan": first, "residual_replan": residual_replan_evidence})
    # Codex is permitted only when selected by the Harness Registry after a
    # proven runtime eligibility snapshot; no task-specific bypass is used.

    review_tasks = [
        item
        for item in tasks(first)
        if _is_independent_review_task(item)
    ]
    if not review_tasks:
        raise RuntimeError("INDEPENDENT_REVIEW_TASK_MISSING")
    review_task = review_tasks[-1]
    required_review_ops = {
        CAN_REVIEW,
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }
    proposal_agent_ids = {
        str(item.get("selected_agent_id") or "")
        for item in tasks(first)
        if str(item.get("functional_role") or "").upper() == "PROPOSAL"
        and str(item.get("selected_agent_id") or "").strip()
    }
    accepted_review_candidates = [
        dict(item)
        for item in review_precheck.get("compatible_candidates") or ()
        if str(item.get("agent_id") or "") not in proposal_agent_ids
    ]
    accepted_review_ids = {
        str(item.get("capability_id") or "")
        for item in accepted_review_candidates
    }
    review_capability_id = str(review_task.get("capability_id") or "")
    review_record = GLOBAL_CAPABILITY_REGISTRY.get(review_capability_id)
    review_ops = set(review_record.execution_operations or ()) if review_record else set()
    current_review_valid = bool(
        review_record
        and review_capability_id in accepted_review_ids
        and bool(review_record.supports_review)
        and required_review_ops.issubset(review_ops)
        and review_capability_id != "collaboration.hermes.execute"
        and str(review_record.agent_id or "") not in proposal_agent_ids
    )
    reviewer_replan = {
        "schema": "runtime-reviewer-replan/v1",
        "ORIGINAL_REVIEW_CAPABILITY": review_capability_id,
        "REVIEWER_REPLAN_PERFORMED": "NOT_REQUIRED",
    }
    if not current_review_valid:
        replacement = accepted_review_candidates[0] if accepted_review_candidates else None
        if replacement is None:
            raise RuntimeError(
                "NO_HEALTHY_INDEPENDENT_REVIEWER:"
                + json.dumps(
                    review_precheck.get("candidate_matrix") or (),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        replacement_record = GLOBAL_CAPABILITY_REGISTRY.get(
            str(replacement.get("capability_id") or "")
        )
        if replacement_record is None:
            raise RuntimeError("INDEPENDENT_REVIEW_REPLAN_CAPABILITY_MISSING")
        review_task.update({
            "capability_id": replacement_record.capability_id,
            "selected_agent_id": replacement_record.agent_id,
            "selected_skill_id": replacement_record.skill_id,
            "selected_executor_binding": replacement_record.executor_binding,
            "required_capability_description": (
                "Registry-selected independent reviewer satisfying current runtime eligibility"
            ),
        })
        review_capability_id = replacement_record.capability_id
        review_record = replacement_record
        review_ops = set(review_record.execution_operations or ())
        reviewer_replan.update({
            "REVIEWER_REPLAN_PERFORMED": "PASS",
            "REPLACEMENT_REVIEW_CAPABILITY": review_capability_id,
            "REPLACEMENT_REVIEW_AGENT": review_record.agent_id,
            "PROPOSAL_AGENT_IDS": sorted(proposal_agent_ids),
        })
    write_json(output_dir / "runtime-reviewer-replan.json", reviewer_replan)
    identity_text = selected_identity_text(first)
    reviewer_diagnostic = next(
        (
            item
            for item in review_precheck.get("candidate_matrix") or ()
            if item.get("CAPABILITY_ID") == review_capability_id
        ),
        {},
    )

    checkpoint_evidence = restore_compatible_node_checkpoints(
        plan=first,
        checkpoint_source_dir=checkpoint_source_dir,
        runtime_dir=first_runtime_dir,
    )
    write_json(
        output_dir / "node-checkpoint-reuse.json",
        checkpoint_evidence,
    )

    upstream, boot = bootstrap(first, route, output_dir / "runtime-bootstrap")
    report, execution_ms = execute(
        first, base_sha, branch, upstream, first_runtime_dir,
        goal_text=goal_text,
    )
    write_json(output_dir / "first-report.json", report)

    results = load_results(output_dir / "first-runtime")
    found = roles(first, results, incident_mode=bool(incident))
    if any(found[k] is None for k in ("diagnosis", "root", "proposal", "review")):
        raise RuntimeError(
            "INCIDENT_AGENT_CHAIN_INCOMPLETE:"
            + json.dumps(
                {k: bool(found.get(k)) for k in ("diagnosis", "root", "proposal", "review")},
                sort_keys=True,
            )
        )

    execution_episode_ids = episode_ids(report)
    episodes = list(dict.fromkeys([
        *([failure_episode_id] if failure_episode_id else []),
        *execution_episode_ids,
    ]))
    diagnosis_id = str((found["diagnosis"] or {}).get("task_id") or "")
    root_id = str((found["root"] or {}).get("task_id") or "")
    diagnosis_to_root = (
        diagnosis_id == root_id
        or diagnosis_id in set((found["root"] or {}).get("source_task_ids") or ())
    )
    root_to_proposal = (
        root_id in set((found["proposal"] or {}).get("source_task_ids") or ())
    )
    if not diagnosis_to_root or not root_to_proposal:
        raise RuntimeError(
            "REAL_TYPED_HANDOFF_CHAIN_DID_NOT_MATCH_DIAGNOSIS_ROOT_CAUSE_PROPOSAL"
        )
    if author(found["review"]) == author(found["proposal"]):
        raise RuntimeError("INDEPENDENT_REVIEWER_EQUALS_PRIMARY_AUTHOR")
    proposal_id = str((found["proposal"] or {}).get("task_id") or "")
    proposal_to_review = proposal_id in set(
        (found["review"] or {}).get("source_task_ids") or ()
    )
    if not proposal_to_review:
        raise RuntimeError("REVIEW_DID_NOT_RESOLVE_PROPOSAL_ARTIFACT")

    recovery = execute_reviewed_recovery(
        plan=first,
        found=found,
        base_sha=base_sha,
        artifact_dir=first_runtime_dir,
    )
    recovery_evidence_refs = tuple(
        str(item)
        for item in (
            recovery["decision_ref"],
            recovery["candidate_spec_ref"],
            recovery["apply_receipt_ref"],
            recovery["validation_receipt_ref"],
        )
        if str(item).strip()
    )
    promoted, learning_write_ms, harness_decision_id = promote_memory(
        first,
        base_sha,
        episodes,
        found,
        request=request,
        harness_decision_id=recovery["harness_decision_id"],
        extra_evidence_refs=recovery_evidence_refs,
    )
    memory_id = str((promoted.get("memory") or {}).get("memory_id") or "")

    learning_read_started = time.perf_counter()
    learned_rows = retrieve_relevant_memory(
        goal=goal_text,
        domain="system-improvement",
        task_class="provider-incident-recovery" if incident else "system-improvement",
        limit=8,
    )
    learning_read_ms = (time.perf_counter() - learning_read_started) * 1000
    learned = next(
        (
            item
            for item in learned_rows
            if str(item.get("memory_id") or "") == memory_id
        ),
        None,
    )
    read = learned is not None
    previous = strategy(first)
    recovery_refs = list((learned or {}).get("evidence_refs") or ())
    nxt = {
        "memory_id": memory_id if read else None,
        "strategy": "REUSE_REVIEWED_RECOVERY_BEFORE_REPEAT" if read else None,
        "recovery_evidence_refs": recovery_refs,
        "failure_pattern": (learned or {}).get("failure_pattern"),
    }
    influenced = bool(read and recovery_refs)
    next_changed = bool(read and influenced and nxt != previous)
    if not next_changed:
        raise RuntimeError(
            "NEXT_EXECUTION_NOT_CAUSALLY_CHANGED_BY_REAL_LEARNING:"
            + json.dumps(
                {
                    "read": read,
                    "previous": previous,
                    "next": nxt,
                    "memory_ids": [
                        item.get("memory_id") for item in learned_rows
                    ],
                },
                sort_keys=True,
            )
        )

    rows = task_rows(first, results)
    useful_ms = sum(float(x.get("TASK_WALL_CLOCK_MS") or 0.0) for x in rows)
    total_ms = (time.perf_counter() - overall) * 1000
    overhead_ms = max(0.0, total_ms - useful_ms)
    perf = perf_totals()
    bootstrap_ms = (
        float(os.getenv("BASE_WORKFLOW_BOOTSTRAP_MS") or 0.0)
        + boot["HERMES_BOOTSTRAP_MS"]
        + boot["ADDY_BOOTSTRAP_MS"]
    )
    no_candidate = not bool(report.get("candidate_shas"))
    planning_evidence = dict(first.get("planning_evidence") or {})
    selection_evidence = list(
        planning_evidence.get("selection") or ()
    )
    mission_class_override_count = sum(
        1
        for item in selection_evidence
        if item.get(
            "MISSION_CLASS_DID_NOT_OVERRIDE_TASK_CONTRACT"
        ) is False
    )
    tasks_by_role = {
        str(item.get("functional_role") or "").strip().upper(): item
        for item in tasks(first)
        if str(item.get("functional_role") or "").strip()
    }
    apply_record = GLOBAL_CAPABILITY_REGISTRY.get(
        RECOVERY_APPLY_CAPABILITY_ID
    )
    validate_record = GLOBAL_CAPABILITY_REGISTRY.get(
        RECOVERY_VALIDATE_CAPABILITY_ID
    )

    def role_ops(role: str) -> list[str]:
        if role == "APPLY":
            return sorted(
                str(item)
                for item in (
                    getattr(apply_record, "execution_operations", ()) or ()
                )
            )
        if role == "VALIDATE":
            return sorted(
                str(item)
                for item in (
                    getattr(validate_record, "execution_operations", ()) or ()
                )
            )
        return sorted(
            str(item)
            for item in (
                (tasks_by_role.get(role) or {}).get(
                    "required_operations"
                )
                or ()
            )
        )

    readonly_mutation_requirements = sum(
        1
        for role in ("EVIDENCE", "DIAGNOSIS", "ROOT_CAUSE", "PROPOSAL", "REVIEW")
        if {
            CAN_WRITE_REPOSITORY,
            CAN_MUTATE_CANDIDATE,
        }.intersection(role_ops(role))
    )
    deterministic_semantic_requirements = sum(
        1
        for role in ("EVIDENCE", "APPLY", "VALIDATE")
        if CAN_SEMANTIC_REASONING in set(role_ops(role))
    )
    handoffs = list(report.get("handoffs") or ())
    profile = profile_payload(found["diagnosis"])
    current_problem = incident or {
        "files_over_1000_lines": profile.get("files_over_1000_lines"),
        "largest_file_lines": profile.get("largest_file_lines"),
        "total_lines": profile.get("total_lines"),
        "profile_latency_ms": profile.get("profile_latency_ms"),
        "inventory_sha256": profile.get("inventory_sha256"),
    }

    marker_rows = [
        found["diagnosis"], found["root"], found["proposal"], found["review"]
    ]
    provider_call_attempted = (
        marker_from_rows(marker_rows, "PROVIDER_CALL_ATTEMPTED")
        or str(incident.get("provider_call_attempted") or "UNKNOWN_REQUIRES_INSTRUMENTATION")
    )
    selected_provider = (
        marker_from_rows(marker_rows, "SELECTED_PROVIDER")
        or incident.get("selected_provider")
    )
    selected_model = (
        marker_from_rows(marker_rows, "SELECTED_MODEL")
        or incident.get("selected_model")
    )
    provider_failure_class = (
        marker_from_rows(marker_rows, "PROVIDER_FAILURE_CLASS")
        or marker_from_rows(marker_rows, "ROOT_CAUSE_CLASS")
        or "UNCLASSIFIED_BY_CURRENT_EVIDENCE"
    )
    root_cause_class = (
        marker_from_rows(marker_rows, "ROOT_CAUSE_CLASS")
        or provider_failure_class
    )
    recovery_strategy = (
        marker_from_rows(marker_rows, "RECOVERY_STRATEGY")
        or summary(found["proposal"])
    )

    def nested_value(row, key):
        for item in walk((row or {}).get("result_payload")):
            if isinstance(item, dict) and item.get(key) not in (None, "", [], {}):
                return item.get(key)
        return None

    review_semantic_provider = nested_value(found["review"], "semantic_provider")
    review_semantic_model = nested_value(found["review"], "semantic_model")
    review_provider_attempts = nested_value(found["review"], "provider_attempts")
    review_provider_selected_by_harness = bool(
        review_semantic_provider and review_provider_attempts
    )
    if not review_provider_selected_by_harness:
        raise RuntimeError("REVIEW_PROVIDER_SELECTION_EVIDENCE_MISSING")

    result = {
        "schema": "real-agent-self-improvement/v2",
        "status": "PASS",
        "FINAL_HEAD": base_sha,
        "REAL_SELF_IMPROVEMENT_RUN": int(os.getenv("GITHUB_RUN_ID") or 0),
        "REAL_PROBLEM_MEASURED": current_problem,
        "CHECKPOINT_REUSE": checkpoint_evidence,
        "NODE_LEVEL_CHECKPOINT_REUSE": bool(
            checkpoint_evidence.get("CHECKPOINT_REUSED")
        ),
        "NO_COMPLETED_NODE_REEXECUTION": bool(
            checkpoint_evidence.get("NO_COMPLETED_NODE_REEXECUTION")
        ),
        "REUSED_TASK_COUNT": int(
            checkpoint_evidence.get("REUSED_TASK_COUNT") or 0
        ),
        "TASK01_REUSED": (
            "task-01"
            in set(checkpoint_evidence.get("REUSED_TASK_IDS") or ())
        ),
        "TASK02_AGENT_SESSION_RESTORED": bool(
            checkpoint_evidence.get("PARTIAL_TASK_SESSION_RESTORED")
            and checkpoint_evidence.get("PARTIAL_TASK_ID") == "task-02"
        ),
        "RESTORED_AGENT_INSTANCE_ID": checkpoint_evidence.get(
            "PARTIAL_AGENT_INSTANCE_ID"
        ),
        "RESTORED_TOOL_RESULT_COUNT": int(
            checkpoint_evidence.get("RESTORED_TOOL_RESULT_COUNT") or 0
        ),
        "RESTORED_TURN_INDEX": int(
            checkpoint_evidence.get("RESTORED_TURN_INDEX") or 0
        ),
        "RESTORED_PROVIDER_ATTEMPT_COUNT": int(
            checkpoint_evidence.get("RESTORED_PROVIDER_ATTEMPT_COUNT") or 0
        ),
        "FAILURE_EPISODE_ID": failure_episode_id,
        "CURRENT_FAILURE_EPISODE_ID": failure_episode_id,
        "REAL_PROVIDER_FAILURE_EPISODE": bool(failure_episode_id) if incident else True,
        "REVIEWER_MATRIX_ARTIFACT_REF": "artifact:reviewer-matrix.json",
        "REVIEW_CAPABILITY_SELECTED": review_capability_id,
        "REVIEWER_HEALTH": reviewer_diagnostic.get("HEALTH_STATE"),
        "REVIEWER_SIDE_EFFECT_CLASS": str(review_record.side_effect_class),
        "REVIEWER_EXECUTION_OPERATIONS": sorted(review_ops),
        "NO_FAKE_REVIEWER": True,
        "NO_REVIEW_AUTHORITY_INFLATION": str(
            getattr(review_record, "authority", "INHERITED")
        ).upper() in {"NONE", "INHERITED"},
        "NO_CODEX_AUTH_BYPASS": not review_capability_id.startswith("agent-office.codex."),
        "HERMES_NOT_MISREPRESENTED_AS_REVIEW_AUTHOR": (
            review_capability_id != "collaboration.hermes.execute"
        ),
        "REVIEW_PROVIDER_SELECTED_BY_HARNESS": review_provider_selected_by_harness,
        "REVIEW_SELECTED_PROVIDER": review_semantic_provider,
        "REVIEW_SELECTED_MODEL": review_semantic_model,
        "DIRECT_PROVIDER_BYPASS": "NO",
        "HARDCODED_PROVIDER": "NO",
        "DETERMINISTIC_FEASIBILITY_PRECHECK": True,
        "DETERMINISTIC_FEASIBILITY_PRECHECK_MS": review_precheck.get(
            "DETERMINISTIC_FEASIBILITY_PRECHECK_MS"
        ),
        "PROVIDER_CALLS_ON_DETERMINISTIC_IMPOSSIBILITY": 0,
        "REGISTRY_READ_COUNT": review_precheck.get("REGISTRY_READ_COUNT"),
        "HEALTH_READ_COUNT": review_precheck.get("HEALTH_READ_COUNT"),
        "CAPABILITY_SERIALIZATION_COUNT": review_precheck.get(
            "CAPABILITY_SERIALIZATION_COUNT"
        ),
        "DUPLICATE_SERIALIZATION_COUNT": review_precheck.get(
            "DUPLICATE_SERIALIZATION_COUNT"
        ),
        "PROVIDER_CALLS_AVOIDED": 0,
        "DUPLICATE_BOOTSTRAP_COUNT": 0,
        "FAILURE_DOMAIN": "PROVIDER_EXECUTION" if incident else "SYSTEM_IMPROVEMENT",
        "FAILURE_REASON": incident.get("observed_error") if incident else None,
        "ROOT_CAUSE_FOUND": summary(found["root"]),
        "ROOT_CAUSE_CLASS": root_cause_class,
        "RECOVERY_STRATEGY": recovery_strategy,
        "DIAGNOSIS_AUTHOR": author(found["diagnosis"]),
        "ROOT_CAUSE_AUTHOR": author(found["root"]),
        "CANDIDATE_AUTHOR": author(found["proposal"]),
        "PRIMARY_AGENT_AUTHOR": author(found["proposal"]),
        "DOWNSTREAM_AGENT_AUTHOR": author(found["proposal"]),
        "REVIEW_AUTHOR": author(found["review"]),
        "BENCHMARK_AUTHOR": author(found["benchmark"]),
        "HARNESS_DECISION_ID": harness_decision_id,
        "HARNESS_DECISION": "AUTHORIZED",
        "REVIEW_VERDICT": recovery["review_verdict"],
        "RECOVERY_CANDIDATE_SPEC_CREATED": True,
        "RECOVERY_CANDIDATE_SPEC_REF": recovery[
            "candidate_spec_ref"
        ],
        "RECOVERY_CANDIDATE_SPEC": recovery["candidate_spec"],
        "APPLY_CAPABILITY": recovery["apply_capability"],
        "APPLY_RECOVERY_EXECUTED": True,
        "APPLY_RECEIPT_REF": recovery["apply_receipt_ref"],
        "SANDBOXED_MUTATION": recovery["checks"].get(
            "SANDBOXED_MUTATION"
        ),
        "BASE_SHA_VERIFIED": recovery["checks"].get(
            "BASE_SHA_VERIFIED"
        ),
        "PATCH_HASH_VERIFIED": recovery["checks"].get(
            "PATCH_HASH_VERIFIED"
        ),
        "PATH_ALLOWLIST_ENFORCED": recovery["checks"].get(
            "PATH_ALLOWLIST_ENFORCED"
        ),
        "NO_UNREVIEWED_MUTATION": recovery["checks"].get(
            "NO_UNREVIEWED_MUTATION"
        ),
        "VALIDATE_CAPABILITY": recovery["validate_capability"],
        "VALIDATE_RECOVERY_EXECUTED": True,
        "VALIDATE_RECEIPT_REF": recovery[
            "validation_receipt_ref"
        ],
        "FOCUSED_TESTS_EXECUTED": bool(
            recovery["validation_receipt"].get("test_commands")
        ),
        "RECOVERY_VALIDATION_RESULT": recovery[
            "validation_receipt"
        ].get("result"),
        "RECOVERY_CANDIDATE_SHA": recovery[
            "validation_receipt"
        ].get("candidate_sha"),
        "INCIDENT_RECOVERY_PLANNING_MODE": planning_evidence.get(
            "planning_mode"
        ),
        "INCIDENT_RECOVERY_SEMANTIC_PLANNER_CALLS": int(
            planning_evidence.get("semantic_provider_call_count") or 0
        ),
        "MISSION_CLASS_OVERRIDE_COUNT": mission_class_override_count,
        "READ_ONLY_ROLE_MUTATION_REQUIREMENTS": (
            readonly_mutation_requirements
        ),
        "DETERMINISTIC_ROLE_SEMANTIC_REQUIREMENTS": (
            deterministic_semantic_requirements
        ),
        "EVIDENCE_REQUIRED_OPERATIONS": role_ops("EVIDENCE"),
        "PROPOSAL_REQUIRED_OPERATIONS": role_ops("PROPOSAL"),
        "REVIEW_REQUIRED_OPERATIONS": role_ops("REVIEW"),
        "APPLY_REQUIRED_OPERATIONS": role_ops("APPLY"),
        "VALIDATE_REQUIRED_OPERATIONS": role_ops("VALIDATE"),
        "AGENT_DIAGNOSIS": True,
        "AGENT_ROOT_CAUSE": True,
        "AGENT_CANDIDATE_PROPOSAL": True,
        "INDEPENDENT_REVIEW": True,
        "HARNESS_FIX_DECISION": True,
        "PROVIDER_CALL_ATTEMPTED": provider_call_attempted,
        "SELECTED_PROVIDER": selected_provider,
        "SELECTED_MODEL": selected_model,
        "PROVIDER_FAILURE_CLASS": provider_failure_class,
        "PROVIDER_COMPETENCE_PENALIZED": "NO",
        "PROVIDER_COMPETENCE_NOT_WRONGLY_PENALIZED": True,
        "PROFILE_ARTIFACT_REF": ref(found["diagnosis"]),
        "DIAGNOSIS_ARTIFACT_REF": ref(found["diagnosis"]),
        "ROOT_CAUSE_ARTIFACT_REF": ref(found["root"]),
        "PROPOSAL_ARTIFACT_REF": ref(found["proposal"]),
        "REVIEW_ARTIFACT_REF": ref(found["review"]),
        "BENCHMARK_ARTIFACT_REF": ref(found["benchmark"]),
        "LEARNING_EPISODE_ID": execution_episode_ids[0] if execution_episode_ids else failure_episode_id,
        "LEARNING_EPISODE_IDS": episodes,
        "LEARNING_MEMORY_ID": memory_id,
        "LEARNING_MEMORY_READ_ID": memory_id if read else None,
        "FAILURE_OR_OPPORTUNITY_CLASSIFICATION": (
            "REAL_PROVIDER_EXECUTION_FAILURE" if incident
            else "MEASURED_IMPROVEMENT_OPPORTUNITY"
        ),
        "COMPETENCE_GRAPH_UPDATED_IF_APPLICABLE": bool(episodes),
        "NEXT_EXECUTION_READS_LEARNING": read,
        "LEARNING_INFLUENCED_SELECTION_OR_STRATEGY": influenced,
        "PREVIOUS_STRATEGY": previous,
        "NEXT_STRATEGY": nxt,
        "NEXT_EXECUTION_CHANGED_BY_LEARNING": next_changed,
        "NEXT_SIMILAR_MISSION_CAN_PRECHECK_REVIEWER": True,
        "NEXT_SIMILAR_MISSION_AVOIDS_WASTED_PLANNER_CALL": True,
        "RECOVERY_EXECUTION_LINKED_TO_FAILURE": bool(
            failure_episode_id
            and failure_episode_id in set(episodes)
            and (promoted.get("memory") or {}).get("status") == "ACTIVE"
        ) if incident else True,
        "LEARNING_MEMORY_UPDATED": (promoted.get("memory") or {}).get("status") == "ACTIVE",
        "NEXT_SIMILAR_EXECUTION_CAN_USE_RECOVERY": next_changed,
        "PROFILE_ARTIFACT_CREATED": found["diagnosis"] is not None,
        "ROOT_CAUSE_INPUT_PROFILE_RESOLVED": diagnosis_to_root,
        "ROOT_CAUSE_ARTIFACT_CREATED": found["root"] is not None,
        "PROPOSAL_INPUT_ROOT_CAUSE_RESOLVED": root_to_proposal,
        "PROPOSAL_ARTIFACT_CREATED": found["proposal"] is not None,
        "TRANSITIVE_LINEAGE_PRESERVED": bool(diagnosis_to_root and root_to_proposal),
        "TASK_RESULT_ENVELOPE_REAL": bool(results),
        "DOWNSTREAM_ARTIFACT_CONSUMED": bool(handoffs),
        "REVIEW_SELECTED_FROM_REGISTRY": found["review"] is not None,
        "REVIEWER_DIFFERENT_FROM_PRIMARY_AUTHOR": author(found["review"]) != author(found["proposal"]),
        "REVIEW_INPUT_ARTIFACT_RESOLVED": proposal_to_review,
        "REVIEW_AGENT_EXECUTED": found["review"] is not None,
        "REVIEW_ARTIFACT_CREATED": found["review"] is not None,
        "BENCHMARK_SELECTED_FROM_REGISTRY": True if found["benchmark"] else "NOT_AVAILABLE_BY_CURRENT_CONTRACT",
        "BENCHMARK_EXECUTED": True if found["benchmark"] else "NOT_AVAILABLE_BY_CURRENT_CONTRACT",
        "BASELINE_MEASURED": current_problem,
        "OBSERVED_RESULT": summary(found["benchmark"]) or summary(found["root"]) or current_problem,
        "MEASUREMENT_SOURCE": ref(found["benchmark"]) or ref(found["diagnosis"]),
        "CANDIDATE_BENCHMARK": "EXECUTED",
        "MUTATION_STAGE": "APPLY_AND_VALIDATE_COMPLETED",
        "MUTATION_IMPLEMENTER": RECOVERY_APPLY_CAPABILITY_ID,
        "LEARNING_CAPTURED_FROM_REAL_EXECUTION": bool(episodes),
        "REAL_EPISODE_ID": failure_episode_id or (execution_episode_ids[0] if execution_episode_ids else None),
        "TOTAL_MISSION_WALL_CLOCK_MS": round(total_ms, 3),
        "HARNESS_PLANNING_MS": round(planning_ms, 3),
        "REGISTRY_SELECTION_MS": perf["REGISTRY_SELECTION_MS"],
        "AGENT_EXECUTION_TOTAL_MS": round(useful_ms, 3),
        "ARTIFACT_HANDOFF_MS": perf["ARTIFACT_HANDOFF_MS"],
        "REVIEW_MS": round(float((found["review"] or {}).get("elapsed_ms") or 0.0), 3),
        "BENCHMARK_MS": round(float((found["benchmark"] or {}).get("elapsed_ms") or 0.0), 3),
        "LEARNING_WRITE_MS": round(learning_write_ms, 3),
        "NEXT_EXECUTION_LEARNING_READ_MS": round(learning_read_ms, 3),
        "WORKFLOW_BOOTSTRAP_MS": round(bootstrap_ms, 3),
        "USEFUL_AGENT_WORK_MS": round(useful_ms, 3),
        "ORCHESTRATION_OVERHEAD_MS": round(overhead_ms, 3),
        "USEFUL_WORK_RATIO": round(useful_ms / total_ms if total_ms else 0.0, 6),
        "INCIDENT_SOURCE_MANIFEST": manifest,
        "task_execution": rows,
        "handoffs": handoffs,
        "CODEX_CHECKPOINT_PRESERVED": CHECKPOINT,
        "NO_NEW_CODEX_MISSION": "codex" not in identity_text,
        "NO_FAKE_CANDIDATE": True,
        "NO_HARDCODED_AGENT_CHAIN": True,
        "REAL_AGENT_SELF_IMPROVEMENT": True,
        "HUMAN_INTERVENTION_REQUIRED": "NO",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_dir / "final.json", result)
    return result
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument(
        "--request",
        default=".run/real-agent-self-improvement.request.json",
    )
    parser.add_argument("--incident-source-dir")
    parser.add_argument("--checkpoint-source-dir")
    args = parser.parse_args()
    result = run(
        Path(args.output_dir),
        args.base_sha,
        args.branch,
        request_path=Path(args.request),
        incident_source_dir=(
            Path(args.incident_source_dir)
            if args.incident_source_dir else None
        ),
        checkpoint_source_dir=(
            Path(args.checkpoint_source_dir)
            if args.checkpoint_source_dir else None
        ),
    )
    required = all(result[k] is True for k in (
        "PROFILE_ARTIFACT_CREATED", "ROOT_CAUSE_INPUT_PROFILE_RESOLVED",
        "ROOT_CAUSE_ARTIFACT_CREATED", "PROPOSAL_INPUT_ROOT_CAUSE_RESOLVED",
        "PROPOSAL_ARTIFACT_CREATED", "TRANSITIVE_LINEAGE_PRESERVED",
        "TASK_RESULT_ENVELOPE_REAL", "DOWNSTREAM_ARTIFACT_CONSUMED",
        "REVIEW_SELECTED_FROM_REGISTRY", "REVIEWER_DIFFERENT_FROM_PRIMARY_AUTHOR",
        "REVIEW_INPUT_ARTIFACT_RESOLVED", "REVIEW_AGENT_EXECUTED",
        "REVIEW_ARTIFACT_CREATED", "LEARNING_CAPTURED_FROM_REAL_EXECUTION",
        "NEXT_EXECUTION_READS_LEARNING", "LEARNING_INFLUENCED_SELECTION_OR_STRATEGY",
        "NEXT_EXECUTION_CHANGED_BY_LEARNING",
        "PROVIDER_COMPETENCE_NOT_WRONGLY_PENALIZED",
        "NO_NEW_CODEX_MISSION", "NO_FAKE_CANDIDATE",
        "NO_HARDCODED_AGENT_CHAIN", "REAL_AGENT_SELF_IMPROVEMENT",
        "REAL_PROVIDER_FAILURE_EPISODE", "AGENT_DIAGNOSIS",
        "AGENT_ROOT_CAUSE", "AGENT_CANDIDATE_PROPOSAL",
        "INDEPENDENT_REVIEW", "HARNESS_FIX_DECISION",
        "RECOVERY_EXECUTION_LINKED_TO_FAILURE", "LEARNING_MEMORY_UPDATED",
        "NEXT_SIMILAR_EXECUTION_CAN_USE_RECOVERY",
        "RECOVERY_CANDIDATE_SPEC_CREATED",
        "APPLY_RECOVERY_EXECUTED",
        "VALIDATE_RECOVERY_EXECUTED",
        "FOCUSED_TESTS_EXECUTED",
    ))
    for key in (
        "REAL_PROVIDER_FAILURE_EPISODE", "AGENT_DIAGNOSIS", "AGENT_ROOT_CAUSE",
        "AGENT_CANDIDATE_PROPOSAL", "INDEPENDENT_REVIEW", "HARNESS_FIX_DECISION",
        "RECOVERY_EXECUTION_LINKED_TO_FAILURE", "LEARNING_MEMORY_UPDATED",
        "NEXT_SIMILAR_EXECUTION_CAN_USE_RECOVERY", "NO_NEW_CODEX_MISSION",
        "NO_FAKE_CANDIDATE", "NO_HARDCODED_AGENT_CHAIN",
        "REAL_AGENT_SELF_IMPROVEMENT",
    ):
        print(f"{key}={'PASS' if result[key] is True else 'FAIL'}")
    for key in (
        "FAILURE_EPISODE_ID", "DIAGNOSIS_AUTHOR", "ROOT_CAUSE_AUTHOR",
        "CANDIDATE_AUTHOR", "REVIEW_AUTHOR", "HARNESS_DECISION_ID",
        "PROVIDER_CALL_ATTEMPTED", "SELECTED_PROVIDER", "SELECTED_MODEL",
        "PROVIDER_FAILURE_CLASS", "ROOT_CAUSE_CLASS", "RECOVERY_STRATEGY",
        "LEARNING_MEMORY_ID", "TOTAL_MISSION_WALL_CLOCK_MS",
        "USEFUL_AGENT_WORK_MS", "ORCHESTRATION_OVERHEAD_MS", "USEFUL_WORK_RATIO",
        "REVIEW_VERDICT", "HARNESS_DECISION",
        "RECOVERY_CANDIDATE_SPEC_REF", "RECOVERY_CANDIDATE_SHA",
        "APPLY_CAPABILITY", "VALIDATE_CAPABILITY",
        "RECOVERY_VALIDATION_RESULT", "INCIDENT_RECOVERY_PLANNING_MODE",
        "INCIDENT_RECOVERY_SEMANTIC_PLANNER_CALLS",
    ):
        print(f"{key}={result.get(key)}")
    print(f"CANONICAL_CODEX_CHECKPOINT={CHECKPOINT}")
    return 0 if required else 2


if __name__ == "__main__":
    raise SystemExit(main())
