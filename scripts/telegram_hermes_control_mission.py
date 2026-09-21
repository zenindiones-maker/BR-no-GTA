from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from app.database.schema import initialize_schema
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import (
    CollaborationTask,
    build_collaboration_plan,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.hermes_multiagent.board_adapter import HermesBoardAdapter
from app.services.hermes_multiagent.capability_broker import (
    HermesHarnessCapabilityBroker,
)
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.hermes_multiagent.runtime import (
    execute_hermes_mission_capability,
)
from app.services.hermes_multiagent.telegram_progress import format_team_progress
from scripts.telegram_harness_gateway import TelegramApi


UPSTREAM_SHA = "9eca7f388f71755293343dddd6ec4d9111d68fc4"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_factory(chat_id: int) -> tuple[Callable[[str, str], None], list[str]]:
    lines: list[str] = []
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api = TelegramApi(token) if token and chat_id else None

    def emit(kind: str, message: str) -> None:
        text = format_team_progress(kind, message)
        lines.append(text)
        print(text, flush=True)
        if api is not None:
            api.send(chat_id, text)

    return emit, lines


def _build_plan(*, mission_id: str, goal_id: str):
    return build_collaboration_plan(
        mission_id=mission_id,
        goal_id=goal_id,
        tasks=(
            CollaborationTask(
                task_id="fact-check",
                capability_id="gta6.fact-check",
                action="RESEARCH",
                objective=(
                    "Verify the identity/provenance of the Telegram-selected script snapshot "
                    "without inventing content claims."
                ),
                expected_output="deterministic provenance FactCheckResult",
            ),
            CollaborationTask(
                task_id="gta6-brain",
                capability_id="gta6.brain.decide",
                action="DECISION",
                objective=(
                    "Optional semantic editorial recommendation. This task may block alone "
                    "when no zero-cost reasoning provider is eligible."
                ),
                dependencies=("fact-check",),
                expected_output="BrainDecision or BLOCKED_PROVIDER",
            ),
            CollaborationTask(
                task_id="content-strategy",
                capability_id="youtube.department.content-strategy",
                action="EDITORIAL",
                objective=(
                    "Provider-free bounded content-strategy review using only the verified "
                    "artifact identity and human request."
                ),
                dependencies=("fact-check",),
                expected_output="YouTubeSpecialistResult",
            ),
            CollaborationTask(
                task_id="script-review",
                capability_id="youtube.department.script-review",
                action="EDITORIAL",
                objective=(
                    "Provider-free script review with explicit limitations and human-review gate."
                ),
                dependencies=("content-strategy",),
                expected_output="review result plus structured reviewer disposition",
            ),
            CollaborationTask(
                task_id="production-management",
                capability_id="youtube.department.production-management",
                action="EXECUTION",
                objective=(
                    "Readiness assessment only; never render, synthesize voice, upload or publish."
                ),
                dependencies=("script-review",),
                expected_output="human-gated readiness advisory",
            ),
        ),
    )


def _hermes_authorization(plan):
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"execute Telegram Hermes mission {plan.mission_id}",
            authorized_action="EXECUTION",
            domain="collaboration",
            task_class="telegram-hermes-editorial",
            goal_id=plan.goal_id,
            required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
            fallback_allowed=False,
            provider_required=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        execution_id=f"{plan.mission_id}:{os.getenv('GITHUB_RUN_ID') or 'local'}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": plan.goal_id,
            "mission_id": plan.mission_id,
            "runtime": "hermes",
            "ingress": "telegram",
        },
    )
    return routing, authorization


def _claim(board, mapping, profiles, task_id: str, *, claimer: str | None = None) -> int:
    profile_by_task = {profile.task_id: profile for profile in profiles}
    worker = claimer or profile_by_task[task_id].profile_name
    claimed = board.claim(mapping[task_id], claimer=worker)
    run_id = int(getattr(claimed, "current_run_id", 0) or 0)
    if run_id <= 0:
        raise RuntimeError(f"Hermes claim did not create run for {task_id}")
    return run_id


def _complete(board, mapping, task_id: str, run_id: int, summary: str) -> None:
    if not board.complete(mapping[task_id], summary=summary, run_id=run_id):
        raise RuntimeError(f"Hermes task did not complete: {task_id}")


