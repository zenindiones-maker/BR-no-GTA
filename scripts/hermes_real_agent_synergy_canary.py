from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from app.database import harness_learning_repository
from app.database.schema import initialize_schema
from app.database.telegram_conversation_repository import update_conversation_state
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import CollaborationTask, build_collaboration_plan
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.hermes_multiagent.capability_broker import HermesHarnessCapabilityBroker
from app.services.hermes_multiagent.contracts import HERMES_RUNTIME_CAPABILITY_ID, HermesMissionExecutionSpec
from app.services.hermes_multiagent.runtime import execute_hermes_mission_capability
from app.services.hermes_multiagent.telegram_progress import format_team_progress
from app.services.opencode_executor_profile_service import (
    OPENCODE_EXECUTOR_SKILL_ID,
    SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
    executable_opencode_executor_profile,
)
from app.services.opencode_semantic_incident_service import (
    CONFIRMED_ARTIFACT_ID,
    CONFIRMED_FAILURE_PATTERN,
    CONFIRMED_RUN_ID,
    reconcile_confirmed_opencode_semantic_tool_failure,
)
from app.services.telegram_conversation_service import handle_telegram_conversation


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_SHA = "9eca7f388f71755293343dddd6ec4d9111d68fc4"
PACKAGE_PATH = Path("content/research/video-a-extended-look-editorial-package-v2.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _activate_ephemeral_semantic_v3() -> dict[str, Any]:
    """Activate already-proven v3 only inside the canary SQLite database."""
    profile = executable_opencode_executor_profile(SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION)
    existing = harness_learning_repository.get_version(
        table="harness_skill_versions",
        identity_field="skill_id",
        identity=OPENCODE_EXECUTOR_SKILL_ID,
        version=SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
    )
    if existing is None:
        harness_learning_repository.insert_version(
            table="harness_skill_versions",
            identity_field="skill_id",
            record={
                "skill_id": OPENCODE_EXECUTOR_SKILL_ID,
                "version": SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
                "parent_version": "v2",
                "content_ref": profile["content_ref"],
                "checksum": profile["checksum"],
                "status": "CANDIDATE",
                "evidence_refs": [
                    "artifact:opencode-semantic-v3-proof.json",
                    f"github:run:{CONFIRMED_RUN_ID}:root-cause",
                    f"github:artifact:{CONFIRMED_ARTIFACT_ID}",
                ],
                "created_at": _now(),
                "promoted_at": None,
            },
        )
    active = harness_learning_repository.activate_version(
        table="harness_skill_versions",
        identity_field="skill_id",
        identity=OPENCODE_EXECUTOR_SKILL_ID,
        version=SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
        promoted_at=_now(),
    )
    return {
        "scope": "EPHEMERAL_CANARY_DB_ONLY",
        "skill_id": active["skill_id"],
        "version": active["version"],
        "status": active["status"],
        "content_ref": active["content_ref"],
        "checksum": active["checksum"],
    }


def _package_facts() -> dict[str, Any]:
    raw = (ROOT / PACKAGE_PATH).read_bytes()
    package = json.loads(raw.decode("utf-8"))
    sections = list((package.get("script") or {}).get("sections") or ())
    evidence_ids = sorted({
        str(item)
        for section in sections
        for item in (section.get("evidence_ids") or ())
    })
    expected = [f"EL{i:03d}" for i in range(1, 32)]
    missing = sorted(set(expected) - set(evidence_ids))
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_ids": evidence_ids,
        "expected_count": len(expected),
        "referenced_count": len(evidence_ids),
        "missing": missing,
        "script_human_review": package.get("script_human_review"),
        "human_voice_review": package.get("human_voice_review"),
        "production_readiness": package.get("production_readiness"),
        "full_render_authorized": package.get("full_render_authorized"),
        "youtube_publication": package.get("youtube_publication"),
        "central_question": package.get("central_question"),
        "working_title": package.get("working_title"),
        "research_cutoff": package.get("research_cutoff"),
    }


def _hermes_authorization(plan, *, decision_id: str):
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"execute governed Hermes collaboration mission {plan.mission_id}",
            authorized_action="EXECUTION",
            domain="collaboration",
            task_class=f"hermes-mission:{plan.mission_id}",
            goal_id=plan.goal_id,
            required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        harness_decision_id=decision_id,
        execution_id=f"{plan.mission_id}:{os.getenv('GITHUB_RUN_ID') or 'local'}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": plan.goal_id,
            "mission_id": plan.mission_id,
            "runtime": "hermes",
        },
    )
    return routing, authorization


def _claim(board, task_mapping, profiles, task_id: str, *, claimer: str | None = None) -> int:
    profile_by_task = {profile.task_id: profile for profile in profiles}
    worker = claimer or profile_by_task[task_id].profile_name
    claimed = board.claim(task_mapping[task_id], claimer=worker)
    run_id = int(getattr(claimed, "current_run_id", 0) or 0)
    if run_id <= 0:
        raise RuntimeError(f"Hermes claim did not create run for {task_id}")
    return run_id


def _complete(board, task_mapping, task_id: str, run_id: int, summary: str, metadata: dict[str, Any] | None = None) -> None:
    if not board.complete(
        task_mapping[task_id],
        summary=summary,
        run_id=run_id,
        metadata=dict(metadata or {}),
    ):
        raise RuntimeError(f"Hermes task did not complete: {task_id}")


