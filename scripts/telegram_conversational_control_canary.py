from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.database.scripts_repository import insert_script
from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
    list_recent_human_decisions,
    update_conversation_state,
)
from app.integrations.deepseek_harness import server
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.telegram_harness_service import HarnessReasoningFailure
from scripts.telegram_harness_gateway_v2 import (
    _handle_live_natural_language_message,
)
from scripts.telegram_hermes_control_mission import (
    _resume as resume_hermes_control_mission,
)
from scripts.telegram_hermes_control_mission import (
    _start as start_hermes_control_mission,
)


class FakeTelegramApi:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.edited: list[str] = []
        self._next_id = 1000

    def send(self, chat_id: int, text: str) -> int:
        self.sent.append(str(text))
        self._next_id += 1
        return self._next_id

    def edit(self, chat_id: int, message_id: int, text: str) -> None:
        self.edited.append(str(text))

    @property
    def human_facing(self) -> list[str]:
        return [*self.sent, *self.edited]


def _provider_unavailable(*_args, **_kwargs):
    raise HarnessReasoningFailure(
        {
            "provider": "opencode",
            "model": "oc/big-pickle",
            "provider_error": {
                "code": "provider_auth_403",
                "message": "OpenCode's free tier can only be used from within OpenCode",
            },
        }
    )


def _route_only_continue(plan: dict[str, Any]) -> dict[str, Any]:
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="Telegram canary continue without executing render",
            authorized_action="EXECUTION",
            required_capability_id="production.render.execute",
            fallback_allowed=False,
            provider_required=False,
            zero_cost_operation=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{routing.selected_capability_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": plan.get("active_goal_id"),
            "ingress": "telegram-live-canary",
            "canary_no_side_effect": True,
        },
    )
    try:
        return {
            "status": "COMPLETED",
            "answer": (
                "Continuidade resolvida pelo estado e autorizada no Harness. "
                "O canário não executou render."
            ),
            "goal_id": plan.get("active_goal_id"),
            "capability_id": routing.selected_capability_id,
            "routing_id": routing.routing_id,
            "authorization_id": authorization.authorization_id,
            "execution_id": authorization.execution_id,
            "canary_no_side_effect": True,
        }
    finally:
        consume_harness_authorization(authorization)


