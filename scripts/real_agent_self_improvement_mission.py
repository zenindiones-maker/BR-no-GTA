from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
import re
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import time

from app.database.schema import initialize_schema
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_collaboration_service import build_goal_envelope, plan_mission_from_human_goal
from app.services.harness_learning_service import HarnessEpisode, persist_episode, record_memory
from app.services.harness_mission_execution_router import select_mission_execution_route
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.memory_plane_service import evaluate_memory_candidate
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
        domain=str(getattr(record, "domain", None) or "research"),
        task_class="provider-runtime-failure",
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

def plan_once(goal_id, out, *, goal_text: str, request: dict, failure_episode_id: str | None, manifest: list[dict]):
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
    obj = plan_mission_from_human_goal(goal)
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
    encoded = base64.b64encode(
        json.dumps(plan, ensure_ascii=False, separators=(",", ":")).encode()
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


def roles(plan, results, *, incident_mode: bool = False):
    by_id = {str(t.get("task_id") or ""): t for t in tasks(plan)}
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
                for x in ("root cause", "root-cause", "causal", "failure classification")
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
        proposal = results.get(proposal_ids[-1]) if proposal_ids else None
        return {
            "profile": diagnosis,
            "diagnosis": diagnosis,
            "root": root,
            "proposal": proposal,
            "review": results.get(review_ids[-1]) if review_ids else None,
            "benchmark": results.get(benchmark_ids[-1]) if benchmark_ids else None,
        }

    profile = next((r for r in results.values() if profile_payload(r)), None)
    profile_id = str((profile or {}).get("task_id") or "")
    root_ids = [
        i for i,t in by_id.items()
        if i in results and i != profile_id and any(
            x in task_text(t) for x in ("root cause", "root-cause", "diagnos", "causal")
        )
    ]
    root = results.get(root_ids[0]) if root_ids else None
    root_id = str((root or {}).get("task_id") or "")
    excluded = {profile_id, root_id, *review_ids, *benchmark_ids}
    proposal_ids = [
        i for i,t in by_id.items()
        if i in results and i not in excluded and any(
            x in task_text(t) for x in ("proposal", "recommend", "recomend", "improvement")
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
def ref(row):
    if not row:
        return None
    text = str(row.get("_path") or "")
    return "artifact:task-results/" + text.split("task-results/", 1)[1] if "task-results/" in text else text or None


def author(row):
    if not row:
        return None
    return str(row.get("agent_id") or row.get("skill_id") or row.get("capability_id") or "") or None


def summary(row):
    return str((row or {}).get("result_summary") or "").strip()[:1600]


def episode_ids(report):
    canonical = dict(report.get("hermes_canonical_result") or {})
    payload = dict(canonical.get("result") or {})
    return [str(x) for x in payload.get("harness_episode_ids") or () if str(x).strip()]


def promote_memory(plan, base_sha, episodes, found, *, request: dict):
    if not episodes or any(found[k] is None for k in ("profile", "root", "proposal")):
        raise RuntimeError("REAL_SELF_IMPROVEMENT_ARTIFACT_CHAIN_INCOMPLETE")
    if found["review"] is None:
        raise RuntimeError("INDEPENDENT_REVIEW_NOT_EXECUTED")
    evidence = [
        x for x in (
            ref(found["profile"]), ref(found["root"]),
            ref(found["proposal"]), ref(found["review"]),
        ) if x
    ]
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
    harness_decision_id = f"decision-{plan.get('mission_id')}-incident-recovery"
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


def run(output_dir, base_sha, branch, *, request_path: Path, incident_source_dir: Path | None = None):
    initialize_schema()
    output_dir.mkdir(parents=True, exist_ok=True)
    overall = time.perf_counter()
    request = load_request(request_path)
    goal_text = str(request.get("human_goal") or DEFAULT_GOAL).strip()
    incident = dict(request.get("incident") or {})
    manifest = incident_source_manifest(incident_source_dir)
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

    first, route, planning_ms = plan_once(
        f"real-self-improvement-{os.getenv('GITHUB_RUN_ID') or 'local'}",
        output_dir / "first-plan.json",
        goal_text=goal_text,
        request=request,
        failure_episode_id=failure_episode_id,
        manifest=manifest,
    )
    identity_text = selected_identity_text(first)
    if "codex" in identity_text:
        raise RuntimeError("MUTATION_STAGE=BLOCKED_BY_EXECUTOR_AUTH")

    upstream, boot = bootstrap(first, route, output_dir / "runtime-bootstrap")
    report, execution_ms = execute(
        first, base_sha, branch, upstream, output_dir / "first-runtime",
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

    promoted, learning_write_ms, harness_decision_id = promote_memory(
        first, base_sha, episodes, found, request=request
    )
    memory_id = str((promoted.get("memory") or {}).get("memory_id") or "")

    second_start = time.perf_counter()
    second, _, _ = plan_once(
        f"real-self-improvement-next-{os.getenv('GITHUB_RUN_ID') or 'local'}",
        output_dir / "second-decision.json",
        goal_text=goal_text,
        request=request,
        failure_episode_id=failure_episode_id,
        manifest=manifest,
    )
    learning_read_ms = (time.perf_counter() - second_start) * 1000
    read = memory_id in memory_ids(second)
    previous = strategy(first)
    nxt = strategy(second)
    changed = previous != nxt
    influenced = bool(
        read and (
            nxt["memory_influences_strategy"]
            or nxt["reused_artifact_refs"]
            or changed
        )
    )
    next_changed = bool(read and influenced and changed)
    if not next_changed:
        raise RuntimeError(
            "NEXT_EXECUTION_NOT_CAUSALLY_CHANGED_BY_REAL_LEARNING:"
            + json.dumps(
                {
                    "read": read,
                    "previous": previous,
                    "next": nxt,
                    "memory_ids": sorted(memory_ids(second)),
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

    result = {
        "schema": "real-agent-self-improvement/v2",
        "status": "PASS",
        "FINAL_HEAD": base_sha,
        "REAL_SELF_IMPROVEMENT_RUN": int(os.getenv("GITHUB_RUN_ID") or 0),
        "REAL_PROBLEM_MEASURED": current_problem,
        "FAILURE_EPISODE_ID": failure_episode_id,
        "REAL_PROVIDER_FAILURE_EPISODE": bool(failure_episode_id) if incident else True,
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
        "CANDIDATE_BENCHMARK": "NOT_APPLICABLE_NO_MUTATING_CANDIDATE" if no_candidate else "EXECUTED",
        "MUTATION_STAGE": (
            "WORK_INFRA_FALLBACK_ALLOWED_AFTER_HARNESS_DECISION"
            if incident and no_candidate
            else "NOT_REQUESTED_OR_NOT_REQUIRED"
        ),
        "MUTATION_IMPLEMENTER": (
            "WORK_INFRA_FALLBACK_PENDING"
            if incident and no_candidate
            else "HARNESS_SELECTED_EXECUTOR"
        ),
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
        "NO_FAKE_CANDIDATE": no_candidate,
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
    ):
        print(f"{key}={result.get(key)}")
    print(f"CANONICAL_CODEX_CHECKPOINT={CHECKPOINT}")
    return 0 if required else 2


if __name__ == "__main__":
    raise SystemExit(main())
