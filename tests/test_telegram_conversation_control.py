from __future__ import annotations

from app.database.ideas_repository import insert_idea
from app.database.scripts_repository import insert_script
from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
    list_recent_conversation_turns,
    update_conversation_state,
)
from app.services.telegram_conversation_service import (
    classify_conversation_intent,
    handle_telegram_conversation,
    plan_natural_language_action,
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


def test_last_script_request_delivers_canonical_script_content():
    idea_id = insert_idea("Ideia teste roteiro", description="teste")
    script_id = insert_script(
        idea_id,
        "Roteiro teste",
        "Texto canônico completo do roteiro para revisão humana.",
        status="draft",
        version=1,
    )
    chat_id = 9990
    update_conversation_state(
        chat_id,
        active_artifact=f"script:{script_id}",
        current_subject="roteiro atual",
    )
    result = handle_telegram_conversation(
        "me manda o último roteiro",
        telegram_chat_id=chat_id,
        telegram_message_id=91,
        chat_handler=_chat_stub,
        presenter=_presenter,
    )
    assert result["canonical_result"]["status"] == "SCRIPT_PRESENTED"
    assert result["canonical_result"]["script_id"] == script_id
    assert result["answer"] == "Texto canônico completo do roteiro para revisão humana."
    assert result["conversation_state"]["active_artifact"] == f"script:{script_id}"


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
    seen = {}

    def research_execute(plan, state, message):
        seen["plan"] = dict(plan)
        return {
            "status": "COMPLETED",
            "operation": "br_research_run",
            "result": {
                "total": 3,
                "rockstar_newswire": [{"title": "Official update"}],
                "news_feeds": [{"title": "Secondary report"}],
                "editorial": [{"decision": "QUEUE"}],
            },
            "capability_id": "gta6.research",
            "routing_id": "route-research",
            "authorization_id": "auth-research",
            "execution_id": "exec-research",
        }

    def synthesize(message, **kwargs):
        seen["skip_fresh_research"] = kwargs.get("skip_fresh_research")
        seen["reasoning_context"] = kwargs.get("conversation_context")
        return {
            "status": "COMPLETED",
            "answer": "A pesquisa gerou uma avaliação editorial nova; o roteiro precisa ser reavaliado antes de produção.",
            "capability_id": "ai.reasoning.text",
            "routing_id": "route-ai",
            "authorization_id": "auth-ai",
            "execution_id": "exec-ai",
        }

    result = handle_telegram_conversation(
        "pesquisa as últimas informações do GTA 6 e me diz se muda nosso roteiro",
        telegram_chat_id=9983,
        telegram_message_id=201,
        input_record={"id": 55, "telegram_chat_id": 9983, "telegram_message_id": 201},
        chat_handler=synthesize,
        action_executor=research_execute,
        presenter=_presenter,
    )
    assert result["intent"] == "RESEARCH_REQUEST"
    assert result["plan"]["kind"] == "RESEARCH_PIPELINE"
    assert result["plan"]["capability_id"] == "gta6.research"
    assert seen["plan"]["authorized_action"] == "RESEARCH"
    assert seen["skip_fresh_research"] is True
    compact = seen["reasoning_context"]["governed_research_pipeline_result"]
    assert compact["total"] == 3
    assert compact["editorial_count"] == 1
    assert result["canonical_result"]["capability_id"] == "gta6.research"
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



def test_research_survives_optional_reasoning_provider_failure():
    from app.services.telegram_harness_service import HarnessReasoningFailure

    chat_id = 9991

    def execute(plan, state, message):
        assert plan["kind"] == "RESEARCH_PIPELINE"
        return {
            "status": "COMPLETED",
            "operation": "br_research_run",
            "result": {
                "total": 2,
                "rockstar_newswire": [{"title": "Official evidence survives"}],
                "news_feeds": [{"title": "Secondary evidence survives"}],
                "editorial": [{"decision": "REVIEW_SCRIPT"}],
            },
            "capability_id": "gta6.research",
            "routing_id": "route-research-provider-free",
            "authorization_id": "auth-research-provider-free",
            "execution_id": "exec-research-provider-free",
        }

    def unavailable(*_args, **_kwargs):
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

    result = handle_telegram_conversation(
        "pesquisa a novidade X",
        telegram_chat_id=chat_id,
        telegram_message_id=801,
        action_executor=execute,
        chat_handler=unavailable,
        presenter=_presenter,
    )

    canonical = result["canonical_result"]
    assert canonical["RESEARCH_EXECUTION"] == "PASS"
    assert canonical["OPTIONAL_SYNTHESIS"] == "UNAVAILABLE"
    assert canonical["capability_id"] == "gta6.research"
    assert "Official evidence survives" in result["answer"]
    assert "não acrescentei interpretação" in result["answer"]
    assert result["conversation_state"]["execution_status"] == "COMPLETED"


def test_team_analysis_routes_to_hermes_action_boundary_without_chat_provider():
    chat_id = 9992
    update_conversation_state(
        chat_id,
        active_goal_id="goal-video-a",
        active_artifact="script:8",
        active_task="revisão do roteiro A",
    )
    seen = {}

    def execute(plan, state, message):
        seen["plan"] = dict(plan)
        return {
            "status": "RUNNING",
            "answer": "Missão Hermes despachada pelo Harness.",
            "capability_id": "collaboration.hermes.execute",
            "mission_id": "tg-hermes-test-1",
            "goal_id": "goal-video-a",
            "run_id": "35550000001",
            "routing_id": "route-hermes",
            "authorization_id": "auth-hermes",
            "execution_id": "exec-hermes",
            "pending_action": {
                "kind": "HERMES_CLOUD_RESUME",
                "mission_id": "tg-hermes-test-1",
                "task_id": "production-management",
                "goal_id": "goal-video-a",
                "parent_run_id": "35550000001",
            },
        }

    result = handle_telegram_conversation(
        "Analisa esse roteiro com a equipe e vê o que falta",
        telegram_chat_id=chat_id,
        telegram_message_id=802,
        action_executor=execute,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Hermes collaboration must not enter generic model chat")
        ),
        presenter=_presenter,
    )

    assert result["intent"] == "EXECUTION_REQUEST"
    assert seen["plan"]["kind"] == "HERMES_COLLABORATION"
    assert seen["plan"]["capability_id"] == "collaboration.hermes.execute"
    assert result["conversation_state"]["execution_status"] == "RUNNING"
    assert result["conversation_state"]["active_run_id"] == "35550000001"
    assert result["conversation_state"]["pending_action"]["mission_id"] == "tg-hermes-test-1"


