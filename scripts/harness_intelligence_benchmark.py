from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.database.schema import initialize_schema
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_collaboration_service import (
    _legacy_mission_requirements,
    build_goal_envelope,
    plan_mission_from_human_goal,
)
from app.services.harness_mission_execution_router import select_mission_execution_route
from app.services.telegram_conversation_service import classify_conversation_intent


CASES = (
    {
        "case_id": "slow-self-diagnosis",
        "goal": "Isso está uma carroça, descobre sozinho o que está acontecendo.",
        "subject": "desempenho geral do sistema",
        "conversation_state": {
            "active_stage": "execution",
            "prior_observation": "latência percebida aumentou sem causa confirmada",
        },
    },
    {
        "case_id": "agent-value",
        "goal": "Esses agentes estão realmente ajudando ou só gastando processamento?",
        "subject": "custo operacional dos agentes",
        "conversation_state": {
            "active_task": "system improvement",
            "prior_observation": "há múltiplos especialistas disponíveis",
        },
    },
    {
        "case_id": "artificial-video",
        "goal": "O vídeo ficou artificial. Descobre onde está o problema sem eu te dizer qual etapa olhar.",
        "subject": "qualidade audiovisual",
        "conversation_state": {
            "active_artifact": "latest-video",
            "prior_observation": "problema percebido no resultado final, etapa desconhecida",
        },
    },
    {
        "case_id": "reuse-learning",
        "goal": "Usa o que você aprendeu nas últimas execuções para não repetir os mesmos erros.",
        "subject": "aprendizado operacional",
        "conversation_state": {
            "active_stage": "planning",
            "prior_observation": "há histórico de execuções anteriores a consultar",
        },
    },
    {
        "case_id": "open-investigation",
        "goal": "Não sei exatamente o que está errado. Investiga o sistema e propõe a melhor sequência de trabalho.",
        "subject": "saúde geral do sistema",
        "conversation_state": {
            "execution_status": "uncertain",
            "prior_observation": "sintoma ainda não localizado",
        },
    },
    {
        "case_id": "audio-strange",
        "goal": "O áudio melhorou mas alguma coisa ainda está estranha. Descobre o que é antes de mexer.",
        "subject": "qualidade de áudio",
        "conversation_state": {
            "active_artifact": "latest-audio",
            "prior_observation": "áudio melhorou versus baseline anterior, anomalia residual permanece",
        },
    },
    {
        "case_id": "prove-useless-process",
        "goal": "Tem processo inútil aqui. Prova qual é antes de remover.",
        "subject": "trabalho redundante",
        "conversation_state": {
            "active_stage": "diagnosis",
            "prior_observation": "suspeita de processamento redundante ainda não provada",
        },
    },
    {
        "case_id": "quality-without-latency",
        "goal": "Quero melhorar a qualidade geral sem deixar o pipeline mais lento.",
        "subject": "tradeoff qualidade e desempenho",
        "conversation_state": {
            "active_stage": "optimization",
            "prior_observation": "latência atual deve ser preservada como constraint",
        },
    },
    {
        "case_id": "self-select-specialists",
        "goal": "Vê sozinho quais especialistas você precisa para resolver isso.",
        "subject": "seleção adaptativa de capacidades",
        "conversation_state": {
            "active_task": "system diagnosis",
            "prior_observation": "o humano não especificou agentes nem ferramentas",
        },
    },
    {
        "case_id": "regression-analysis",
        "goal": "Esse resultado ficou pior que o anterior. Descobre o que regrediu.",
        "subject": "regressão de resultado",
        "conversation_state": {
            "active_artifact": "latest-result",
            "prior_observation": "resultado atual é pior que o baseline anterior",
        },
    },
)


@dataclass(frozen=True)
class Metric:
    passed: bool
    state: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(value: Any) -> set[str]:
    stop = {
        "isso", "esta", "está", "para", "como", "mais", "menos", "aqui",
        "antes", "depois", "voce", "você", "quero", "qual", "quais", "esse",
        "essa", "ficou", "ainda", "sem", "nao", "não", "que", "uma", "uns",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9À-ÿ_-]{3,}", str(value or "").casefold())
        if token not in stop
    }


def _metric(value: bool, detail: str, *, no_evidence: bool = False) -> Metric:
    if no_evidence:
        return Metric(True, "PASS_NO_RELEVANT_EVIDENCE", detail)
    return Metric(bool(value), "PASS" if value else "FAIL", detail)


def _signature(plan) -> tuple[Any, ...]:
    proposal = dict(plan.semantic_plan_proposal or {})
    proposal_tasks = list(proposal.get("tasks") or ())
    task_class_by_id = {
        str(item.get("task_id") or ""): str(item.get("task_class") or "")
        for item in proposal_tasks
    }
    routed = plan.collaboration_plan.tasks
    return (
        len(routed),
        tuple(sorted(len(task.dependencies) for task in routed)),
        tuple(task_class_by_id.get(task.task_id, "") for task in routed),
        tuple(task.capability_id for task in routed),
    )