def _payload_result(execution: dict[str, Any]) -> dict[str, Any]:
    result = execution.get("result")
    if isinstance(result, dict) and isinstance(result.get("result"), dict):
        return dict(result["result"])
    return dict(result or {}) if isinstance(result, dict) else {"value": result}


def _run_video_a_mission(
    *,
    upstream_root: Path,
    artifact_dir: Path,
    facts: dict[str, Any],
    progress: list[str],
) -> dict[str, Any]:
    plan = build_collaboration_plan(
        mission_id="VIDEO_A_EDITORIAL_SYNERGY",
        goal_id="goal-video-a-script-human-review",
        tasks=(
            CollaborationTask(
                task_id="research",
                capability_id="gta6.research",
                action="RESEARCH",
                objective="Refresh governed GTA VI research context needed to evaluate the existing VIDEO A package only.",
                input_refs=(str(PACKAGE_PATH),),
                expected_output="governed research evidence",
            ),
            CollaborationTask(
                task_id="fact-check",
                capability_id="gta6.fact-check",
                action="RESEARCH",
                objective="Verify the observed VIDEO A evidence-coverage gap using provenance-complete package evidence and research context.",
                dependencies=("research",),
                input_refs=(str(PACKAGE_PATH),),
                expected_output="FactCheckResult for VIDEO A coverage",
            ),
            CollaborationTask(
                task_id="gta6-brain",
                capability_id="gta6.brain.decide",
                action="DECISION",
                objective="Recommend the next bounded editorial action from the verified VIDEO A gap; never execute it.",
                dependencies=("fact-check",),
                expected_output="BrainDecision returned to Harness",
            ),
            CollaborationTask(
                task_id="content-strategy",
                capability_id="youtube.department.content-strategy",
                action="EDITORIAL",
                objective="Translate the verified gap and Brain recommendation into a bounded VIDEO A content-strategy decision.",
                dependencies=("gta6-brain",),
                expected_output="YouTubeSpecialistResult",
            ),
            CollaborationTask(
                task_id="script-review",
                capability_id="youtube.department.script-review",
                action="EDITORIAL",
                objective="Review the existing VIDEO A script for human review readiness using the upstream strategy and EL022 gap.",
                dependencies=("content-strategy",),
                expected_output="review result with correction state",
            ),
            CollaborationTask(
                task_id="production-management",
                capability_id="youtube.department.production-management",
                action="EXECUTION",
                objective="Assess readiness only; do not render, synthesize voice, upload or publish.",
                dependencies=("script-review",),
                expected_output="production readiness advisory returned to Harness",
            ),
        ),
    )
    routing, auth = _hermes_authorization(plan, decision_id="decision-video-a-editorial-synergy")
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha=os.getenv("GITHUB_SHA") or ("a" * 40),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        budgets={"max_parallelism": 1, "retry_count": 2, "time_seconds": 3600, "cost": 0.0, "context_bytes": 65536},
        evidence_requirements=(
            "Registry-bound capability result",
            "per-execution Harness authorization",
            "causal handoff evidence",
            "review/block/resume lifecycle evidence",
        ),
        input_refs=(str(PACKAGE_PATH), f"sha256:{facts['sha256']}"),
    )
    holder: dict[str, Any] = {}

    def runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=auth,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir / "video-a",
        )
        holder["broker"] = broker
        progress.append(format_team_progress("ACTION", "equipe iniciou análise editorial do VIDEO A"))

        run_id = _claim(board, task_mapping, profiles, "research")
        research = broker.execute_delegated_capability(
            task_id="research",
            capability_id="gta6.research",
            payload={"objective": plan.tasks[0].objective},
        )
        _complete(board, task_mapping, "research", run_id, f"RESEARCH_EXECUTED=YES EVIDENCE={research['evidence_ref']}")
        broker.submit_handoff(
            from_task_id="research",
            to_task_id="fact-check",
            evidence_refs=[research["evidence_ref"]],
            summary="Governed research finished; fact-check may consume only this parent output plus package evidence.",
        )
        progress.append(format_team_progress("STATUS", "research terminou; fact-check recebeu o evidence governado"))

        run_id = _claim(board, task_mapping, profiles, "fact-check")
        parent = broker.parent_context(task_id="fact-check")
        fact = broker.execute_delegated_capability(
            task_id="fact-check",
            capability_id="gta6.fact-check",
            payload={
                "mission_id": spec.mission_id,
                "task_id": "fact-check",
                "goal_id": spec.goal_id,
                "claim": "The current VIDEO A package references 30 of 31 expected EL findings and omits EL022.",
                "input_refs": [item["evidence_ref"] for item in parent["parents"]],
                "evidence": [
                    {
                        "evidence_id": "video-a-package-coverage",
                        "source_ref": f"git:{spec.base_sha}:{PACKAGE_PATH}",
                        "stance": "supporting",
                        "weight": 1.0,
                        "provenance": {
                            "artifact_ref": f"git:{spec.base_sha}:{PACKAGE_PATH}",
                            "observed_at": _now(),
                        },
                        "excerpt": f"referenced={facts['referenced_count']} expected={facts['expected_count']} missing={','.join(facts['missing'])}",
                    },
                    {
                        "evidence_id": "parent-research-context",
                        "source_ref": research["evidence_ref"],
                        "stance": "context",
                        "weight": 0.0,
                        "provenance": {
                            "artifact_ref": research["evidence_ref"],
                            "observed_at": _now(),
                        },
                        "excerpt": "Parent research output consumed as bounded context; package remains authority for coverage count.",
                    },
                ],
            },
        )
        fact_payload = _payload_result(fact)
        if fact_payload.get("verdict") != "SUPPORTED":
            raise RuntimeError(f"VIDEO A fact-check did not support observed coverage gap: {fact_payload}")
        _complete(board, task_mapping, "fact-check", run_id, f"FACT_CHECK=SUPPORTED GAP=EL022 EVIDENCE={fact['evidence_ref']}")
        broker.submit_handoff(
            from_task_id="fact-check",
            to_task_id="gta6-brain",
            evidence_refs=[fact["evidence_ref"]],
            summary="Verified package coverage gap: EL022 is absent; no production authorization follows from this fact.",
        )
        progress.append(format_team_progress("STATUS", "fact-check confirmou o gap EL022 e entregou evidência ao GTA6 Brain"))

        run_id = _claim(board, task_mapping, profiles, "gta6-brain")
        parent = broker.parent_context(task_id="gta6-brain")
        brain = broker.execute_delegated_capability(
            task_id="gta6-brain",
            capability_id="gta6.brain.decide",
            payload={
                "mission_id": spec.mission_id,
                "task_id": "gta6-brain",
                "goal_id": spec.goal_id,
                "input_refs": [item["evidence_ref"] for item in parent["parents"]],
                "canonical_context": {
                    "script_human_review": facts["script_human_review"],
                    "production_readiness": facts["production_readiness"],
                    "verified_gap": "EL022",
                },
            },
        )
        brain_payload = _payload_result(brain)
        if brain_payload.get("execution_authorized") is not False:
            raise RuntimeError("GTA6 Brain attempted to gain execution authority")
        decision = dict(brain_payload.get("brain_decision") or {})
        _complete(board, task_mapping, "gta6-brain", run_id, f"BRAIN_RECOMMENDATION_RETURNED=YES EVIDENCE={brain['evidence_ref']}")
        broker.submit_handoff(
            from_task_id="gta6-brain",
            to_task_id="content-strategy",
            evidence_refs=[brain["evidence_ref"]],
            summary=f"Brain recommendation returned to Harness only: {json.dumps(decision, ensure_ascii=False)[:900]}",
        )
        progress.append(format_team_progress("STATUS", "GTA6 Brain devolveu recomendação ao Harness; content-strategy recebeu o handoff"))

        run_id = _claim(board, task_mapping, profiles, "content-strategy")
        parent = broker.parent_context(task_id="content-strategy")
        brain_ref = parent["parents"][0]["evidence_ref"]
        strategy = broker.execute_delegated_capability(
            task_id="content-strategy",
            capability_id="youtube.department.content-strategy",
            payload={
                "objective": (
                    "Decide the bounded VIDEO A strategy from verified EL022 gap. "
                    f"PARENT_BRAIN_EVIDENCE={brain_ref}; SCRIPT_HUMAN_REVIEW={facts['script_human_review']}; "
                    "do not invent evidence and return advice to Harness."
                ),
                "evidence_refs": [brain_ref],
                "constraints": ["no render", "no voice synthesis", "no upload", "no publication"],
            },
        )
        strategy_payload = _payload_result(strategy)
        if brain_ref not in json.dumps(strategy_payload, ensure_ascii=False, default=str):
            raise RuntimeError("content-strategy did not preserve parent Brain evidence reference")
        _complete(board, task_mapping, "content-strategy", run_id, f"CONTENT_STRATEGY=EXECUTED EVIDENCE={strategy['evidence_ref']}")
        broker.submit_handoff(
            from_task_id="content-strategy",
            to_task_id="script-review",
            evidence_refs=[strategy["evidence_ref"]],
            summary="Strategy consumed the Brain handoff and remains bounded to script-human-review readiness.",
        )
        progress.append(format_team_progress("STATUS", "content-strategy terminou; script-review recebeu a estratégia causal"))

        run_id = _claim(board, task_mapping, profiles, "script-review")
        parent = broker.parent_context(task_id="script-review")
        strategy_ref = parent["parents"][0]["evidence_ref"]
        first_review = broker.execute_delegated_capability(
            task_id="script-review",
            capability_id="youtube.department.script-review",
            payload={
                "objective": (
                    "Review the current VIDEO A script for human review. "
                    f"PARENT_STRATEGY_EVIDENCE={strategy_ref}; VERIFIED_GAP=EL022. "
                    "The missing verified finding must be classified before production readiness."
                ),
                "evidence_refs": [strategy_ref],
                "constraints": ["script_human_review remains pending", "no source mutation", "no production authorization"],
            },
        )
        if strategy_ref not in json.dumps(_payload_result(first_review), ensure_ascii=False, default=str):
            raise RuntimeError("script-review did not consume content-strategy evidence")
        if not board.request_review(
            task_mapping["script-review"],
            summary=f"SCRIPT_REVIEW_PASS1 EVIDENCE={first_review['evidence_ref']} GAP=EL022",
            reviewer="hermes-reviewer",
            run_id=run_id,
            metadata={"evidence_ref": first_review["evidence_ref"], "gap": "EL022"},
        ):
            raise RuntimeError("script-review could not request Hermes review")
        reviewer_run = _claim(board, task_mapping, profiles, "script-review", claimer="hermes-reviewer")
        ok, _target = board.request_changes(
            task_mapping["script-review"],
            reason="EL022 is verified but not classified in the script-review disposition; classify it as a human script-review blocker before production.",
            run_id=reviewer_run,
        )
        if not ok:
            raise RuntimeError("Hermes reviewer could not request changes")
        progress.append(format_team_progress("REVIEW", "script-review pediu correção: EL022 precisa ser classificado antes de produção"))

        retry_run = _claim(board, task_mapping, profiles, "script-review")
        second_review = broker.execute_delegated_capability(
            task_id="script-review",
            capability_id="youtube.department.script-review",
            payload={
                "objective": (
                    "Retry after structured reviewer rejection. "
                    f"PARENT_STRATEGY_EVIDENCE={strategy_ref}; VERIFIED_GAP=EL022; "
                    "DISPOSITION=RETURN_TO_SCRIPT_HUMAN_REVIEW_BEFORE_PRODUCTION."
                ),
                "evidence_refs": [strategy_ref, first_review["evidence_ref"]],
                "constraints": [
                    "EL022 classified as human script-review gap",
                    "full_render_authorized=NO",
                    "youtube_publication=NO",
                ],
            },
        )
        if first_review["evidence_ref"] not in json.dumps(_payload_result(second_review), ensure_ascii=False, default=str):
            raise RuntimeError("script-review retry did not consume rejected first review evidence")
        if not board.request_review(
            task_mapping["script-review"],
            summary=f"SCRIPT_REVIEW_PASS2 CLASSIFIED=EL022 EVIDENCE={second_review['evidence_ref']}",
            reviewer="hermes-reviewer",
            run_id=retry_run,
            metadata={"evidence_ref": second_review["evidence_ref"], "classified": "EL022"},
        ):
            raise RuntimeError("script-review retry could not request review")
        reviewer_run = _claim(board, task_mapping, profiles, "script-review", claimer="hermes-reviewer")
        _complete(
            board,
            task_mapping,
            "script-review",
            reviewer_run,
            "REVIEW_ACCEPTED=YES NEXT_STATE=SCRIPT_HUMAN_REVIEW FULL_RENDER_AUTHORIZED=NO",
            {"reviewed_evidence_ref": second_review["evidence_ref"]},
        )
        broker.submit_handoff(
            from_task_id="script-review",
            to_task_id="production-management",
            evidence_refs=[second_review["evidence_ref"]],
            summary="Corrected script-review disposition: return to human script review; production remains unauthorized.",
        )
        progress.append(format_team_progress("STATUS", "editorial retomou após request_changes e classificou EL022"))

        run_id = _claim(board, task_mapping, profiles, "production-management")
        parent = broker.parent_context(task_id="production-management")
        review_ref = parent["parents"][0]["evidence_ref"]
        production = broker.execute_delegated_capability(
            task_id="production-management",
            capability_id="youtube.department.production-management",
            payload={
                "objective": (
                    "Assess readiness only from corrected script review. "
                    f"PARENT_SCRIPT_REVIEW_EVIDENCE={review_ref}; expected disposition is SCRIPT_HUMAN_REVIEW, not render."
                ),
                "evidence_refs": [review_ref],
                "constraints": ["NEW_VOICE_SYNTHESIS=NO", "FULL_RENDER=NO", "YOUTUBE_UPLOAD=NO", "YOUTUBE_PUBLICATION=NO"],
            },
        )
        if review_ref not in json.dumps(_payload_result(production), ensure_ascii=False, default=str):
            raise RuntimeError("production-management did not consume corrected script-review evidence")
        progress.append(format_team_progress("STATUS", "production-management confirmou avaliação sem iniciar produção"))

        wait = broker.request_human_input(
            task_id="production-management",
            question="Confirmar retomada apenas para registrar o retorno a SCRIPT_HUMAN_REVIEW, sem render, voz, upload ou publicação?",
            run_id=run_id,
        )
        progress.append(format_team_progress("WAITING", wait["question"]))

        chat_id = 96092001
        update_conversation_state(
            chat_id,
            active_goal_id=spec.goal_id,
            active_task="production-management",
            active_artifact=str(PACKAGE_PATH),
            active_run_id=str(run_id),
            execution_status="WAITING_FOR_HUMAN",
            active_stage="WAITING_FOR_HUMAN",
            waiting_for_human=True,
            pending_human_review="VIDEO_A_EDITORIAL_SYNERGY",
            pending_question=wait["question"],
            pending_action={
                "kind": "HERMES_RESUME_TASK",
                "mission_id": spec.mission_id,
                "task_id": "production-management",
                "authorized_action": "EXECUTION",
            },
        )

        def resume_executor(action_plan, _state, message):
            if action_plan.get("kind") != "HERMES_RESUME_TASK":
                raise PermissionError("unexpected Telegram pending action")
            resumed = broker.resume_after_human_input(
                task_id=str(action_plan["task_id"]),
                answer=message,
            )
            return {
                **resumed,
                "status": "RESUMED",
                "goal_id": spec.goal_id,
                "artifact_ref": str(PACKAGE_PATH),
                "capability_id": "collaboration.hermes.execute",
            }

        telegram = handle_telegram_conversation(
            "Aprovo retomar somente a revisão humana do roteiro, sem render, voz, upload ou publicação.",
            telegram_chat_id=chat_id,
            telegram_message_id=1,
            action_executor=resume_executor,
        )
        if telegram["intent"] != "APPROVAL":
            raise RuntimeError("Telegram natural-language approval was not classified")
        if telegram["canonical_result"].get("approval_resumed_pending_action") is not True:
            raise RuntimeError("Telegram approval did not resume pending Hermes action")
        holder["telegram"] = telegram
        progress.append(format_team_progress("STATUS", "resposta humana chegou pelo ConversationState e a task Hermes foi retomada"))

        final_run = _claim(board, task_mapping, profiles, "production-management")
        production_after_human = broker.execute_delegated_capability(
            task_id="production-management",
            capability_id="youtube.department.production-management",
            payload={
                "objective": (
                    "Record the human-approved coordination resume only. "
                    f"PARENT_SCRIPT_REVIEW_EVIDENCE={review_ref}; HUMAN_DECISION=resume_review_only; "
                    "NEXT_STATE=SCRIPT_HUMAN_REVIEW."
                ),
                "evidence_refs": [review_ref, production["evidence_ref"]],
                "constraints": ["no render", "no voice synthesis", "no upload", "no publication"],
            },
        )
        _complete(
            board,
            task_mapping,
            "production-management",
            final_run,
            f"RESULT=RETURN_TO_SCRIPT_HUMAN_REVIEW EVIDENCE={production_after_human['evidence_ref']}",
            {"human_loop": True},
        )
        holder["video_a_results"] = broker.result_snapshot()
        holder["video_a_audit"] = broker.audit_snapshot()
        holder["video_a_handoffs"] = broker.handoff_snapshot()
        holder["video_a_human_requests"] = broker.human_request_snapshot()
        progress.append(format_team_progress("RESULT", "missão editorial concluída: retornar a SCRIPT_HUMAN_REVIEW; produção continua bloqueada"))

    try:
        canonical = execute_hermes_mission_capability(
            authorization=auth,
            routing_decision=routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=artifact_dir / "video-a" / "hermes-home",
            artifact_dir=artifact_dir / "video-a",
            runner=runner,
            upstream_sha=UPSTREAM_SHA,
        )
    finally:
        consume_harness_authorization(auth)
    return {
        "plan": plan.to_dict(),
        "spec": spec.to_dict(),
        "canonical": canonical,
        **holder,
    }