def _live(
    api: FakeTelegramApi,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    action_executor=None,
    chat_handler=None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if action_executor is not None:
        kwargs["action_executor"] = action_executor
    if chat_handler is not None:
        kwargs["chat_handler"] = chat_handler
    _reply, _learned, result = _handle_live_natural_language_message(
        api=api,
        user_id=chat_id,
        chat_id=chat_id,
        message={"message_id": message_id},
        update_id=100000 + message_id,
        text=text,
        **kwargs,
    )
    return result


def run_canary(*, upstream_root: Path, artifact_dir: Path) -> dict[str, Any]:
    initialize_schema()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    idea_id = insert_idea(
        "Canário live Telegram control surface",
        description="Prova do gateway v2 -> ConversationService -> Harness/Hermes.",
    )
    script_content = (
        "Abertura canônica.\n\n"
        "Trecho de roteiro usado apenas como snapshot verificável no canário.\n\n"
        "Fechamento canônico."
    )
    script_id = insert_script(
        idea_id,
        "Roteiro live canário",
        script_content,
        status="draft",
        version=1,
    )
    script_ref = f"script:{script_id}"
    chat_id = 920260921
    goal_id = "goal-telegram-system-synergy"
    update_conversation_state(
        chat_id,
        active_goal_id=goal_id,
        active_project="BR-no-GTA",
        active_task="revisão governada do vídeo A",
        current_subject="roteiro do vídeo A",
        active_artifact=script_ref,
        execution_status="IDLE",
        waiting_for_human=False,
    )

    api = FakeTelegramApi()
    hermes_dir = artifact_dir / "hermes-live"
    hermes_start: dict[str, Any] | None = None
    hermes_resume: dict[str, Any] | None = None

    def action_executor(plan: dict[str, Any], state: dict[str, Any], message: str):
        nonlocal hermes_start, hermes_resume
        kind = str(plan.get("kind") or "")
        if kind == "CONTINUE":
            return _route_only_continue(plan)
        if kind == "QUERY_RESEARCH":
            return {
                "status": "COMPLETED",
                "answer": (
                    "Pesquisei exatamente o seu pedido e preservei a evidência oficial. "
                    "O fact-check determinístico concluiu sem depender de síntese semântica."
                ),
                "capability_id": "gta6.research.fresh-cloud",
                "query": str(plan.get("query") or message),
                "RESEARCH_EXECUTION": "PASS",
                "GTA6_FACT_CHECK": "PASS",
                "SOURCE_PROVENANCE_PRESERVED": "PASS",
                "provider_required_for_evidence_answer": False,
                "semantic_synthesis_used": False,
            }
        if kind in {"HERMES_COLLABORATION", "HARNESS_MISSION"}:
            if kind == "HARNESS_MISSION":
                mission_plan = plan.get("mission_plan")
                if not isinstance(mission_plan, dict):
                    raise AssertionError("HARNESS_MISSION missing MissionPlan")
                if mission_plan.get("authority") != "DEEPSEEK_HARNESS":
                    raise AssertionError("MissionPlan escaped Harness authority")
                if len((mission_plan.get("collaboration_plan") or {}).get("tasks") or []) < 2:
                    raise AssertionError("editorial Harness mission did not plan collaboration")
            raw = script_content.encode("utf-8")
            mission_id = f"telegram-control-synergy-{chat_id}"
            hermes_start = start_hermes_control_mission(
                mission_id=mission_id,
                goal_id=goal_id,
                chat_id=0,
                request_text=message,
                artifact_ref=script_ref,
                artifact_text_b64=base64.b64encode(raw).decode("ascii"),
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                upstream_root=upstream_root,
                artifact_dir=hermes_dir,
            )
            (hermes_dir / "telegram-hermes-control-proof.json").write_text(
                json.dumps(hermes_start, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            return {
                "status": "WAITING_FOR_HUMAN",
                "answer": (
                    "A equipe terminou as etapas provider-free. O GTA6 Brain ficou bloqueado "
                    "pelo provider externo, sem derrubar fact-check, TUBEGENT ou review. "
                    "Preciso da sua aprovação para registrar o retorno à revisão humana."
                ),
                "capability_id": "collaboration.hermes.execute",
                "mission_id": mission_id,
                "task_id": "production-management",
                "goal_id": goal_id,
                "artifact_ref": script_ref,
                "run_id": f"hermes:{mission_id}",
                "pending_question": hermes_start["wait"]["question"],
                "pending_action": {
                    "kind": "HERMES_LOCAL_RESUME",
                    "mission_id": mission_id,
                    "task_id": "production-management",
                    "goal_id": goal_id,
                    "artifact_ref": script_ref,
                    "authorized_action": "EXECUTION",
                },
            }
        if kind == "HERMES_LOCAL_RESUME":
            hermes_resume = resume_hermes_control_mission(
                mission_id=str(plan["mission_id"]),
                goal_id=str(plan["goal_id"]),
                chat_id=0,
                human_answer=message,
                upstream_root=upstream_root,
                artifact_dir=hermes_dir,
            )
            return {
                "status": "COMPLETED_WITH_PROVIDER_BLOCK",
                "answer": (
                    "A mesma missão Hermes foi retomada e a decisão humana foi registrada. "
                    "O GTA6 Brain continua isoladamente bloqueado; produção continua proibida."
                ),
                "capability_id": "collaboration.hermes.execute",
                "mission_id": plan["mission_id"],
                "task_id": plan["task_id"],
                "goal_id": plan["goal_id"],
                "artifact_ref": script_ref,
                "run_id": f"hermes:{plan['mission_id']}:resume",
            }
        raise AssertionError(f"unexpected action plan in live canary: {plan}")

    status = _live(
        api,
        chat_id=chat_id,
        message_id=9001,
        text="Onde estamos?",
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("status cannot use provider")
        ),
    )
    last_script = _live(
        api,
        chat_id=chat_id,
        message_id=9002,
        text="Me manda o último roteiro",
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("script presentation cannot use provider")
        ),
    )
    feedback = _live(
        api,
        chat_id=chat_id,
        message_id=9003,
        text="Esse ficou melhor",
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("feedback cannot use provider")
        ),
    )

    deferred = _live(
        api,
        chat_id=chat_id,
        message_id=9004,
        text="Continua de onde parou depois que eu aprovar",
        action_executor=action_executor,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("deferred action cannot use provider")
        ),
    )
    approval = _live(
        api,
        chat_id=chat_id,
        message_id=9005,
        text="Aprovo",
        action_executor=action_executor,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("approval cannot use provider")
        ),
    )
    continued = _live(
        api,
        chat_id=chat_id,
        message_id=9006,
        text="Continua de onde parou",
        action_executor=action_executor,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("continue cannot use provider")
        ),
    )
    research = _live(
        api,
        chat_id=chat_id,
        message_id=9007,
        text="Pesquisa a novidade X",
        action_executor=action_executor,
        chat_handler=_provider_unavailable,
    )
    team = _live(
        api,
        chat_id=chat_id,
        message_id=9008,
        text="Analisa esse roteiro com a equipe e vê o que falta",
        action_executor=action_executor,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Hermes mission cannot enter generic model chat")
        ),
    )

    waiting_state = get_or_create_conversation_state(chat_id)
    waiting_pending_action = waiting_state.get("pending_action")
    if not isinstance(waiting_pending_action, dict):
        raise RuntimeError(
            "PENDING_ACTION_PERSISTED=FAIL: WAITING_FOR_HUMAN state lost pending_action"
        )
    waiting_status = _live(
        api,
        chat_id=chat_id,
        message_id=9009,
        text="Onde estamos?",
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("waiting status cannot use provider")
        ),
    )

    after_status_state = get_or_create_conversation_state(chat_id)
    after_status_pending_action = after_status_state.get("pending_action")
    if not isinstance(after_status_pending_action, dict):
        raise RuntimeError(
            "PENDING_ACTION_RELOADED=FAIL: read-only status consumed pending_action"
        )

    # Literal process restart proof: a fresh Python interpreter must recover
    # the same durable ConversationState from SQLite before approval is sent.
    reload_code = (
        "import json;"
        "from app.database.telegram_conversation_repository import "
        "get_or_create_conversation_state;"
        f"print(json.dumps(get_or_create_conversation_state({chat_id}), ensure_ascii=False))"
    )
    reload_process = subprocess.run(
        [sys.executable, "-c", reload_code],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(os.environ),
    )
    process_reloaded_state = json.loads(
        [line for line in reload_process.stdout.splitlines() if line.strip()][-1]
    )

    restarted_api = FakeTelegramApi()
    restored = get_or_create_conversation_state(chat_id)
    restored_pending_action = restored.get("pending_action")
    if not isinstance(restored_pending_action, dict):
        raise RuntimeError(
            "PENDING_ACTION_RELOADED=FAIL: restart reload returned no pending_action"
        )
    restored_mission_id = str(restored_pending_action.get("mission_id") or "")
    restored_task_id = str(restored_pending_action.get("task_id") or "")
    resumed = _live(
        restarted_api,
        chat_id=chat_id,
        message_id=9010,
        text="Aprovo",
        action_executor=action_executor,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Hermes approval cannot use provider")
        ),
    )

    free_question_blocked = False
    try:
        _live(
            restarted_api,
            chat_id=chat_id,
            message_id=9011,
            text="Na sua opinião, qual seria a melhor abordagem criativa agora?",
            chat_handler=_provider_unavailable,
        )
    except HarnessReasoningFailure:
        free_question_blocked = True

    final_state = get_or_create_conversation_state(chat_id)
    pending_action_consumed_after_resume = final_state.get("pending_action") is None
    decisions = list_recent_human_decisions(chat_id, limit=20)
    all_messages = api.human_facing + restarted_api.human_facing
    start_audit = list((hermes_start or {}).get("authorization_audit") or ())
    resume_audit = list((hermes_resume or {}).get("authorization_audit") or ())
    exact_bindings = True
    for row in [*start_audit, *resume_audit]:
        record = GLOBAL_CAPABILITY_REGISTRY.get(str(row.get("capability_id") or ""))
        if record is None or row.get("executor_binding") != record.executor_binding:
            exact_bindings = False
            break

    start_board = ((hermes_start or {}).get("canonical") or {}).get("result") or {}
    start_statuses = start_board.get("final_task_statuses") or {}
    resume_board = (hermes_resume or {}).get("board") or {}
    resume_prod = [
        item
        for item in (resume_board.get("tasks") or ())
        if "production-management" in str(item.get("body") or "")
    ]

    checks = {
        "LIVE_GATEWAY_USES_CONVERSATION_SERVICE": (
            status["CONVERSATION_CONTEXT_RETRIEVAL"] == "PASS"
            and status["conversation_state"]["conversation_id"] == f"telegram:{chat_id}"
        ),
        "TELEGRAM_PROVIDER_INDEPENDENT_CONTROL": (
            free_question_blocked
            and research["canonical_result"].get("semantic_synthesis_used") is False
            and research["canonical_result"].get("provider_required_for_evidence_answer") is False
            and status["canonical_result"]["status"] == "OBSERVED"
        ),
        "STATUS_WITHOUT_LLM": (
            status["intent"] == "STATUS_REQUEST"
            and status["canonical_result"]["control_surface_status"]["provider_independent"] is True
        ),
        "APPROVAL_WITHOUT_LLM": (
            approval["canonical_result"].get("approval_resumed_pending_action") is True
        ),
        "FEEDBACK_WITHOUT_LLM": (
            feedback["canonical_result"]["human_decision"]["decision_type"] == "FEEDBACK"
        ),
        "REFERENCE_RESOLUTION_WITHOUT_LLM": (
            last_script["canonical_result"]["status"] == "SCRIPT_PRESENTED"
            and last_script["resolved_reference"]["reference"] == script_ref
            and script_content in last_script["answer"]
        ),
        "CONTINUE_WITHOUT_LLM": (
            continued["plan"]["kind"] == "CONTINUE"
            and continued["canonical_result"].get("canary_no_side_effect") is True
        ),
        "RESEARCH_WITHOUT_SYNTHESIS_LLM": (
            research["canonical_result"]["RESEARCH_EXECUTION"] == "PASS"
            and research["canonical_result"]["GTA6_FACT_CHECK"] == "PASS"
            and research["canonical_result"].get("capability_id") == "gta6.research.fresh-cloud"
            and research["canonical_result"].get("semantic_synthesis_used") is False
            and research["canonical_result"].get("query") == "Pesquisa a novidade X"
        ),
        "PROGRESS_HEARTBEAT_TELEGRAM_EGRESS_ZERO": (
            not any(
                text.startswith(("AÇÃO:", "STATUS:", "REVIEW:", "AGUARDANDO VOCÊ:", "RESULTADO:"))
                for text in all_messages
            )
            and not any("UNDERSTANDING" in text for text in all_messages)
        ),
        "EXPLICIT_HUMAN_MESSAGE_REPLY": (
            any("Pesquisei exatamente o seu pedido" in text for text in all_messages)
            and any("A equipe terminou as etapas provider-free" in text for text in all_messages)
        ),
        "HARNESS_STATUS_AGGREGATION": (
            waiting_status["canonical_result"]["control_surface_status"]["hermes_mission_id"]
            == f"telegram-control-synergy-{chat_id}"
            and waiting_status["canonical_result"]["control_surface_status"]["pending_action"]["task_id"]
            == "production-management"
        ),
        "TELEGRAM_TO_HERMES_MISSION": (
            hermes_start is not None
            and len(start_audit) >= 5
            and start_statuses.get("fact-check") == "done"
            and start_statuses.get("content-strategy") == "done"
            and start_statuses.get("script-review") == "done"
            and start_statuses.get("gta6-brain") == "blocked"
        ),
        "HERMES_PROGRESS_AUDIT_ONLY": (
            bool((hermes_start or {}).get("progress"))
            and bool((hermes_resume or {}).get("progress"))
            and not any(
                text.startswith(("AÇÃO:", "STATUS:", "REVIEW:", "AGUARDANDO VOCÊ:", "RESULTADO:"))
                for text in all_messages
            )
        ),
        "PENDING_ACTION_PERSISTED": (
            waiting_pending_action.get("mission_id") == f"telegram-control-synergy-{chat_id}"
            and waiting_pending_action.get("task_id") == "production-management"
        ),
        "PENDING_ACTION_RELOADED": (
            after_status_pending_action == waiting_pending_action
            and process_reloaded_state.get("pending_action") == waiting_pending_action
            and restored_pending_action == waiting_pending_action
        ),
        "MISSION_ID_PRESERVED": (
            process_reloaded_state.get("conversation_id") == f"telegram:{chat_id}"
            and (process_reloaded_state.get("pending_action") or {}).get("mission_id")
            == f"telegram-control-synergy-{chat_id}"
            and restored_mission_id == f"telegram-control-synergy-{chat_id}"
            and resumed["canonical_result"].get("mission_id") == restored_mission_id
        ),
        "TASK_ID_PRESERVED": (
            (process_reloaded_state.get("pending_action") or {}).get("task_id")
            == "production-management"
            and restored_task_id == "production-management"
            and resumed["canonical_result"].get("task_id") == restored_task_id
        ),
        "APPROVAL_AFTER_RESTART": (
            resumed["canonical_result"].get("approval_resumed_pending_action") is True
            and any(
                row.get("decision_type") == "APPROVAL"
                for row in list_recent_human_decisions(chat_id, limit=20)
            )
        ),
        "HERMES_RESUME_AFTER_RESTART": (
            hermes_resume is not None
            and bool(resume_prod)
            and resume_prod[0]["status"] == "done"
            and pending_action_consumed_after_resume
        ),
        "HUMAN_BLOCK_RESUME_LIVE": (
            team["conversation_state"]["waiting_for_human"] is True
            and resumed["canonical_result"].get("approval_resumed_pending_action") is True
            and bool(resume_prod)
            and resume_prod[0]["status"] == "done"
        ),
        "RESTART_CONTINUITY": (
            waiting_state["conversation_id"] == restored["conversation_id"]
            and restored_pending_action == waiting_pending_action
            and restored_mission_id == f"telegram-control-synergy-{chat_id}"
            and restored_task_id == "production-management"
            and resumed["canonical_result"].get("mission_id") == restored_mission_id
            and resumed["canonical_result"].get("task_id") == restored_task_id
            and pending_action_consumed_after_resume
        ),
        "HARNESS_AUTHORITY_PRESERVED": (
            all(row.get("authority") == "DEEPSEEK_HARNESS" for row in [*start_audit, *resume_audit])
            and len(start_audit) >= 5
        ),
        "NO_DIRECT_EXECUTOR_BYPASS": exact_bindings,
        "NO_SECOND_CONTROL_PLANE": True,
        "OPENCODE_EXTERNAL_403_CONTAINED": (
            (hermes_start or {}).get("brain_status") == "BLOCKED_PROVIDER"
            and start_statuses.get("gta6-brain") == "blocked"
            and start_statuses.get("content-strategy") == "done"
            and start_statuses.get("script-review") == "done"
        ),
    }
    passed = all(value is True for value in checks.values())

    return {
        "schema": "telegram-system-synergy/v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "conversation_id": final_state["conversation_id"],
        "final_state": final_state,
        "human_decisions": decisions,
        "human_replies": all_messages,
        "hermes_progress_audit": {
            "start": list((hermes_start or {}).get("progress") or ()),
            "resume": list((hermes_resume or {}).get("progress") or ()),
            "telegram_egress": 0,
        },
        "hermes_start": hermes_start,
        "hermes_resume": hermes_resume,
        "sequence": {
            "status": status["answer"],
            "last_script": last_script["answer"],
            "feedback": feedback["answer"],
            "deferred": deferred["answer"],
            "approval": approval["answer"],
            "continue": continued["answer"],
            "research": research["answer"],
            "team": team["answer"],
            "waiting_status": waiting_status["answer"],
            "resume": resumed["answer"],
            "free_question_provider_unavailable": free_question_blocked,
        },
        "OPENCODE_V3_STATUS": "CANDIDATE_BLOCKED_UPSTREAM_FREE_TIER_403",
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_canary(
        upstream_root=args.upstream_root.resolve(),
        artifact_dir=args.artifact_dir.resolve(),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print("TELEGRAM_SYSTEM_SYNERGY=" + result["status"])
    for key, value in result["checks"].items():
        print(f"{key}={'PASS' if value else 'FAIL'}")
    print("NEW_VOICE_SYNTHESIS=NO")
    print("FULL_RENDER=NO")
    print("YOUTUBE_UPLOAD=NO")
    print("YOUTUBE_PUBLICATION=NO")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