def _case_metrics(case: dict[str, Any], plan) -> dict[str, Metric]:
    proposal = dict(plan.semantic_plan_proposal or {})
    interpreted = str(proposal.get("interpreted_goal") or "")
    human_overlap = _tokens(case["goal"]) & _tokens(interpreted)
    tasks = list(plan.collaboration_plan.tasks)
    raw_proposal_tasks = list(proposal.get("tasks") or ())
    legacy = _legacy_mission_requirements(plan.goal)
    legacy_ids = [str(item["task_id"]) for item in legacy]
    new_ids = [task.task_id for task in tasks]

    valid_registry = True
    invalid_records: list[str] = []
    for task in tasks:
        record = GLOBAL_CAPABILITY_REGISTRY.get(task.capability_id)
        if (
            record is None
            or not record.execution_enabled
            or task.action not in record.allowed_actions
            or task.selected_executor_binding != record.executor_binding
        ):
            valid_registry = False
            invalid_records.append(task.capability_id)

    context_notes = [
        str(item).strip()
        for item in proposal.get("context_usage_notes") or ()
        if str(item).strip()
    ]
    bounded = dict(plan.bounded_memory_context or {})
    memory_present = bool(
        bounded.get("conversation_memory")
        or bounded.get("operational_memory")
        or bounded.get("knowledge_memory")
        or bounded.get("artifact_lineage_memory")
    )
    competence_exists = bool(
        learning_repository.list_competence(status="ACTIVE", limit=1)
    )
    bad_path_known = bool(
        str((plan.provider_health.get("opencode") or {}).get("state") or "")
        in {"UPSTREAM_DENIED", "BLOCKED", "QUARANTINED"}
        or any(
            str(item.get("failure_pattern") or "")
            for item in learning_repository.list_memories(
                status="ACTIVE",
                memory_type="FAILURE",
                limit=5,
            )
        )
    )
    route = select_mission_execution_route(plan.to_dict())
    provider_calls = int(
        plan.planning_evidence.get("semantic_provider_call_count") or 0
    )

    forbidden_authority_fields = {
        "selected_executor_binding",
        "selected_agent_id",
        "authorization_id",
        "publication_authority",
        "promotion_decision",
    }
    proposal_authority_clean = all(
        not (forbidden_authority_fields & set(item))
        for item in raw_proposal_tasks
        if isinstance(item, dict)
    )

    return {
        "INTENT_UNDERSTANDING": _metric(
            bool(interpreted and human_overlap and proposal.get("required_outcomes")),
            f"interpreted_goal overlap tokens={sorted(human_overlap)[:8]}",
        ),
        "CONTEXT_USAGE": _metric(
            bool(context_notes),
            f"context_usage_notes={context_notes[:4]}",
        ),
        "MEMORY_USAGE": _metric(
            bool(plan.memory_influences_strategy),
            (
                "relevant bounded memory changed strategy"
                if plan.memory_influences_strategy
                else "no relevant canonical memory was available in this runtime"
            ),
            no_evidence=not memory_present,
        ),
        "DYNAMIC_TASK_DECOMPOSITION": _metric(
            bool(
                plan.planning_mode == "SEMANTIC_ADAPTIVE"
                and tasks
                and (not legacy_ids or new_ids != legacy_ids)
            ),
            f"legacy_task_ids={legacy_ids}; new_task_ids={new_ids}",
        ),
        "CAPABILITY_SELECTION": _metric(
            valid_registry,
            f"selected={[task.capability_id for task in tasks]}; invalid={invalid_records}",
        ),
        "COMPETENCE_AWARE_SELECTION": _metric(
            bool(plan.competence_influences_selection),
            (
                "competence affected Harness ranking"
                if plan.competence_influences_selection
                else "no relevant competence record was available in this runtime"
            ),
            no_evidence=not competence_exists,
        ),
        "BAD_PATH_AVOIDANCE": _metric(
            bool(plan.known_bad_paths_avoided),
            f"avoided={list(plan.known_bad_paths_avoided)}",
            no_evidence=not bad_path_known,
        ),
        "NO_HARDCODED_TEAM_REQUIRED": _metric(
            proposal_authority_clean
            and all(
                name.casefold() not in case["goal"].casefold()
                for name in ("codex", "hermes", "agent office")
            ),
            "human goal contained no specialist names; proposal contained no authority-bearing executor fields",
        ),
        "NO_UNNECESSARY_PROVIDER_CALL": _metric(
            1 <= provider_calls <= 2,
            f"semantic_provider_call_count={provider_calls}",
        ),
        "PLAN_VALIDITY": _metric(
            plan.authority == "DEEPSEEK_HARNESS"
            and plan.collaboration_plan.authority == "DEEPSEEK_HARNESS"
            and valid_registry,
            f"authority={plan.authority}; tasks={len(tasks)}",
        ),
        "EXECUTION_FEASIBILITY": _metric(
            route.runtime not in {"SEMANTIC_PROVIDER_UNAVAILABLE"}
            and valid_registry,
            f"runtime={route.runtime}; reason={route.reason}",
        ),
        "HUMAN_CLARIFICATION_ONLY_WHEN_NEEDED": _metric(
            not bool(proposal.get("needs_human_clarification")),
            "benchmark goals contain enough information to investigate safely without premature clarification",
        ),
    }