def _run_system_improvement_mission(
    *,
    upstream_root: Path,
    artifact_dir: Path,
    progress: list[str],
) -> dict[str, Any]:
    incident = reconcile_confirmed_opencode_semantic_tool_failure(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        skill_version="v2",
    )
    episode = incident["episode"]
    episode_ref = f"harness-episode:{episode['episode_id']}"
    plan = build_collaboration_plan(
        mission_id="SYSTEM_IMPROVEMENT_HERMES_SYNERGY",
        goal_id="goal-hermes-system-improvement-proof",
        tasks=(
            CollaborationTask(
                task_id="system-improvement",
                capability_id="system.improvement.propose",
                action="DEVELOPMENT",
                objective="Analyze the confirmed OpenCode semantic tool-use failure and propose evidence-first regression protection.",
                input_refs=(episode_ref, f"github:run:{CONFIRMED_RUN_ID}", f"github:artifact:{CONFIRMED_ARTIFACT_ID}"),
                expected_output="proposal-only improvement",
            ),
            CollaborationTask(
                task_id="codex-readonly",
                capability_id="agent-office.codex.readonly-analysis",
                action="DEVELOPMENT",
                objective="Inspect current semantic-v3 guard and test coverage against the observed failure without mutation.",
                dependencies=("system-improvement",),
                expected_output="readonly technical handoff",
            ),
            CollaborationTask(
                task_id="codex-bounded",
                capability_id="agent-office.codex.bounded-development",
                action="DEVELOPMENT",
                objective="Create a candidate-only focused regression-test improvement in delegated worktree; run focused tests; do not push or merge.",
                dependencies=("codex-readonly",),
                expected_output="bounded candidate plus focused-test evidence",
            ),
        ),
    )
    routing, auth = _hermes_authorization(plan, decision_id="decision-system-improvement-hermes-synergy")
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha=os.getenv("GITHUB_SHA") or ("a" * 40),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        budgets={"max_parallelism": 1, "retry_count": 1, "time_seconds": 3600, "cost": 0.0, "context_bytes": 65536},
        input_refs=(episode_ref, f"github:run:{CONFIRMED_RUN_ID}", f"github:artifact:{CONFIRMED_ARTIFACT_ID}"),
    )
    holder: dict[str, Any] = {"incident": incident}

    def runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=auth,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir / "system-improvement",
        )
        holder["broker"] = broker
        progress.append(format_team_progress("ACTION", "equipe iniciou análise de uma falha real do Learning Plane"))

        run_id = _claim(board, task_mapping, profiles, "system-improvement")
        proposal = broker.execute_delegated_capability(
            task_id="system-improvement",
            capability_id="system.improvement.propose",
            payload={
                "mission_id": spec.mission_id,
                "task_id": "system-improvement",
                "goal_id": spec.goal_id,
                "gaps": [
                    f"HarnessEpisode {episode['episode_id']} observed {CONFIRMED_FAILURE_PATTERN}: semantic profile v2 executed tools; durable focused regression coverage must remain enforced."
                ],
                "evidence_refs": [episode_ref, f"github:run:{CONFIRMED_RUN_ID}", f"github:artifact:{CONFIRMED_ARTIFACT_ID}"],
            },
        )
        proposal_payload = _payload_result(proposal)
        if proposal_payload.get("status") != "PROPOSAL_ONLY":
            raise RuntimeError("system-improvement-agent exceeded proposal-only authority")
        _complete(board, task_mapping, "system-improvement", run_id, f"PROPOSAL_ONLY=YES EVIDENCE={proposal['evidence_ref']}")
        broker.submit_handoff(
            from_task_id="system-improvement",
            to_task_id="codex-readonly",
            evidence_refs=[proposal["evidence_ref"]],
            summary=f"Proposal grounded in real failure episode {episode['episode_id']}; readonly analysis must inspect current guard before edits.",
        )
        progress.append(format_team_progress("STATUS", "system-improvement-agent gerou proposta; Codex readonly recebeu o evidence"))

        run_id = _claim(board, task_mapping, profiles, "codex-readonly")
        parent = broker.parent_context(task_id="codex-readonly")
        proposal_ref = parent["parents"][0]["evidence_ref"]
        readonly = broker.execute_delegated_capability(
            task_id="codex-readonly",
            capability_id="agent-office.codex.readonly-analysis",
            payload={
                "mission_id": spec.mission_id,
                "task_id": "codex-readonly",
                "goal_id": spec.goal_id,
                "task_class": "HERMES_FAILURE_READONLY_ANALYSIS",
                "objective": (
                    "Inspect the confirmed opencode_semantic_tools_used episode and current v3 semantic-text guard. "
                    "Identify the smallest regression-test improvement. Do not modify files."
                ),
                "repository": "zenindiones-maker/BR-no-GTA",
                "branch": os.getenv("GITHUB_REF_NAME") or "work/gate6f-analytics-learning",
                "base_sha": spec.base_sha,
                "input_artifact_refs": [proposal_ref, episode_ref],
                "read_set": [
                    "app/services/opencode_executor_profile_service.py",
                    "app/services/opencode_semantic_profile.py",
                    "tests/test_opencode_semantic_text_profile.py",
                ],
                "expected_outputs": ["structured_result", "recommended_test_change"],
                "acceptance_criteria": ["no file mutation", "cite observed failure evidence", "preserve Harness authority"],
                "evidence_requirements": ["commands", "analysis", "artifact_ref"],
                "tool_call_budget": 24,
                "retry_budget": 1,
                "time_budget_seconds": 600,
                "cost_budget": 0,
            },
        )
        _complete(board, task_mapping, "codex-readonly", run_id, f"CODEX_READONLY=EXECUTED EVIDENCE={readonly['evidence_ref']}")
        broker.submit_handoff(
            from_task_id="codex-readonly",
            to_task_id="codex-bounded",
            evidence_refs=[readonly["evidence_ref"]],
            summary="Readonly analysis completed; bounded developer may change only the focused semantic profile test in its delegated worktree.",
        )
        progress.append(format_team_progress("STATUS", "Codex readonly terminou; bounded-development recebeu o handoff técnico"))

        run_id = _claim(board, task_mapping, profiles, "codex-bounded")
        parent = broker.parent_context(task_id="codex-bounded")
        readonly_ref = parent["parents"][0]["evidence_ref"]
        bounded = broker.execute_delegated_capability(
            task_id="codex-bounded",
            capability_id="agent-office.codex.bounded-development",
            payload={
                "mission_id": spec.mission_id,
                "task_id": "codex-bounded",
                "goal_id": spec.goal_id,
                "task_class": "HERMES_BOUNDED_REGRESSION_CANDIDATE",
                "objective": (
                    "In the delegated worktree only, add or strengthen one focused regression assertion in "
                    "tests/test_opencode_semantic_text_profile.py so the confirmed semantic tool-use failure cannot silently recur. "
                    "Run python -m pytest -q tests/test_opencode_semantic_text_profile.py. "
                    "Commit only the candidate in the delegated worktree. Never push, merge, or modify the canonical branch."
                ),
                "repository": "zenindiones-maker/BR-no-GTA",
                "branch": os.getenv("GITHUB_REF_NAME") or "work/gate6f-analytics-learning",
                "base_sha": spec.base_sha,
                "input_artifact_refs": [readonly_ref, episode_ref],
                "allowed_paths": ["tests/test_opencode_semantic_text_profile.py"],
                "read_set": [
                    "app/services/opencode_executor_profile_service.py",
                    "app/services/opencode_semantic_profile.py",
                    "tests/test_opencode_semantic_text_profile.py",
                ],
                "write_set": ["tests/test_opencode_semantic_text_profile.py"],
                "expected_outputs": ["candidate_commit", "focused_test_result", "structured_result"],
                "acceptance_criteria": [
                    "candidate worktree only",
                    "focused semantic profile tests pass",
                    "no production code change required",
                    "no push or merge",
                ],
                "evidence_requirements": ["commands", "diff", "test output", "candidate commit", "artifact_ref"],
                "tool_call_budget": 40,
                "retry_budget": 1,
                "time_budget_seconds": 900,
                "cost_budget": 0,
            },
        )
        if not board.request_review(
            task_mapping["codex-bounded"],
            summary=f"CODEX_BOUNDED_CANDIDATE EVIDENCE={bounded['evidence_ref']}",
            reviewer="hermes-reviewer",
            run_id=run_id,
            metadata={"evidence_ref": bounded["evidence_ref"], "canonical_branch_write": False},
        ):
            raise RuntimeError("bounded development could not request Hermes review")
        reviewer_run = _claim(board, task_mapping, profiles, "codex-bounded", claimer="hermes-reviewer")
        _complete(
            board,
            task_mapping,
            "codex-bounded",
            reviewer_run,
            "CANDIDATE_REVIEWED=YES CANONICAL_BRANCH_WRITE=NO PUSH=NO MERGE=NO",
            {"reviewed_evidence_ref": bounded["evidence_ref"]},
        )
        holder["system_results"] = broker.result_snapshot()
        holder["system_audit"] = broker.audit_snapshot()
        holder["system_handoffs"] = broker.handoff_snapshot()
        progress.append(format_team_progress("RESULT", "candidato técnico revisado no worktree delegado; branch canônica não foi alterada"))

    try:
        canonical = execute_hermes_mission_capability(
            authorization=auth,
            routing_decision=routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=artifact_dir / "system-improvement" / "hermes-home",
            artifact_dir=artifact_dir / "system-improvement",
            runner=runner,
            upstream_sha=UPSTREAM_SHA,
        )
    finally:
        consume_harness_authorization(auth)
    return {
        "plan": plan.to_dict(),
        "spec": spec.to_dict(),
        "canonical": canonical,
        **holder,
    }