def test_status_aggregates_hermes_pending_state_without_llm():
    chat_id = 9993
    update_conversation_state(
        chat_id,
        active_goal_id="goal-video-a",
        active_task="produção governada",
        active_run_id="35550000002",
        active_stage="RUNNING",
        execution_status="RUNNING",
        active_artifact="script:8",
        pending_action={
            "kind": "HERMES_CLOUD_RESUME",
            "mission_id": "tg-hermes-status-1",
            "task_id": "production-management",
            "goal_id": "goal-video-a",
            "parent_run_id": "35550000002",
        },
    )

    result = handle_telegram_conversation(
        "Onde estamos?",
        telegram_chat_id=chat_id,
        telegram_message_id=803,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("status must remain provider-free")
        ),
        presenter=_presenter,
    )

    status = result["canonical_result"]["control_surface_status"]
    assert status["provider_independent"] is True
    assert status["authority"] == "DEEPSEEK_HARNESS"
    assert status["hermes_mission_id"] == "tg-hermes-status-1"
    assert status["active_run_id"] == "35550000002"
    assert status["pending_action"]["task_id"] == "production-management"


def test_restart_continuity_approval_reuses_persisted_hermes_lineage():
    chat_id = 9994
    pending = {
        "kind": "HERMES_CLOUD_RESUME",
        "mission_id": "tg-hermes-restart-1",
        "task_id": "production-management",
        "goal_id": "goal-video-a",
        "artifact_ref": "script:8",
        "parent_run_id": "35550000003",
        "authorized_action": "EXECUTION",
    }
    update_conversation_state(
        chat_id,
        active_goal_id="goal-video-a",
        active_artifact="script:8",
        active_run_id="35550000003",
        execution_status="RUNNING",
        pending_action=pending,
    )

    # Simulate a fresh gateway process by reloading only durable state.
    restored = get_or_create_conversation_state(chat_id)
    assert restored["pending_action"] == pending
    seen = {}

    def resume(plan, state, message):
        seen["plan"] = dict(plan)
        seen["conversation_id"] = state["conversation_id"]
        return {
            "status": "RUNNING",
            "answer": "Mesma missão retomada.",
            "capability_id": "collaboration.hermes.execute",
            "mission_id": plan["mission_id"],
            "task_id": plan["task_id"],
            "goal_id": plan["goal_id"],
            "run_id": "35550000004",
            "routing_id": "route-resume",
            "authorization_id": "auth-resume",
            "execution_id": "exec-resume",
        }

    result = handle_telegram_conversation(
        "Aprovo",
        telegram_chat_id=chat_id,
        telegram_message_id=804,
        action_executor=resume,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("unambiguous approval must not require an LLM")
        ),
        presenter=_presenter,
    )

    assert seen["conversation_id"] == f"telegram:{chat_id}"
    assert seen["plan"]["mission_id"] == "tg-hermes-restart-1"
    assert seen["plan"]["task_id"] == "production-management"
    assert result["canonical_result"]["approval_resumed_pending_action"] is True
    assert result["canonical_result"]["mission_id"] == "tg-hermes-restart-1"
    assert result["conversation_state"]["active_run_id"] == "35550000004"
    assert result["conversation_state"]["pending_action"] is None



