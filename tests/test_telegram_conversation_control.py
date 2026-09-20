from __future__ import annotations

from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
    list_recent_conversation_turns,
    update_conversation_state,
)
from app.services.telegram_conversation_service import (
    classify_conversation_intent,
    handle_telegram_conversation,
    resolve_conversation_reference,
)


def _presenter(canonical, **_kwargs):
    return {"text": canonical.get("answer") or canonical.get("status") or "OK"}


def _chat_stub(message: str, **kwargs):
    return {
        "status": "COMPLETED",
        "answer": f"chat:{message}",
        "capability_id": (
            "gta6.research.fresh-cloud"
            if kwargs.get("force_fresh_research")
            else "ai.reasoning.text"
        ),
        "execution_id": "exec-chat",
    }


def test_intent_classifier_covers_governed_taxonomy():
    assert classify_conversation_intent("onde estamos?") == "STATUS_REQUEST"
    assert classify_conversation_intent("pesquisa as últimas informações do GTA 6") == "RESEARCH_REQUEST"
    assert classify_conversation_intent("continua de onde parou") == "EXECUTION_REQUEST"
    assert classify_conversation_intent("esse ficou melhor") == "FEEDBACK"
    assert classify_conversation_intent("esse roteiro eu aprovo") == "APPROVAL"
    assert classify_conversation_intent("não gostei desse resultado") == "REJECTION"
    assert classify_conversation_intent("cancela isso") == "CANCEL_REQUEST"
    assert classify_conversation_intent("quando sai?") == "QUESTION"


def test_reference_resolution_tracks_last_artifact_and_section():
    chat_id = 9981
    update_conversation_state(
        chat_id,
        active_artifact="script:9",
        current_subject="roteiro atual",
    )
    state = get_or_create_conversation_state(chat_id)
    recent = list_recent_conversation_turns(chat_id)

    latest = resolve_conversation_reference(
        "me manda o último roteiro",
        state=state,
        recent_turns=recent,
    )
    assert latest["reference"] == "script:9"

    section = resolve_conversation_reference(
        "mas corrige aquela parte da música",
        state=state,
        recent_turns=recent,
    )
    assert section["reference"] == "script:9#musica"


def test_multiturn_pronoun_feedback_binds_human_decision_and_learning():
    chat_id = 9982
    update_conversation_state(
        chat_id,
        active_artifact="script:9",
        current_subject="roteiro atual",
        active_goal_id="goal-a",
        active_task="revisar roteiro",
    )

    first = handle_telegram_conversation(
        "me manda o último roteiro",
        telegram_chat_id=chat_id,
        telegram_message_id=101,
        chat_handler=_chat_stub,
        presenter=_presenter,
    )
    assert first["resolved_reference"]["reference"] == "script:9"

    feedback = handle_telegram_conversation(
        "esse ficou melhor",
        telegram_chat_id=chat_id,
        telegram_message_id=102,
        chat_handler=_chat_stub,
        presenter=_presenter,
    )
    assert feedback["intent"] == "FEEDBACK"
    assert feedback["resolved_reference"]["reference"] == "script:9"
    assert feedback["canonical_result"]["human_decision"]["decision_type"] == "FEEDBACK"
    assert feedback["canonical_result"]["learning_correction"]["correction_id"].startswith("correction-")

    correction = handle_telegram_conversation(
        "mas corrige aquela parte da música",
        telegram_chat_id=chat_id,
        telegram_message_id=103,
        chat_handler=_chat_stub,
        action_executor=lambda plan, state, message: {
            "status": "WAITING_FOR_HUMAN",
            "answer": "A correção foi vinculada; aguardando alvo operacional aprovado.",
            "capability_id": plan.get("capability_id"),
            "pending_question": "Qual versão deve receber a alteração?",
        },
        presenter=_presenter,
    )
    assert correction["resolved_reference"]["reference"] == "script:9#musica"
    assert correction["conversation_state"]["waiting_for_human"] is True
    assert correction["CONVERSATION_CONTEXT_RETRIEVAL"] == "PASS"
    assert correction["HARNESS_AUTHORITY_PRESERVED"] == "PASS"


def test_file_submission_is_a_first_class_conversation_intent():
    result = handle_telegram_conversation(
        "arquivo enviado: referencia.mp4",
        telegram_chat_id=9988,
        telegram_message_id=701,
        input_record={
            "id": 701,
            "telegram_chat_id": 9988,
            "telegram_message_id": 701,
            "classification": "reference_media",
            "input_kind": "video",
            "remote_verified": True,
        },
        has_attachment=True,
        chat_handler=_chat_stub,
        presenter=_presenter,
    )
    assert result["intent"] == "FILE_SUBMISSION"
    assert result["conversation_state"]["last_human_intent"] == "FILE_SUBMISSION"


def test_natural_language_research_routes_without_slash_command():
    result = handle_telegram_conversation(
        "pesquisa as últimas informações do GTA 6 e me diz se muda nosso roteiro",
        telegram_chat_id=9983,
        telegram_message_id=201,
        input_record={"id": 55, "telegram_chat_id": 9983, "telegram_message_id": 201},
        chat_handler=_chat_stub,
        presenter=_presenter,
    )
    assert result["intent"] == "RESEARCH_REQUEST"
    assert result["plan"]["capability_id"] == "gta6.research.fresh-cloud"
    assert result["canonical_result"]["capability_id"] == "gta6.research.fresh-cloud"
    assert result["conversation_state"]["execution_status"] == "COMPLETED"