def run_benchmark(*, output: Path) -> dict[str, Any]:
    initialize_schema()
    case_reports: list[dict[str, Any]] = []
    signatures: list[tuple[Any, ...]] = []
    blocked: list[dict[str, str]] = []

    for index, case in enumerate(CASES, start=1):
        goal = build_goal_envelope(
            human_goal=case["goal"],
            project="BR-no-GTA",
            goal_id=f"intelligence-benchmark-{index:02d}",
            subject=case["subject"],
            source_surface="intelligence-benchmark",
            conversation_state=dict(case["conversation_state"]),
        )
        try:
            plan = plan_mission_from_human_goal(goal)
        except RuntimeError as exc:
            reason = str(exc)
            blocked.append({"case_id": case["case_id"], "reason": reason})
            case_reports.append({
                "case_id": case["case_id"],
                "human_goal": case["goal"],
                "status": "BLOCKED" if "PROVIDER" in reason else "FAIL",
                "error": reason,
                "metrics": {},
            })
            if "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE" in reason or "SEMANTIC_PLANNER_PROVIDER_FAILED" in reason:
                break
            continue

        metrics = _case_metrics(case, plan)
        signatures.append(_signature(plan))
        case_reports.append({
            "case_id": case["case_id"],
            "human_goal": case["goal"],
            "status": "PASS" if all(metric.passed for metric in metrics.values()) else "FAIL",
            "planning_mode": plan.planning_mode,
            "mission_id": plan.mission_id,
            "plan_id": plan.plan_id,
            "task_ids": [task.task_id for task in plan.collaboration_plan.tasks],
            "capability_ids": [task.capability_id for task in plan.collaboration_plan.tasks],
            "execution_route": select_mission_execution_route(plan.to_dict()).to_dict(),
            "metrics": {key: value.to_dict() for key, value in metrics.items()},
            "planning_evidence": dict(plan.planning_evidence),
            "semantic_plan_proposal": dict(plan.semantic_plan_proposal or {}),
        })

    unique_signatures = len({json.dumps(sig, ensure_ascii=False, sort_keys=True, default=str) for sig in signatures})
    completed = len(signatures)
    diversity_pass = completed >= 4 and unique_signatures >= min(4, completed)

    deterministic_control = {
        "message": "Onde estamos?",
        "intent": classify_conversation_intent("Onde estamos?"),
    }
    deterministic_control["passed"] = deterministic_control["intent"] == "STATUS_REQUEST"

    all_case_metrics_pass = bool(case_reports) and all(
        report.get("status") == "PASS"
        for report in case_reports
    )
    provider_blocked = bool(blocked) and any("PROVIDER" in item["reason"] for item in blocked)
    overall_pass = (
        len(case_reports) == len(CASES)
        and all_case_metrics_pass
        and diversity_pass
        and deterministic_control["passed"]
        and not provider_blocked
    )

    proof = next(
        (
            {
                "case_id": report["case_id"],
                "human_goal": report["human_goal"],
                "mission_id": report["mission_id"],
                "plan_id": report["plan_id"],
                "task_ids": report["task_ids"],
                "capability_ids": report["capability_ids"],
                "execution_route": report["execution_route"],
            }
            for report in case_reports
            if report.get("status") == "PASS"
        ),
        None,
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authority": "DEEPSEEK_HARNESS",
        "planner_authority": "NONE",
        "benchmark_kind": "LIVE_PROVIDER_STRUCTURAL_INTELLIGENCE",
        "provider_inference_injected": False,
        "case_count": len(CASES),
        "completed_case_count": completed,
        "cases": case_reports,
        "plan_diversity": {
            "passed": diversity_pass,
            "unique_signatures": unique_signatures,
            "completed_plans": completed,
            "threshold": min(4, completed) if completed else 4,
        },
        "deterministic_control_proof": deterministic_control,
        "blocked": blocked,
        "real_natural_goal_proof": proof,
        "INTELLIGENCE_BENCHMARK": "PASS" if overall_pass else (
            "BLOCKED_PROVIDER" if provider_blocked else "FAIL"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + chr(10),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/harness-intelligence/intelligence-benchmark.json",
    )
    args = parser.parse_args()
    report = run_benchmark(output=Path(args.output))
    print("INTELLIGENCE_BENCHMARK=" + report["INTELLIGENCE_BENCHMARK"])
    print(
        "PLAN_DIVERSITY="
        + ("PASS" if report["plan_diversity"]["passed"] else "FAIL")
    )
    print(
        "NO_UNNECESSARY_PROVIDER_CALL_FOR_STATUS="
        + ("PASS" if report["deterministic_control_proof"]["passed"] else "FAIL")
    )
    proof = report.get("real_natural_goal_proof")
    print(
        "REAL_NATURAL_GOAL_PROOF="
        + (
            f"{proof['mission_id']}:{proof['case_id']}"
            if isinstance(proof, dict)
            else "UNAVAILABLE"
        )
    )
    return 0 if report["INTELLIGENCE_BENCHMARK"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