def test_status_observation_does_not_consume_persisted_pending_action():
    chat_id = 9995
    pending = {
        "kind": "HERMES_CLOUD_RESUME",
        "mission_id": "tg-hermes-status-restart-1",
        "task_id": "production-management",
        "goal_id": "goal-video-a",
        "artifact_ref": "script:8",
        "parent_run_id": "35550000005",
        "authorized_action": "EXECUTION",
    }
    persisted = update_conversation_state(
        chat_id,
        active_goal_id="goal-video-a",
        active_artifact="script:8",
        active_run_id="35550000005",
        active_stage="WAITING_FOR_HUMAN",
        execution_status="WAITING_FOR_HUMAN",
        waiting_for_human=True,
        pending_human_review="script:8",
        pending_question="Aprova continuar?",
        pending_action=pending,
    )
    assert persisted["pending_action"] == pending

    observed = handle_telegram_conversation(
        "Onde estamos?",
        telegram_chat_id=chat_id,
        telegram_message_id=805,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("status observation must not use an LLM")
        ),
        presenter=_presenter,
    )
    assert observed["canonical_result"]["control_surface_status"]["pending_action"] == pending

    # get_or_create opens a new SQLite connection on every call, so this is a
    # durable reload rather than an in-memory state check.
    reloaded = get_or_create_conversation_state(chat_id)
    assert reloaded["conversation_id"] == f"telegram:{chat_id}"
    assert reloaded["pending_action"] == pending
    assert reloaded["pending_action"]["mission_id"] == "tg-hermes-status-restart-1"
    assert reloaded["pending_action"]["task_id"] == "production-management"
    assert reloaded["waiting_for_human"] is True
    assert reloaded["execution_status"] == "WAITING_FOR_HUMAN"
    assert reloaded["active_stage"] == "WAITING_FOR_HUMAN"
    assert reloaded["pending_question"] == "Aprova continuar?"