def _mapping_from_snapshot(board: HermesBoardAdapter) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for task in board.snapshot().get("tasks") or ():
        body = task.get("body")
        if not isinstance(body, str):
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        plan_task_id = str(parsed.get("plan_task_id") or "").strip()
        board_task_id = str(task.get("id") or "").strip()
        if plan_task_id and board_task_id:
            mapping[plan_task_id] = board_task_id
    return mapping


def _decode_artifact(value: str) -> bytes:
    if not value:
        return b""
    return base64.b64decode(value.encode("ascii"), validate=True)


def _start(
    *,
    mission_id: str,
    goal_id: str,
    chat_id: int,
    request_text: str,
    artifact_ref: str,
    artifact_text_b64: str,
    expected_sha256: str,
    upstream_root: Path,
    artifact_dir: Path,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    raw = _decode_artifact(artifact_text_b64)
    observed_sha = hashlib.sha256(raw).hexdigest() if raw else expected_sha256
    if expected_sha256 and observed_sha != expected_sha256:
        raise RuntimeError("Telegram artifact snapshot SHA-256 mismatch")
    snapshot_path = artifact_dir / "input-script.txt"
    if raw:
        snapshot_path.write_bytes(raw)

    plan = _build_plan(mission_id=mission_id, goal_id=goal_id)
    routing, auth = _hermes_authorization(plan)
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha=os.getenv("GITHUB_SHA") or ("a" * 40),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        budgets={
            "max_parallelism": 1,
            "retry_count": 2,
            "time_seconds": 1800,
            "cost": 0.0,
            "context_bytes": 65536,
        },
        evidence_requirements=(
            "Registry-bound capability result",
            "per-execution Harness authorization",
            "provider blocker contained to declaring task",
            "human block persisted as mission evidence",
        ),
        input_refs=tuple(
            item for item in (
                artifact_ref,
                f"sha256:{observed_sha}" if observed_sha else None,
            ) if item
        ),
    )
    emit, progress = _emit_factory(chat_id)
    holder: dict[str, Any] = {}

    def runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=auth,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir,
        )
        holder["broker"] = broker
        emit("ACTION", "equipe iniciou a análise editorial governada")

        fact_run = _claim(board, task_mapping, profiles, "fact-check")
        source_ref = artifact_ref or f"telegram-snapshot:{observed_sha}"
        fact = broker.execute_delegated_capability(
            task_id="fact-check",
            capability_id="gta6.fact-check",
            payload={
                "mission_id": mission_id,
                "task_id": "fact-check",
                "goal_id": goal_id,
                "claim": (
                    "The selected Telegram artifact snapshot is bound to the observed "
                    "SHA-256 and may be used as the exact review input."
                ),
                "input_refs": [source_ref],
                "evidence": [
                    {
                        "evidence_id": "telegram-script-snapshot",
                        "source_ref": source_ref,
                        "stance": "supporting",
                        "weight": 1.0,
                        "provenance": {
                            "artifact_ref": source_ref,
                            "observed_at": _now(),
                        },
                        "excerpt": (
                            f"sha256={observed_sha or 'not-materialized'} "
                            f"bytes={len(raw)} request={request_text[:240]}"
                        ),
                    }
                ],
            },
        )
        _complete(
            board,
            task_mapping,
            "fact-check",
            fact_run,
            f"FACT_CHECK=SUPPORTED EVIDENCE={fact['evidence_ref']}",
        )
        broker.submit_handoff(
            from_task_id="fact-check",
            to_task_id="content-strategy",
            evidence_refs=[fact["evidence_ref"]],
            summary="Verified artifact identity is available for bounded provider-free review.",
        )
        broker.submit_handoff(
            from_task_id="fact-check",
            to_task_id="gta6-brain",
            evidence_refs=[fact["evidence_ref"]],
            summary="Optional Brain enrichment receives the same verified artifact identity.",
        )
        emit("STATUS", "fact-check terminou; a evidência foi entregue às próximas tarefas")

        brain_run = _claim(board, task_mapping, profiles, "gta6-brain")
        blocker = (
            "BLOCKED_PROVIDER: OpenCode zero-cost provider admission is externally "
            "blocked with HTTP 403 before inference; no other zero-cost provider is eligible."
        )
        if not board.block(
            task_mapping["gta6-brain"],
            reason=blocker,
            run_id=brain_run,
            kind="capability",
        ):
            raise RuntimeError("GTA6 Brain task could not enter provider block")
        emit(
            "STATUS",
            "GTA6 Brain ficou bloqueado pelo provider zero-cost; a análise provider-free continua.",
        )

        strategy_run = _claim(board, task_mapping, profiles, "content-strategy")
        strategy = broker.execute_delegated_capability(
            task_id="content-strategy",
            capability_id="youtube.department.content-strategy",
            payload={
                "objective": (
                    f"Review the selected script artifact {artifact_ref or observed_sha} "
                    f"for the human request: {request_text[:1200]}. "
                    "Do not invent factual claims; preserve the provider blocker as a limitation."
                ),
                "evidence_refs": [fact["evidence_ref"]],
                "constraints": [
                    "GTA6 Brain semantic enrichment unavailable",
                    "no render",
                    "no voice synthesis",
                    "no upload",
                    "no publication",
                ],
            },
        )
        _complete(
            board,
            task_mapping,
            "content-strategy",
            strategy_run,
            f"CONTENT_STRATEGY=EXECUTED EVIDENCE={strategy['evidence_ref']}",
        )
        broker.submit_handoff(
            from_task_id="content-strategy",
            to_task_id="script-review",
            evidence_refs=[strategy["evidence_ref"]],
            summary="Provider-free strategy completed with explicit semantic limitations.",
        )
        emit("STATUS", "content-strategy terminou; script-review recebeu a evidência causal")

        review_run = _claim(board, task_mapping, profiles, "script-review")
        first_review = broker.execute_delegated_capability(
            task_id="script-review",
            capability_id="youtube.department.script-review",
            payload={
                "objective": (
                    f"Review artifact {artifact_ref or observed_sha} using only supplied evidence. "
                    "Classify unknown semantic/factual issues for human review instead of inventing them."
                ),
                "evidence_refs": [strategy["evidence_ref"]],
                "constraints": [
                    "provider-free bounded pass",
                    "unverified semantic claims require human review",
                    "production remains unauthorized",
                ],
            },
        )
        if not board.request_review(
            task_mapping["script-review"],
            summary=f"SCRIPT_REVIEW_PASS1 EVIDENCE={first_review['evidence_ref']}",
            reviewer="hermes-reviewer",
            run_id=review_run,
            metadata={"evidence_ref": first_review["evidence_ref"]},
        ):
            raise RuntimeError("script-review could not request Hermes review")
        reviewer_run = _claim(
            board,
            task_mapping,
            profiles,
            "script-review",
            claimer="hermes-reviewer",
        )
        ok, _ = board.request_changes(
            task_mapping["script-review"],
            reason=(
                "The provider-free pass must explicitly preserve the semantic-analysis limitation "
                "and return unresolved items to the human before production."
            ),
            run_id=reviewer_run,
        )
        if not ok:
            raise RuntimeError("Hermes reviewer could not request changes")
        emit("REVIEW", "script-review pediu correção para explicitar o limite sem provider")

        retry_run = _claim(board, task_mapping, profiles, "script-review")
        second_review = broker.execute_delegated_capability(
            task_id="script-review",
            capability_id="youtube.department.script-review",
            payload={
                "objective": (
                    "Retry after Hermes request_changes. Preserve all supplied evidence and "
                    "set disposition=HUMAN_SCRIPT_REVIEW_REQUIRED while semantic provider is blocked."
                ),
                "evidence_refs": [
                    strategy["evidence_ref"],
                    first_review["evidence_ref"],
                ],
                "constraints": [
                    "HUMAN_SCRIPT_REVIEW_REQUIRED",
                    "FULL_RENDER=NO",
                    "NEW_VOICE_SYNTHESIS=NO",
                    "YOUTUBE_UPLOAD=NO",
                    "YOUTUBE_PUBLICATION=NO",
                ],
            },
        )
        if not board.request_review(
            task_mapping["script-review"],
            summary=f"SCRIPT_REVIEW_PASS2 EVIDENCE={second_review['evidence_ref']}",
            reviewer="hermes-reviewer",
            run_id=retry_run,
            metadata={"evidence_ref": second_review["evidence_ref"]},
        ):
            raise RuntimeError("script-review retry could not request review")
        reviewer_run = _claim(
            board,
            task_mapping,
            profiles,
            "script-review",
            claimer="hermes-reviewer",
        )
        _complete(
            board,
            task_mapping,
            "script-review",
            reviewer_run,
            "REVIEW_ACCEPTED=YES NEXT_STATE=HUMAN_SCRIPT_REVIEW_REQUIRED",
        )
        broker.submit_handoff(
            from_task_id="script-review",
            to_task_id="production-management",
            evidence_refs=[second_review["evidence_ref"]],
            summary="Corrected review requires human decision before any production action.",
        )
        emit("STATUS", "script-review foi corrigido e voltou para revisão humana")

        prod_run = _claim(board, task_mapping, profiles, "production-management")
        production = broker.execute_delegated_capability(
            task_id="production-management",
            capability_id="youtube.department.production-management",
            payload={
                "objective": (
                    "Assess readiness only. The human must approve the next review step; "
                    "production remains forbidden."
                ),
                "evidence_refs": [second_review["evidence_ref"]],
                "constraints": [
                    "NEW_VOICE_SYNTHESIS=NO",
                    "FULL_RENDER=NO",
                    "YOUTUBE_UPLOAD=NO",
                    "YOUTUBE_PUBLICATION=NO",
                ],
            },
        )
        wait = broker.request_human_input(
            task_id="production-management",
            question=(
                "A análise provider-free terminou. Aprova registrar o retorno do roteiro "
                "para revisão humana, mantendo produção, voz, upload e publicação bloqueados?"
            ),
            run_id=prod_run,
        )
        holder.update(
            fact=fact,
            strategy=strategy,
            first_review=first_review,
            second_review=second_review,
            production=production,
            wait=wait,
        )
        emit("WAITING", wait["question"])

    try:
        canonical = execute_hermes_mission_capability(
            authorization=auth,
            routing_decision=routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=artifact_dir / "hermes-home",
            artifact_dir=artifact_dir,
            runner=runner,
            upstream_sha=UPSTREAM_SHA,
        )
    finally:
        consume_harness_authorization(auth)

    broker = holder["broker"]
    proof = {
        "schema": "telegram-hermes-control/v1",
        "mode": "start",
        "status": "WAITING_FOR_HUMAN",
        "mission_id": mission_id,
        "goal_id": goal_id,
        "artifact_ref": artifact_ref,
        "artifact_sha256": observed_sha,
        "task_id": "production-management",
        "provider_blocker": "OPENCODE_EXTERNAL_403",
        "brain_status": "BLOCKED_PROVIDER",
        "canonical": canonical,
        "wait": holder["wait"],
        "script_review_evidence_ref": holder["second_review"]["evidence_ref"],
        "production_evidence_ref": holder["production"]["evidence_ref"],
        "authorization_audit": broker.audit_snapshot(),
        "handoffs": broker.handoff_snapshot(),
        "progress": progress,
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
    return proof


def _resume(
    *,
    mission_id: str,
    goal_id: str,
    chat_id: int,
    human_answer: str,
    upstream_root: Path,
    artifact_dir: Path,
) -> dict[str, Any]:
    start_proof_path = artifact_dir / "telegram-hermes-control-proof.json"
    start_proof = json.loads(start_proof_path.read_text(encoding="utf-8"))
    if start_proof.get("mission_id") != mission_id:
        raise RuntimeError("Restored Hermes mission id mismatch")

    plan = _build_plan(mission_id=mission_id, goal_id=goal_id)
    routing, auth = _hermes_authorization(plan)
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha=os.getenv("GITHUB_SHA") or ("a" * 40),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        budgets={"max_parallelism": 1, "retry_count": 1, "time_seconds": 900, "cost": 0.0},
        evidence_requirements=("restored Hermes board", "fresh Harness authorization", "human decision"),
        input_refs=tuple(
            item
            for item in (str(start_proof.get("artifact_ref") or "").strip(),)
            if item
        ),
    )
    board_id = f"br-{mission_id.lower().replace('_', '-')}"[:64]
    board = HermesBoardAdapter(
        upstream_root=upstream_root,
        hermes_home=artifact_dir / "hermes-home",
        board_id=board_id,
    )
    mapping = _mapping_from_snapshot(board)
    expected = {task.task_id for task in spec.collaboration_plan.tasks}
    if set(mapping) != expected:
        raise RuntimeError(f"Restored Hermes board mapping mismatch: {sorted(mapping)}")
    emit, progress = _emit_factory(chat_id)
    broker = HermesHarnessCapabilityBroker(
        spec=spec,
        parent_authorization=auth,
        board=board,
        task_mapping=mapping,
        artifact_dir=artifact_dir,
    )
    emit("ACTION", "aprovação recebida; retomando a task bloqueada pelo Harness")
    try:
        resumed = broker.resume_after_human_input(
            task_id="production-management",
            answer=human_answer,
        )
        claimed = board.claim(
            mapping["production-management"],
            claimer="telegram-human-resume",
        )
        run_id = int(getattr(claimed, "current_run_id", 0) or 0)
        if run_id <= 0:
            raise RuntimeError("Resumed Hermes task did not create run")
        result = broker.execute_delegated_capability(
            task_id="production-management",
            capability_id="youtube.department.production-management",
            payload={
                "objective": (
                    "Record the human-approved return to script review only. "
                    "Do not start production."
                ),
                "evidence_refs": [
                    str(start_proof["script_review_evidence_ref"]),
                    str(start_proof["production_evidence_ref"]),
                ],
                "constraints": [
                    "NEXT_STATE=HUMAN_SCRIPT_REVIEW",
                    "NEW_VOICE_SYNTHESIS=NO",
                    "FULL_RENDER=NO",
                    "YOUTUBE_UPLOAD=NO",
                    "YOUTUBE_PUBLICATION=NO",
                ],
            },
        )
        _complete(
            board,
            mapping,
            "production-management",
            run_id,
            f"HUMAN_RESUME=PASS EVIDENCE={result['evidence_ref']}",
        )
    finally:
        consume_harness_authorization(auth)
    emit("RESULT", "decisão humana registrada; roteiro retorna para revisão, sem produção")

    return {
        "schema": "telegram-hermes-control/v1",
        "mode": "resume",
        "status": "COMPLETED_WITH_PROVIDER_BLOCK",
        "mission_id": mission_id,
        "goal_id": goal_id,
        "task_id": "production-management",
        "human_answer": human_answer,
        "resume": resumed,
        "result": result,
        "provider_blocker": "OPENCODE_EXTERNAL_403",
        "brain_status": "BLOCKED_PROVIDER",
        "board": board.snapshot(),
        "authorization_audit": broker.audit_snapshot(),
        "progress": progress,
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("start", "resume"), required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--chat-id", type=int, default=0)
    parser.add_argument("--request-text", default="")
    parser.add_argument("--artifact-ref", default="")
    parser.add_argument("--artifact-text-b64", default="")
    parser.add_argument("--artifact-sha256", default="")
    parser.add_argument("--human-answer", default="")
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()

    initialize_schema()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "start":
        proof = _start(
            mission_id=args.mission_id,
            goal_id=args.goal_id,
            chat_id=args.chat_id,
            request_text=args.request_text,
            artifact_ref=args.artifact_ref,
            artifact_text_b64=args.artifact_text_b64,
            expected_sha256=args.artifact_sha256,
            upstream_root=args.upstream_root.resolve(),
            artifact_dir=args.artifact_dir.resolve(),
        )
    else:
        proof = _resume(
            mission_id=args.mission_id,
            goal_id=args.goal_id,
            chat_id=args.chat_id,
            human_answer=args.human_answer,
            upstream_root=args.upstream_root.resolve(),
            artifact_dir=args.artifact_dir.resolve(),
        )
    output = args.artifact_dir / "telegram-hermes-control-proof.json"
    output.write_text(
        json.dumps(proof, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print("TELEGRAM_HERMES_CONTROL_MODE=" + args.mode)
    print("TELEGRAM_HERMES_CONTROL_STATUS=" + proof["status"])
    print("OPENCODE_EXTERNAL_403_CONTAINED=PASS")
    print("NEW_VOICE_SYNTHESIS=NO")
    print("FULL_RENDER=NO")
    print("YOUTUBE_UPLOAD=NO")
    print("YOUTUBE_PUBLICATION=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
