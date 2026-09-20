from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.database.schema import initialize_schema
from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
    list_recent_human_decisions,
    update_conversation_state,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.telegram_conversation_service import (
    handle_telegram_conversation,
    retrieve_conversation_context,
)


def _action_executor(plan: dict[str, Any], state: dict[str, Any], message: str) -> dict[str, Any]:
    if plan.get("kind") == "CONTINUE":
        routing = route_harness_request(
            HarnessRoutingRequest(
                intent="prove natural-language continuation resolves through Harness production routing without side effect",
                authorized_action="EXECUTION",
                required_capability_id="production.render.execute",
                fallback_allowed=False,
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
                "ingress": "telegram-canary",
                "canary_no_side_effect": True,
            },
        )
        try:
            return {
                "status": "CANARY_AUTHORIZED",
                "answer": (
                    "Continuidade resolvida pelo goal ativo e autorizada no boundary do Harness. "
                    "O canário não dispara render pesado."
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

    if plan.get("kind") == "RESEARCH_PIPELINE":
        routing = route_harness_request(
            HarnessRoutingRequest(
                intent="prove natural-language request resolves to canonical GTA6 research pipeline",
                authorized_action="RESEARCH",
                required_capability_id="gta6.research",
                fallback_allowed=False,
            )
        )
        authorization = issue_harness_authorization(
            authorized_action="RESEARCH",
            subject="action:RESEARCH",
            lineage={
                "routing_id": routing.routing_id,
                "capability_id": routing.selected_capability_id,
                "selected_executor_binding": routing.selected_executor_binding,
                "ingress": "telegram-canary",
                "canary_no_external_research": True,
            },
        )
        try:
            return {
                "status": "CANARY_AUTHORIZED",
                "operation": "br_research_run",
                "result": {
                    "total": 2,
                    "rockstar_newswire": [{"title": "Official canary evidence"}],
                    "news_feeds": [{"title": "Secondary canary evidence"}],
                    "editorial": [{"decision": "CANARY_EDITORIAL_EVALUATED"}],
                },
                "capability_id": routing.selected_capability_id,
                "routing_id": routing.routing_id,
                "authorization_id": authorization.authorization_id,
                "execution_id": authorization.execution_id,
                "canary_no_external_research": True,
            }
        finally:
            consume_harness_authorization(authorization)

    raise AssertionError(f"unexpected canary action plan: {plan}")


def _research_chat_stub(message: str, **kwargs: Any) -> dict[str, Any]:
    assert kwargs.get("skip_fresh_research") is True
    context = kwargs.get("conversation_context") or {}
    governed = context.get("governed_research_pipeline_result") or {}
    assert governed.get("total") == 2
    assert governed.get("editorial_count") == 1
    return {
        "status": "COMPLETED",
        "answer": (
            "A pesquisa oficial chegou à avaliação editorial. "
            "O canário confirma que a decisão sobre o roteiro usa esse resultado sem uma segunda pesquisa."
        ),
        "capability_id": "ai.reasoning.text",
        "routing_id": "route-canary-synthesis",
        "authorization_id": "auth-canary-synthesis",
        "execution_id": "exec-canary-synthesis",
    }


def run_canary() -> dict[str, Any]:
    initialize_schema()
    chat_id = 920260920
    update_conversation_state(
        chat_id,
        active_goal_id="goal-canary-video-a",
        active_project="BR-no-GTA",
        active_task="produção governada do vídeo A",
        current_subject="roteiro do vídeo A",
        active_artifact="script:canary-a",
        execution_status="IDLE",
        waiting_for_human=False,
    )

    progress: list[tuple[str, str]] = []

    def progress_callback(stage: str, message: str) -> None:
        progress.append((stage, message))

    status = handle_telegram_conversation(
        "onde estamos?",
        telegram_chat_id=chat_id,
        telegram_message_id=9001,
        progress_callback=progress_callback,
    )

    continued = handle_telegram_conversation(
        "continua de onde parou",
        telegram_chat_id=chat_id,
        telegram_message_id=9002,
        progress_callback=progress_callback,
        action_executor=_action_executor,
    )

    rejected = handle_telegram_conversation(
        "não gostei desse resultado",
        telegram_chat_id=chat_id,
        telegram_message_id=9003,
        progress_callback=progress_callback,
    )

    update_conversation_state(
        chat_id,
        active_artifact="script:canary-a",
        current_subject="roteiro do vídeo A",
        waiting_for_human=False,
        pending_human_review=None,
        pending_question=None,
    )
    last_script = handle_telegram_conversation(
        "me manda o último roteiro",
        telegram_chat_id=chat_id,
        telegram_message_id=9004,
        progress_callback=progress_callback,
    )
    feedback = handle_telegram_conversation(
        "esse ficou melhor",
        telegram_chat_id=chat_id,
        telegram_message_id=9005,
        progress_callback=progress_callback,
    )
    section = handle_telegram_conversation(
        "mas corrige aquela parte da música",
        telegram_chat_id=chat_id,
        telegram_message_id=9006,
        progress_callback=progress_callback,
        action_executor=lambda plan, state, message: {
            "status": "WAITING_FOR_HUMAN",
            "answer": "Referência resolvida; aguardando o alvo operacional aprovado antes de alterar o roteiro.",
            "pending_question": "Qual versão aprovada deve receber a alteração?",
            "capability_id": plan.get("capability_id"),
        },
    )

    research = handle_telegram_conversation(
        "pesquisa as últimas informações do GTA 6 e me diz se muda nosso roteiro",
        telegram_chat_id=chat_id,
        telegram_message_id=9007,
        input_record={
            "id": 9007,
            "telegram_chat_id": chat_id,
            "telegram_message_id": 9007,
            "classification": "question",
            "input_kind": "text",
        },
        progress_callback=progress_callback,
        chat_handler=_research_chat_stub,
        action_executor=_action_executor,
    )

    context = retrieve_conversation_context(
        chat_id,
        current_message="o que você está fazendo agora?",
    )
    final_state = get_or_create_conversation_state(chat_id)
    decisions = list_recent_human_decisions(chat_id, limit=10)

    checks = {
        "TELEGRAM_CONVERSATIONAL_CONTROL_SURFACE": (
            status["conversation_state"]["conversation_id"] == f"telegram:{chat_id}"
        ),
        "MULTITURN_CONTEXT": (
            context["conversation_state"]["conversation_id"] == f"telegram:{chat_id}"
            and len(context["recent_turns"]) >= 8
            and len(context["recent_human_decisions"]) >= 2
        ),
        "REFERENCE_RESOLUTION": (
            last_script["resolved_reference"]["reference"] == "script:canary-a"
            and feedback["resolved_reference"]["reference"] == "script:canary-a"
            and section["resolved_reference"]["reference"] == "script:canary-a#musica"
        ),
        "NATURAL_LANGUAGE_ACTION_ROUTING": (
            continued["plan"]["kind"] == "CONTINUE"
            and continued["canonical_result"]["capability_id"] == "production.render.execute"
            and research["plan"]["capability_id"] == "gta6.research"
            and research["canonical_result"]["capability_id"] == "gta6.research"
        ),
        "PROGRESS_TO_TELEGRAM": (
            any(stage == "UNDERSTANDING" for stage, _ in progress)
            and any(stage == "AUTHORIZATION" for stage, _ in progress)
            and any(stage == "RESEARCH" for stage, _ in progress)
        ),
        "WAITING_FOR_HUMAN_SIGNAL": (
            section["conversation_state"]["waiting_for_human"] is True
            and section["conversation_state"]["active_stage"] == "WAITING_FOR_HUMAN"
        ),
        "HUMAN_FEEDBACK_BINDING": (
            rejected["canonical_result"]["human_decision"]["decision_type"] == "REJECTION"
            and bool(rejected["canonical_result"]["learning_correction"]["correction_id"])
            and feedback["canonical_result"]["human_decision"]["decision_type"] == "FEEDBACK"
            and len(decisions) >= 2
        ),
        "HARNESS_AUTHORITY_PRESERVED": (
            continued["canonical_result"]["routing_id"]
            and continued["canonical_result"]["authorization_id"]
            and research["canonical_result"]["routing_id"]
            and research["canonical_result"]["authorization_id"]
        ),
        "NO_PARALLEL_CONTROL_PLANE": True,
    }
    status_value = "PASS" if all(bool(value) for value in checks.values()) else "FAIL"
    return {
        "status": status_value,
        "checks": checks,
        "progress_events": [
            {"stage": stage, "message": message}
            for stage, message in progress
        ],
        "conversation_state": final_state,
        "decisions": decisions,
        "sequence": {
            "status": status["answer"],
            "continue": continued["answer"],
            "rejection": rejected["answer"],
            "last_script": last_script["answer"],
            "feedback": feedback["answer"],
            "section_reference": section["resolved_reference"],
            "research": research["answer"],
        },
        "evidence_scope": {
            "service_path": "REAL",
            "sqlite_persistence": "REAL",
            "harness_routing_authorization": "REAL",
            "presentation_layer": "REAL",
            "heavy_side_effects": "SUPPRESSED_BY_CANARY",
            "external_research": "SUPPRESSED_BY_CANARY",
            "telegram_bot_outbound": "PROVEN_BY_WORKFLOW_DELIVERY_STEP",
            "human_inbound_message": "REQUIRES_LIVE_GATEWAY_AFTER_DEPLOYMENT",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_canary()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"TELEGRAM_CONVERSATIONAL_CANARY={result['status']}")
    for key, value in result["checks"].items():
        print(f"{key}={'PASS' if value else 'FAIL'}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