def test_private_group_share_human_identity_and_project_thread():
    user_id = 99100
    private_chat = 99101
    group_chat = -99102

    update_conversation_state(
        private_chat,
        active_goal_id="goal-video-a",
        active_task="revisão humana do roteiro",
        active_artifact="script:8",
        current_subject="voz do vídeo A",
    )

    private = handle_telegram_conversation(
        "não gostei dessa voz",
        telegram_user_id=user_id,
        telegram_chat_id=private_chat,
        telegram_chat_type="private",
        telegram_message_id=99103,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("human decision must remain provider-free")
        ),
        presenter=_presenter,
    )
    assert private["intent"] == "REJECTION"
    assert private["TELEGRAM_USER_ID_PROPAGATED"] == "PASS"
    assert private["TELEGRAM_CHAT_TYPE_PROPAGATED"] == "PASS"
    assert private["human_identity"]["chat_type"] == "private"
    assert private["human_identity"]["telegram_user_id"] == user_id

    group = handle_telegram_conversation(
        "Onde estamos?",
        telegram_user_id=user_id,
        telegram_chat_id=group_chat,
        telegram_chat_type="group",
        telegram_message_id=99104,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("group status must remain provider-free")
        ),
        action_executor=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("group status must not enter Hermes/action execution")
        ),
        presenter=_presenter,
    )
    assert group["human_identity"]["chat_type"] == "group"
    assert group["human_identity"]["telegram_user_id"] == user_id
    assert (
        private["human_identity"]["human_identity_id"]
        == group["human_identity"]["human_identity_id"]
    )
    assert private["human_identity"]["thread_id"] == group["human_identity"]["thread_id"]
    assert (
        private["human_identity"]["surface_session_id"]
        != group["human_identity"]["surface_session_id"]
    )
    assert group["conversation_state"]["active_goal_id"] == "goal-video-a"
    assert group["conversation_state"]["active_artifact"] == "script:8"
    assert group["TELEGRAM_USER_ID_PROPAGATED"] == "PASS"
    assert group["TELEGRAM_CHAT_TYPE_PROPAGATED"] == "PASS"


def test_private_human_decision_is_recalled_from_group_canonical_memory():
    user_id = 99110
    private_chat = 99111
    group_chat = -99112

    update_conversation_state(
        private_chat,
        active_goal_id="goal-voice-shared",
        active_task="revisão da voz",
        active_artifact="script:8",
        current_subject="voz",
    )
    private = handle_telegram_conversation(
        "não gostei dessa voz",
        telegram_user_id=user_id,
        telegram_chat_id=private_chat,
        telegram_chat_type="private",
        telegram_message_id=99113,
        presenter=_presenter,
    )
    canonical_decision = private["canonical_result"]["canonical_human_decision"]

    progress = []
    group = handle_telegram_conversation(
        "o que eu decidi sobre a voz?",
        telegram_user_id=user_id,
        telegram_chat_id=group_chat,
        telegram_chat_type="group",
        telegram_message_id=99114,
        progress_callback=lambda stage, message: progress.append((stage, message)),
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("canonical memory recall must remain provider-free")
        ),
        action_executor=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("canonical memory recall must not enter Hermes")
        ),
        presenter=_presenter,
    )

    recalled = group["canonical_result"]["human_decisions"]
    assert canonical_decision["decision_id"] in {
        item["decision_id"] for item in recalled
    }
    assert group["canonical_result"]["provider_independent"] is True
    assert progress == []
    assert private["human_identity"]["thread_id"] == group["human_identity"]["thread_id"]



def test_natural_system_improvement_goal_does_not_require_hermes_keyword():
    plan = plan_natural_language_action(
        "Analisa por que o sistema está demorando e corrige o que for inútil sem reduzir qualidade.",
        intent="EXECUTION_REQUEST",
        state={"active_goal_id": "system-health", "active_artifact": None},
        resolved_reference=None,
    )
    assert plan["kind"] == "SYSTEM_IMPROVEMENT_MISSION"
    assert plan["authorized_action"] == "DEVELOPMENT"
    assert plan["mission_planner"] == "HARNESS_REGISTRY_COMPETENCE"
    assert plan["collaboration_runtime"] == "HERMES_WHEN_MULTI_AGENT_REQUIRED"
    assert "hermes" not in "Analisa por que o sistema está demorando e corrige o que for inútil sem reduzir qualidade.".casefold()