def test_continue_uses_active_goal_and_real_action_boundary():
    seen = {}

    def execute(plan, state, message):
        seen["plan"] = dict(plan)
        seen["state"] = dict(state)
        seen["message"] = message
        return {
            "status": "COMPLETED",
            "goal_id": plan["active_goal_id"],
            "execution_id": "exec-continue-1",
            "run_id": "run-continue-1",
            "capability_id": "production.render.execute",
            "answer": "Continuei a tarefa ativa pelo boundary oficial.",
        }

    chat_id = 9984
    update_conversation_state(
        chat_id,
        active_goal_id="goal-video-a",
        active_task="produção do vídeo A",
        current_subject="vídeo A",
    )

    result = handle_telegram_conversation(
        "continua de onde parou",
        telegram_chat_id=chat_id,
        telegram_message_id=301,
        action_executor=execute,
        chat_handler=_chat_stub,
        presenter=_presenter,
    )
    assert result["plan"]["kind"] == "CONTINUE"
    assert seen["plan"]["active_goal_id"] == "goal-video-a"
    assert result["conversation_state"]["active_run_id"] == "run-continue-1"
    assert result["conversation_state"]["execution_status"] == "COMPLETED"


def test_status_answer_comes_from_persisted_real_state_not_model_guess():
    chat_id = 9985
    update_conversation_state(
        chat_id,
        active_goal_id="goal-voice",
        active_task="extração acústica PT-BR",
        active_run_id="35499900001",
        active_stage="ACOUSTIC_EXTRACTION",
        execution_status="RUNNING",
        active_blocker=None,
    )

    result = handle_telegram_conversation(
        "o que você está fazendo agora?",
        telegram_chat_id=chat_id,
        telegram_message_id=401,
        chat_handler=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("status must not use model chat")
        ),
        presenter=_presenter,
    )
    assert "extração acústica PT-BR" in result["answer"]
    assert "ACOUSTIC_EXTRACTION" in result["answer"]
    assert "35499900001" in result["answer"]


def test_deferred_execution_resumes_only_after_explicit_approval():
    chat_id = 9989
    update_conversation_state(
        chat_id,
        active_goal_id="goal-video-a",
        active_task="produção do vídeo A",
        active_artifact="script:8",
        current_subject="roteiro do vídeo A",
    )
    calls = []

    def execute(plan, state, message):
        calls.append((dict(plan), message))
        return {
            "status": "COMPLETED",
            "goal_id": plan.get("active_goal_id"),
            "run_id": "run-after-approval",
            "execution_id": "exec-after-approval",
            "capability_id": "production.render.execute",
            "answer": "Ação pendente retomada pelo Harness.",
        }

    deferred = handle_telegram_conversation(
        "faz o vídeo depois que eu aprovar",
        telegram_chat_id=chat_id,
        telegram_message_id=451,
        action_executor=execute,
        chat_handler=_chat_stub,
        presenter=_presenter,
    )
    assert deferred["plan"]["kind"] == "DEFER_UNTIL_APPROVAL"
    assert deferred["conversation_state"]["waiting_for_human"] is True
    assert deferred["conversation_state"]["pending_action"]["kind"] == "CONTINUE"
    assert calls == []

    approved = handle_telegram_conversation(
        "esse roteiro eu aprovo",
        telegram_chat_id=chat_id,
        telegram_message_id=452,
        action_executor=execute,
        chat_handler=_chat_stub,
        presenter=_presenter,
    )
    assert len(calls) == 1
    assert calls[0][0]["active_goal_id"] == "goal-video-a"
    assert approved["canonical_result"]["approval_resumed_pending_action"] is True
    assert approved["conversation_state"]["waiting_for_human"] is False
    assert approved["conversation_state"]["active_run_id"] == "run-after-approval"
    assert approved["conversation_state"]["pending_action"] is None


def test_waiting_for_human_is_explicit_state_not_silent_stop():
    chat_id = 9986
    update_conversation_state(
        chat_id,
        active_artifact="script:8",
        active_goal_id="goal-a",
        active_task="revisão humana do roteiro",
    )

    result = handle_telegram_conversation(
        "corrige a voz e me manda novos samples",
        telegram_chat_id=chat_id,
        telegram_message_id=501,
        action_executor=lambda plan, state, message: {
            "status": "WAITING_FOR_HUMAN",
            "answer": "Selecionei a narração, mas falta o payload aprovado.",
            "capability_id": "narration.generate.pt-BR",
            "pending_question": "Qual take aprovado devo usar como base?",
        },
        presenter=_presenter,
    )
    state = result["conversation_state"]
    assert result["plan"]["capability_id"] == "narration.generate.pt-BR"
    assert state["waiting_for_human"] is True
    assert state["active_stage"] == "WAITING_FOR_HUMAN"
    assert state["pending_question"] == "Qual take aprovado devo usar como base?"


def test_recent_turns_are_compact_and_persisted():
    chat_id = 9987
    for index in range(1, 5):
        handle_telegram_conversation(
            f"mensagem {index}",
            telegram_chat_id=chat_id,
            telegram_message_id=600 + index,
            chat_handler=_chat_stub,
            presenter=_presenter,
        )
    turns = list_recent_conversation_turns(chat_id, limit=20)
    state = get_or_create_conversation_state(chat_id)
    assert len(turns) == 8
    assert len(state["recent_turn_ids"]) == 8
    assert state["recent_turn_ids"] == [turn["turn_id"] for turn in turns]