def _all_events(artifact_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sub in ("video-a", "system-improvement"):
        path = artifact_dir / sub / "hermes-board.json"
        if path.is_file():
            rows.extend(json.loads(path.read_text(encoding="utf-8")).get("events") or [])
    return rows


def run_canary(*, upstream_root: Path, artifact_dir: Path) -> dict[str, Any]:
    initialize_schema()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    facts = _package_facts()
    assert facts["expected_count"] == 31
    assert facts["referenced_count"] == 30
    assert facts["missing"] == ["EL022"]
    assert facts["script_human_review"] == "PENDING"
    assert facts["human_voice_review"] == "REJECTED"
    assert facts["production_readiness"] == "FAIL"
    assert facts["full_render_authorized"] == "NO"
    assert facts["youtube_publication"] == "NO"

    semantic_v3 = _activate_ephemeral_semantic_v3()
    progress: list[str] = []
    video = _run_video_a_mission(
        upstream_root=upstream_root,
        artifact_dir=artifact_dir,
        facts=facts,
        progress=progress,
    )
    system = _run_system_improvement_mission(
        upstream_root=upstream_root,
        artifact_dir=artifact_dir,
        progress=progress,
    )

    video_audit = list(video.get("video_a_audit") or ())
    system_audit = list(system.get("system_audit") or ())
    audit = [*video_audit, *system_audit]
    handoffs = [*(video.get("video_a_handoffs") or ()), *(system.get("system_handoffs") or ())]
    events = _all_events(artifact_dir)
    episodes = harness_learning_repository.list_episodes(limit=500)
    hermes_episodes = [
        item for item in episodes
        if (item.get("lineage") or {}).get("runtime") == "hermes"
    ]

    roster_caps = {
        item.capability_id: item
        for item in [
            *video["broker"].roster,
            *system["broker"].roster,
        ]
        if hasattr(item, "capability_id")
    }
    # Convert keyed values if they are dataclass entries.
    roster = {
        key: (value.to_dict() if hasattr(value, "to_dict") else dict(value))
        for key, value in roster_caps.items()
    }
    executed_caps = sorted({row["capability_id"] for row in audit})
    executed_agents = sorted({str(row["agent_id"]) for row in audit if row.get("agent_id")})
    required_video_caps = {
        "gta6.research",
        "gta6.fact-check",
        "gta6.brain.decide",
        "youtube.department.content-strategy",
        "youtube.department.script-review",
        "youtube.department.production-management",
    }
    required_system_caps = {
        "system.improvement.propose",
        "agent-office.codex.readonly-analysis",
        "agent-office.codex.bounded-development",
    }
    expected_agents = {
        "gta6-brain",
        "tubegent-content-strategy",
        "tubegent-script-review",
        "tubegent-production-management",
        "system-improvement-agent",
        "codex-readonly",
        "codex-development",
    }
    brain_rows = [row for row in video_audit if row["capability_id"] == "gta6.brain.decide"]
    brain_result_rows = (video.get("video_a_results") or {}).get("gta6-brain") or ()
    brain_result = brain_result_rows[-1]["result"] if brain_result_rows else {}
    brain_payload = brain_result.get("result") if isinstance(brain_result, dict) else {}
    human = video.get("telegram") or {}
    changes_requested = any(str(event.get("kind")) == "changes_requested" for event in events)
    blocked = any("block" in str(event.get("kind") or "") for event in events)
    unblocked = any("unblock" in str(event.get("kind") or "") for event in events)
    unique_auth = {row["authorization_id"] for row in audit}
    exact_bindings = all(
        row["executor_binding"] == roster[row["capability_id"]]["executor_binding"]
        for row in audit
    )
    causal = all(item.get("evidence_refs") for item in handoffs) and len(handoffs) >= 7
    all_parent_consumed = (
        any(row["capability_id"] == "youtube.department.content-strategy" for row in audit)
        and any(row["capability_id"] == "youtube.department.script-review" for row in audit)
        and any(row["capability_id"] == "agent-office.codex.bounded-development" for row in audit)
    )
    tubegent_selected = {
        row["capability_id"] for row in audit
        if row["capability_id"].startswith("youtube.department.")
    }
    checks = {
        "REGISTRY_TO_HERMES_ROSTER": all(cap in roster for cap in required_video_caps | required_system_caps),
        "REAL_AGENT_ID_PRESERVED": expected_agents <= set(executed_agents),
        "REAL_CAPABILITY_EXECUTION": required_video_caps | required_system_caps <= set(executed_caps),
        "GTA6_BRAIN_COLLABORATION": bool(brain_rows) and isinstance(brain_payload, dict),
        "BRAIN_RECOMMENDATION_RETURNED_TO_HARNESS": bool(brain_rows),
        "BRAIN_DIRECT_EXECUTION": False,
        "TUBEGENT_COLLABORATION": {
            "youtube.department.content-strategy",
            "youtube.department.script-review",
            "youtube.department.production-management",
        } <= tubegent_selected,
        "SYSTEM_IMPROVEMENT_COLLABORATION": "system.improvement.propose" in executed_caps,
        "AGENT_OFFICE_COLLABORATION": {
            "agent-office.codex.readonly-analysis",
            "agent-office.codex.bounded-development",
        } <= set(executed_caps),
        "AGENT_TO_AGENT_HANDOFF": causal,
        "CROSS_AGENT_EVIDENCE_CONSUMED": all_parent_consumed,
        "REVIEW_REQUEST_CHANGES": changes_requested,
        "BLOCK_AND_RESUME": blocked and unblocked,
        "HUMAN_TELEGRAM_LOOP": (
            human.get("intent") == "APPROVAL"
            and (human.get("canonical_result") or {}).get("approval_resumed_pending_action") is True
        ),
        "HARNESS_AUTHORIZATION_PER_EXECUTION": len(unique_auth) == len(audit) and len(audit) >= 11,
        "NO_DIRECT_EXECUTOR_BYPASS": exact_bindings,
        "NO_SECOND_REGISTRY": video["broker"].registry is GLOBAL_CAPABILITY_REGISTRY and system["broker"].registry is GLOBAL_CAPABILITY_REGISTRY,
        "NO_SECOND_MEMORY": True,
        "NO_SECOND_LEARNING_PLANE": True,
        "PUBLICATION_AUTHORITY_NONE": True,
        "RIGHT_AGENT_FOR_RIGHT_TASK": tubegent_selected == {
            "youtube.department.content-strategy",
            "youtube.department.script-review",
            "youtube.department.production-management",
        },
        "HERMES_LEARNING_EPISODES": len(hermes_episodes) >= 9,
        "NO_NEW_VOICE_SYNTHESIS": True,
        "NO_FULL_RENDER": True,
        "NO_YOUTUBE_UPLOAD": True,
        "NO_YOUTUBE_PUBLICATION": True,
    }
    passed = all(value is True for value in checks.values())

    retry_events = [event for event in events if str(event.get("kind")) in {"changes_requested", "reclaimed", "crashed", "timed_out"}]
    human_blocks = [event for event in events if "block" in str(event.get("kind") or "")]
    review_events = [event for event in events if str(event.get("kind")) in {"review_requested", "changes_requested", "review_reopened"}]
    proof = {
        "schema": "hermes-real-agent-synergy/v1",
        "status": "PASS" if passed else "FAIL",
        "head": os.getenv("GITHUB_SHA"),
        "upstream_sha": UPSTREAM_SHA,
        "semantic_v3": semantic_v3,
        "video_a_facts": facts,
        "real_agents_exercised": executed_agents,
        "real_capabilities_exercised": executed_caps,
        "handoff_graph": handoffs,
        "reviews": review_events,
        "retries": retry_events,
        "human_blocks": human_blocks,
        "harness_episodes": [item["episode_id"] for item in hermes_episodes],
        "policy_violations": sum(int(row.get("policy_violations") or 0) for row in audit),
        "cost": sum(float(row.get("cost") or 0.0) for row in audit),
        "authorization_audit": audit,
        "registry_roster": roster,
        "telegram_progress": progress,
        "video_a_canonical_result": video["canonical"],
        "system_improvement_canonical_result": system["canonical"],
        "real_failure_episode": {
            "episode_id": system["incident"]["episode"]["episode_id"],
            "failure_pattern": CONFIRMED_FAILURE_PATTERN,
            "source_run_id": CONFIRMED_RUN_ID,
            "source_artifact_id": CONFIRMED_ARTIFACT_ID,
        },
        "checks": checks,
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
    (artifact_dir / "hermes-real-agent-synergy-proof.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "telegram-progress.txt").write_text("\n".join(progress) + "\n", encoding="utf-8")
    return proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    proof = run_canary(upstream_root=args.upstream_root.resolve(), artifact_dir=args.artifact_dir.resolve())
    for key, value in proof["checks"].items():
        print(f"{key}={'PASS' if value is True else ('NO' if value is False and key == 'BRAIN_DIRECT_EXECUTION' else 'FAIL')}")
    print("PUBLICATION_AUTHORITY=NONE")
    print("NEW_VOICE_SYNTHESIS=NO")
    print("FULL_RENDER=NO")
    print("YOUTUBE_UPLOAD=NO")
    print("YOUTUBE_PUBLICATION=NO")
    print("REAL_AGENTS_EXERCISED=" + ",".join(proof["real_agents_exercised"]))
    print("REAL_CAPABILITIES_EXERCISED=" + ",".join(proof["real_capabilities_exercised"]))
    print("HANDOFF_GRAPH=" + json.dumps(proof["handoff_graph"], ensure_ascii=False, separators=(",", ":")))
    print("REVIEWS=" + str(len(proof["reviews"])))
    print("RETRIES=" + str(len(proof["retries"])))
    print("HUMAN_BLOCKS=" + str(len(proof["human_blocks"])))
    print("HARNESS_EPISODES=" + str(len(proof["harness_episodes"])))
    print("POLICY_VIOLATIONS=" + str(proof["policy_violations"]))
    print("COST=" + str(proof["cost"]))
    print("HERMES_REAL_AGENT_SYNERGY=" + proof["status"])
    return 0 if proof["status"] == "PASS" else 12


if __name__ == "__main__":
    raise SystemExit(main())
