from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
    update_conversation_state,
)
from app.services.telegram_conversation_service import handle_telegram_conversation


def _presenter(canonical, **_kwargs):
    return {"text": canonical.get("answer") or canonical.get("status") or "OK"}


def _no_provider(*_args, **_kwargs):
    raise AssertionError("status must not call provider")


def _no_action(*_args, **_kwargs):
    raise AssertionError("status must not call Hermes/action execution")


def test_status_query_never_replaces_project_subject_and_exposes_canonical_snapshot():
    chat_id = 99301
    update_conversation_state(
        chat_id,
        active_project="BR-no-GTA",
        active_goal_id="goal-video-a",
        active_task="revisão editorial do vídeo A",
        current_subject="roteiro do vídeo A",
        active_artifact="script:8",
        execution_status="COMPLETED",
        active_stage=None,
        last_execution_result={
            "status": "COMPLETED",
            "capability_id": "youtube.department.script-review",
            "answer": "Revisão editorial concluída e preservada.",
            "goal_id": "goal-video-a",
        },
    )

    result = handle_telegram_conversation(
        "Onde estamos?",
        telegram_chat_id=chat_id,
        telegram_user_id=777,
        telegram_chat_type="private",
        telegram_message_id=99302,
        chat_handler=_no_provider,
        action_executor=_no_action,
        presenter=_presenter,
    )

    state = get_or_create_conversation_state(chat_id)
    snapshot = result["canonical_result"]["project_status_snapshot"]
    assert state["current_subject"] == "roteiro do vídeo A"
    assert snapshot["project"] == "BR-no-GTA"
    assert snapshot["current_goal"] == "goal-video-a"
    assert snapshot["current_subject"] == "roteiro do vídeo A"
    assert snapshot["latest_meaningful_result"]["status"] == "COMPLETED"
    assert snapshot["next_action"]
    assert snapshot["provider_calls"] == 0
    assert snapshot["hermes_calls"] == 0
    assert "Onde estamos" not in result["answer"]
    assert "Projeto: BR-no-GTA" in result["answer"]
    assert "Último avanço:" in result["answer"]
    assert "Agora:" in result["answer"]
    assert "Próximo:" in result["answer"]
    assert "\\n" not in result["answer"]
    assert "\nÚltimo avanço:" in result["answer"]
    assert result["canonical_result"]["STATUS_PROVIDER_CALLS"] == 0
    assert result["canonical_result"]["STATUS_HERMES_CALLS"] == 0
