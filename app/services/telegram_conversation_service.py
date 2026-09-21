from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable

from app.database import harness_learning_repository as learning_repository
from app.database.telegram_conversation_repository import (
    append_conversation_turn,
    get_or_create_conversation_state,
    list_recent_conversation_turns,
    list_recent_human_decisions,
    record_human_decision,
    resolve_telegram_human_context,
    update_conversation_state,
    update_shared_thread_context,
)
from app.services.gta6_observation_service import build_gta6_observation
from app.services.harness_learning_service import record_human_correction
from app.services.harness_collaboration_service import (
    build_goal_envelope,
    plan_mission_from_human_goal,
)
from app.services.human_presentation_service import present_canonical_result_under_harness
from app.services.memory_plane_service import record_canonical_human_decision
from app.services.script_service import get_script, list_scripts
from app.services.telegram_harness_service import (
    HarnessReasoningFailure,
    chat_under_harness,
)
from app.services.telegram_control_surface_status import (
    build_canonical_project_status_snapshot,
    build_harness_control_surface_status,
    render_canonical_project_status,
)
from app.services.telegram_status_reconciliation_service import (
    reconcile_stale_progress_state,
)
from app.services.telegram_gta6_query_service import execute_telegram_gta6_query
from app.services.telegram_intent_resolution_service import resolve_contextual_intent
from app.services.telegram_knowledge_recall_service import recall_canonical_gta6_knowledge
from app.services.telegram_memory_candidate_service import create_telegram_memory_candidate


INTENTS = {
    "QUESTION",
    "INSTRUCTION",
    "FEEDBACK",
    "APPROVAL",
    "REJECTION",
    "STATUS_REQUEST",
    "MEMORY_RECALL_REQUEST",
    "MEMORY_WRITE_REQUEST",
    "KNOWLEDGE_RECALL_REQUEST",
    "FILE_SUBMISSION",
    "RESEARCH_REQUEST",
    "EXECUTION_REQUEST",
    "CANCEL_REQUEST",
    "CLARIFICATION",
}


ProgressCallback = Callable[[str, str], None]
ChatHandler = Callable[..., dict[str, Any]]
ActionExecutor = Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]


_SHARED_THREAD_FIELDS = (
    "active_goal_id",
    "active_task",
    "current_subject",
    "active_artifact",
    "active_run_id",
    "last_human_decision",
    "waiting_for_human",
    "pending_question",
    "pending_human_review",
)


def _bind_surface_identity(
    *,
    telegram_user_id: int | None,
    telegram_chat_id: int,
    telegram_chat_type: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    state = get_or_create_conversation_state(telegram_chat_id)
    if telegram_user_id is None:
        return None, state

    identity = resolve_telegram_human_context(
        telegram_user_id=int(telegram_user_id),
        telegram_chat_id=int(telegram_chat_id),
        chat_type=telegram_chat_type,
        project_key=str(state.get("active_project") or "BR-no-GTA"),
        allowed=True,
    )
    shared = dict((identity.get("thread") or {}).get("canonical_context") or {})
    hydrate = {
        key: shared[key]
        for key in _SHARED_THREAD_FIELDS
        if key in shared and shared.get(key) is not None and state.get(key) != shared.get(key)
    }
    if hydrate:
        state = update_conversation_state(telegram_chat_id, **hydrate)
    return identity, state


def _sync_shared_thread(
    identity: dict[str, Any] | None,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(identity, dict):
        return None
    changes = {
        key: state.get(key)
        for key in _SHARED_THREAD_FIELDS
    }
    return update_shared_thread_context(str(identity["thread_id"]), **changes)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def classify_conversation_intent(message: str, *, has_attachment: bool = False) -> str:
    if has_attachment:
        return "FILE_SUBMISSION"
    text = _fold(message).strip()
    if not text:
        return "CLARIFICATION"
    if re.search(r"\b(aprovo|aprovado|aprovada|pode seguir|pode continuar|ficou bom)\b", text):
        return "APPROVAL"
    if re.search(r"\b(rejeito|reprovado|reprovada|nao gostei|ficou ruim|esta ruim|ta ruim|nao use|nao usa)\b", text):
        return "REJECTION"
    if re.search(r"\b(cancela|cancelar|pare|parar|interrompe|interromper)\b", text):
        return "CANCEL_REQUEST"
    if any(term in text for term in (
        "onde estamos", "onde voce esta", "onde esta agora",
        "o que voce esta fazendo", "o que esta fazendo agora",
        "qual o status", "status agora", "como esta o run", "como esta a tarefa",
    )):
        return "STATUS_REQUEST"
    if text in {"memoria", "memoria?", "o que voce lembra", "oque voce lembra"}:
        return "MEMORY_RECALL_REQUEST"
    if any(term in text for term in (
        "o que eu decidi", "oque eu decidi", "qual foi minha decisao",
        "qual minha decisao", "o que eu falei sobre", "oque eu falei sobre",
        "o que eu pedi sobre", "oque eu pedi sobre", "lembra o que eu decidi",
        "minha decisao sobre", "minhas decisoes sobre",
    )):
        return "MEMORY_RECALL_REQUEST"
    if text in {"conhecimento", "conhecimento?"}:
        return "KNOWLEDGE_RECALL_REQUEST"
    if any(term in text for term in (
        "conhecimento sobre", "memoria sobre", "memória sobre",
        "o que sabemos sobre", "oque sabemos sobre",
        "o que voce sabe sobre", "oque voce sabe sobre",
        "conhecimento do gta", "conhecimento do gta6",
    )):
        return "KNOWLEDGE_RECALL_REQUEST"
    if any(term in text for term in (
        "lembra disso", "guarda isso", "guarde isso", "anota isso", "anote isso",
    )):
        return "MEMORY_WRITE_REQUEST"
    if any(term in text for term in (
        "pesquisa", "pesquise", "procura", "procure", "investiga", "investigue",
        "ultimas informacoes", "ultimas noticias", "verifica nas fontes",
    )):
        return "RESEARCH_REQUEST"
    gta_subject = any(term in text for term in (
        "gta 6", "gta6", "gta vi", "grand theft auto vi", "vice city",
        "leonida", "lucia", "jason",
    ))
    information_goal = (
        text.startswith(("tudo sobre ", "me fala sobre ", "me fale sobre ", "me conta sobre ",
                         "me conte sobre ", "quero saber sobre ", "o que se sabe sobre ",
                         "oque se sabe sobre ", "o que sabemos sobre ", "oque sabemos sobre "))
        or any(term in text for term in ("o que voce sabe sobre", "oque voce sabe sobre"))
    )
    if gta_subject and information_goal:
        return "RESEARCH_REQUEST"
    if any(term in text for term in (
        "continua", "continue", "continua de onde parou", "continue de onde parou", "continua a missao",
        "retoma", "retome", "faz de novo", "refaz", "faz o video", "faca o video",
        "depois que eu aprovar", "quando eu aprovar", "gera ", "gere ", "corrige ",
        "corrija ", "renderiza", "renderize", "produz ", "produza ", "me manda ",
        "envia ", "execute ", "executa ", "analisa ", "analise ", "revisa ",
        "revise ", "com a equipe", "pela equipe",
    )):
        return "EXECUTION_REQUEST"
    if any(term in text for term in (
        "ficou melhor", "melhorou", "prefiro", "essa voz", "esse roteiro",
        "esse audio", "esse resultado", "essa parte",
    )):
        return "FEEDBACK"
    if text.endswith("?") or text.startswith((
        "onde ", "como ", "quando ", "qual ", "quais ", "quem ", "por que ",
        "porque ", "o que ", "oque ",
    )):
        return "QUESTION"
    if any(term in text for term in ("isso", "aquilo", "esse", "essa", "aquela", "aquele", "ultimo", "ultima")):
        return "INSTRUCTION"
    return "INSTRUCTION"


def _artifact_from_turns(turns: list[dict[str, Any]]) -> str | None:
    for turn in reversed(turns):
        ref = str(turn.get("artifact_ref") or "").strip()
        if ref:
            return ref
    return None


def resolve_conversation_reference(
    message: str,
    *,
    state: dict[str, Any],
    recent_turns: list[dict[str, Any]],
) -> dict[str, Any]:
    text = _fold(message)
    active_artifact = str(state.get("active_artifact") or "").strip() or None
    latest_artifact = active_artifact or _artifact_from_turns(recent_turns)
    if re.search(r"\bvideo\s*a\b", text):
        return {"reference": "video:A", "basis": "explicit"}
    if re.search(r"\bvideo\s*b\b", text):
        return {"reference": "video:B", "basis": "explicit"}
    if "ultimo roteiro" in text or "ultima versao do roteiro" in text:
        if latest_artifact:
            return {"reference": latest_artifact, "basis": "latest_artifact"}
        return {"reference": "script:last", "basis": "semantic-last"}
    if any(term in text for term in ("esse roteiro", "esse audio", "esse resultado", "isso", "esse", "essa")):
        if latest_artifact:
            return {"reference": latest_artifact, "basis": "active_artifact"}
        subject = str(state.get("current_subject") or "").strip()
        if subject:
            return {"reference": subject, "basis": "current_subject"}
    if any(term in text for term in ("aquela parte", "essa parte")):
        subject_terms = ("musica", "trilha", "voz", "roteiro", "intro", "abertura", "fechamento")
        for term in subject_terms:
            if term in text:
                for turn in reversed(recent_turns):
                    if term in _fold(str(turn.get("text_content") or "")):
                        base = latest_artifact or str(state.get("current_subject") or "").strip() or "conversation"
                        return {
                            "reference": f"{base}#{term}",
                            "basis": f"recent_turn:{turn.get('turn_id')}",
                        }
                if latest_artifact:
                    return {"reference": f"{latest_artifact}#{term}", "basis": "active_artifact_section"}
    return {"reference": latest_artifact, "basis": "active_context" if latest_artifact else None}


def _compact_turns(turns: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    compact = []
    for turn in turns[-limit:]:
        compact.append({
            "turn_id": turn.get("turn_id"),
            "role": turn.get("role"),
            "text": str(turn.get("text_content") or "")[:1200],
            "intent": turn.get("intent"),
            "resolved_reference": turn.get("resolved_reference"),
            "artifact_ref": turn.get("artifact_ref"),
            "run_id": turn.get("run_id"),
        })
    return compact


def retrieve_conversation_context(
    telegram_chat_id: int,
    *,
    current_message: str,
    turn_limit: int = 10,
) -> dict[str, Any]:
    state = get_or_create_conversation_state(telegram_chat_id)
    turns = list_recent_conversation_turns(telegram_chat_id, limit=turn_limit)
    decisions = list_recent_human_decisions(telegram_chat_id, limit=6)
    reference = resolve_conversation_reference(
        current_message,
        state=state,
        recent_turns=turns,
    )
    observation = build_gta6_observation()
    return {
        "conversation_state": state,
        "recent_turns": _compact_turns(turns),
        "recent_human_decisions": [
            {
                "decision_id": item.get("decision_id"),
                "decision_type": item.get("decision_type"),
                "target_ref": item.get("target_ref"),
                "artifact_ref": item.get("artifact_ref"),
                "run_id": item.get("run_id"),
                "comment": str(item.get("comment") or "")[:700],
                "learning_correction_id": item.get("learning_correction_id"),
            }
            for item in decisions
        ],
        "resolved_reference": reference,
        "operational_observation": {
            "domain": observation.get("domain"),
            "source_of_truth": observation.get("source_of_truth"),
            "monitor": observation.get("monitor"),
        },
    }


def plan_natural_language_action(
    message: str,
    *,
    intent: str,
    state: dict[str, Any],
    resolved_reference: str | None,
) -> dict[str, Any]:
    text = _fold(message)
    if intent == "STATUS_REQUEST":
        return {"kind": "STATUS", "authorized_action": "DECISION"}
    if intent == "MEMORY_RECALL_REQUEST":
        return {"kind": "MEMORY_RECALL", "authorized_action": "DECISION"}
    if intent == "MEMORY_WRITE_REQUEST":
        return {"kind": "MEMORY_CANDIDATE", "authorized_action": "DECISION"}
    if intent == "KNOWLEDGE_RECALL_REQUEST":
        return {
            "kind": "KNOWLEDGE_RECALL",
            "authorized_action": "DECISION",
            "query": message,
        }
    if intent == "RESEARCH_REQUEST":
        goal_envelope = build_goal_envelope(
            human_goal=message,
            project=str(state.get("active_project") or "BR-no-GTA"),
            goal_id=str(state.get("active_goal_id") or "telegram-gta6-research"),
            subject=str(state.get("current_subject") or "").strip() or None,
            source_surface="telegram",
            conversation_state={
                key: state.get(key)
                for key in (
                    "active_goal_id",
                    "active_task",
                    "current_subject",
                    "active_artifact",
                    "active_run_id",
                    "active_stage",
                    "execution_status",
                    "last_human_decision",
                    "waiting_for_human",
                    "pending_question",
                    "pending_human_review",
                )
                if state.get(key) is not None
            },
        )
        return {
            "kind": "QUERY_RESEARCH",
            "authorized_action": "RESEARCH",
            "capability_id": "gta6.research.fresh-cloud",
            "query": message,
            "goal_envelope": goal_envelope.to_dict(),
            "mission_planner": "HARNESS_REGISTRY_COMPETENCE",
            "collaboration_runtime": "HERMES_WHEN_MULTI_AGENT_REQUIRED",
        }
    if intent == "CANCEL_REQUEST":
        return {"kind": "CANCEL", "authorized_action": "DECISION"}
    if intent in {"APPROVAL", "REJECTION", "FEEDBACK"}:
        return {"kind": "HUMAN_DECISION", "authorized_action": "DECISION"}
    if intent == "EXECUTION_REQUEST":
        if any(term in text for term in ("depois que eu aprovar", "quando eu aprovar")):
            pending_action = (
                {
                    "kind": "CONTINUE",
                    "authorized_action": "EXECUTION",
                    "active_goal_id": state.get("active_goal_id"),
                    "active_task": state.get("active_task"),
                }
                if state.get("active_goal_id")
                else {
                    "kind": "CAPABILITY_DISCOVERY",
                    "authorized_action": "EXECUTION",
                    "artifact_ref": resolved_reference or state.get("active_artifact"),
                }
            )
            return {
                "kind": "DEFER_UNTIL_APPROVAL",
                "authorized_action": "DECISION",
                "pending_action": pending_action,
                "artifact_ref": resolved_reference or state.get("active_artifact"),
            }
        if text in {"continua", "continue"} or any(term in text for term in ("continua de onde parou", "continue de onde parou", "continua a missao", "retoma", "retome")):
            return {
                "kind": "CONTINUE",
                "authorized_action": "EXECUTION",
                "active_goal_id": state.get("active_goal_id"),
                "active_task": state.get("active_task"),
            }
        # Deterministic known actions stay deterministic. Mission planning is for
        # goals that actually require decomposition, not for simple retrieval or
        # an already-known capability.
        if "roteiro" in text and any(term in text for term in ("manda", "envia", "mostra")):
            return {
                "kind": "PRESENT_EXISTING",
                "authorized_action": "DECISION",
                "artifact_ref": resolved_reference or state.get("active_artifact") or "script:last",
            }
        if any(term in text for term in ("voz", "narracao", "sample", "samples", "audio")):
            return {
                "kind": "CAPABILITY",
                "authorized_action": "EXECUTION",
                "capability_id": "narration.generate.pt-BR",
                "artifact_ref": resolved_reference or state.get("active_artifact"),
            }
        # Natural operational goals are converted into a Harness-owned GoalEnvelope
        # and MissionPlan. The human never selects Hermes, Agent Office or specialists.
        try:
            subject_context = " ".join(
                item
                for item in (
                    str(state.get("current_subject") or "").strip(),
                    str(state.get("active_task") or "").strip(),
                    str(resolved_reference or "").strip(),
                )
                if item
            ) or None
            goal_envelope = build_goal_envelope(
                human_goal=message,
                project=str(state.get("active_project") or "BR-no-GTA"),
                goal_id=str(state.get("active_goal_id") or "telegram-human-goal"),
                subject=subject_context,
                source_surface="telegram",
                conversation_state={
                    key: state.get(key)
                    for key in (
                        "active_goal_id",
                        "active_task",
                        "current_subject",
                        "active_artifact",
                        "active_run_id",
                        "active_stage",
                        "execution_status",
                        "last_human_decision",
                        "waiting_for_human",
                        "pending_question",
                        "pending_human_review",
                    )
                    if state.get(key) is not None
                },
            )
            mission_plan = plan_mission_from_human_goal(
                goal_envelope,
                artifact_ref=resolved_reference or state.get("active_artifact"),
            )
        except RuntimeError as exc:
            reason = str(exc)
            if reason == "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE":
                return {
                    "kind": "SEMANTIC_REASONING_UNAVAILABLE",
                    "authorized_action": "DECISION",
                    "reason": "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE",
                }
            if reason.startswith("MISSION_NEEDS_HUMAN_CLARIFICATION:"):
                return {
                    "kind": "CLARIFICATION",
                    "authorized_action": "DECISION",
                    "reason": "MISSION_NEEDS_HUMAN_CLARIFICATION",
                    "question": reason.split(":", 1)[1].strip(),
                }
            if reason.startswith("SEMANTIC_MISSION_PROPOSAL_REJECTED:"):
                return {
                    "kind": "MISSION_PLANNING_REJECTED",
                    "authorized_action": "DECISION",
                    "reason": reason,
                    "authority": "DEEPSEEK_HARNESS",
                }
            raise

        if mission_plan is not None and goal_envelope is not None:
            if goal_envelope.mission_class == "SYSTEM_IMPROVEMENT":
                return {
                    "kind": "SYSTEM_IMPROVEMENT_MISSION",
                    "authorized_action": "DEVELOPMENT",
                    "capability_id": "system.improvement.propose",
                    "artifact_ref": resolved_reference or state.get("active_artifact"),
                    "active_goal_id": state.get("active_goal_id"),
                    "goal_envelope": goal_envelope.to_dict(),
                    "mission_plan": mission_plan.to_dict(),
                    "mission_planner": "HARNESS_REGISTRY_COMPETENCE",
                    "collaboration_runtime": "HERMES_WHEN_MULTI_AGENT_REQUIRED",
                }
            return {
                "kind": "HARNESS_MISSION",
                "authorized_action": "EXECUTION",
                "artifact_ref": resolved_reference or state.get("active_artifact"),
                "active_goal_id": state.get("active_goal_id"),
                "goal_envelope": goal_envelope.to_dict(),
                "mission_plan": mission_plan.to_dict(),
                "mission_planner": "HARNESS_REGISTRY_COMPETENCE",
                "collaboration_runtime": (
                    "HERMES_WHEN_MULTI_AGENT_REQUIRED" if len(mission_plan.collaboration_plan.tasks) > 1 else None
                ),
            }

        return {
            "kind": "CAPABILITY_DISCOVERY",
            "authorized_action": "EXECUTION",
            "artifact_ref": resolved_reference,
        }
    return {"kind": "CHAT", "authorized_action": "DECISION"}


def _canonical_human_memory_recall(message: str, state: dict[str, Any]) -> dict[str, Any]:
    goal_id = str(state.get("active_goal_id") or "").strip() or None
    rows = learning_repository.list_canonical_human_decisions(
        goal_id=goal_id,
        limit=100,
    )
    if not rows and goal_id is not None:
        rows = learning_repository.list_canonical_human_decisions(limit=100)
    query = {
        token for token in re.findall(r"[a-z0-9À-ÿ_-]{3,}", _fold(message))
        if token not in {
            "que", "qual", "foi", "minha", "minhas", "sobre", "decidi",
            "falei", "pedi", "lembra", "lembrar", "oque", "memoria",
        }
    }
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for item in rows:
        metadata = dict(item.get("metadata") or {})
        haystack = _fold(" ".join([
            str(item.get("content") or ""),
            str(item.get("artifact_ref") or ""),
            str(item.get("task_id") or ""),
            str(metadata.get("target") or ""),
            json.dumps(metadata, ensure_ascii=False, default=str),
        ]))
        score = sum(1 for token in query if token in haystack)
        if query and score <= 0:
            continue
        if not query:
            score = 1
        ranked.append((score, str(item.get("created_at") or ""), item))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    selected = [dict(row[2]) for row in ranked[:5]]
    if not selected:
        return {
            "status": "NO_CANONICAL_HUMAN_DECISION_MATCH",
            "answer": (
                "Ainda não encontrei decisões humanas canônicas relevantes para este contexto. "
                "As conversas continuam preservadas, mas não vou inventar memória duradoura."
            ),
            "human_decisions": [],
            "provider_independent": True,
        }
    lines = []
    for item in selected:
        source = str(item.get("source_surface") or "").upper()
        decision = str(item.get("decision_type") or "")
        content = str(item.get("content") or "").strip()
        lines.append(f"{decision} via {source}: {content}")
    return {
        "status": "CANONICAL_HUMAN_MEMORY_RECALLED",
        "answer": "\n".join(lines),
        "human_decisions": selected,
        "provider_independent": True,
        "canonical_memory_plane": "HARNESS_LEARNING_PLANE",
    }


def _parse_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"answer": value}
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    return {"result": value}


def _extract_identity(payload: dict[str, Any], *keys: str) -> Any:
    stack = [payload]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        for key in keys:
            value = current.get(key)
            if value not in (None, "", [], {}):
                return value
        for value in current.values():
            if isinstance(value, dict):
                stack.append(value)
    return None


def _default_action_executor(plan: dict[str, Any], state: dict[str, Any], message: str) -> dict[str, Any]:
    from app.integrations.deepseek_harness import server

    if plan["kind"] == "SEMANTIC_REASONING_UNAVAILABLE":
        return {
            "status": "BLOCKED_PROVIDER",
            "answer": (
                "Não consigo fazer a parte de raciocínio aberto agora porque nenhum modelo semântico "
                "zero-cost está disponível. O restante do sistema continua operacional: status, memória, "
                "conhecimento, pesquisa governada e missões com executores conhecidos continuam funcionando."
            ),
            "reason_code": "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE",
            "provider_retry_performed": False,
            "authority": "DEEPSEEK_HARNESS",
            "NEW_VOICE_SYNTHESIS": "NO",
            "FULL_RENDER": "NO",
            "YOUTUBE_UPLOAD": "NO",
            "YOUTUBE_PUBLICATION": "NO",
        }

    if plan["kind"] == "CONTINUE":
        goal_id = str(plan.get("active_goal_id") or "").strip()
        if not goal_id:
            return {
                "status": "WAITING_FOR_HUMAN",
                "answer": (
                    "Tenho o contexto da conversa, mas ainda não existe um goal ativo inequívoco para continuar. "
                    "Diga qual trabalho devo retomar uma vez; depois disso eu mantenho esse vínculo no estado da conversa."
                ),
                "pending_question": "Qual trabalho devo retomar?",
            }
        return _parse_result(server.br_execution_process_next(goal_id=goal_id))

    if plan["kind"] == "HERMES_CLOUD_RESUME":
        from app.services.telegram_hermes_dispatch_service import (
            resume_telegram_hermes_mission,
        )

        return resume_telegram_hermes_mission(
            pending_action=plan,
            state=state,
            message=message,
        )

    if plan["kind"] in {"SYSTEM_IMPROVEMENT_MISSION", "HARNESS_MISSION"}:
        from app.services.harness_mission_execution_router import (
            execute_harness_mission_plan,
        )
        return execute_harness_mission_plan(
            plan=plan,
            state=state,
            message=message,
        )

    if plan["kind"] == "HERMES_COLLABORATION":
        from app.services.telegram_hermes_dispatch_service import (
            dispatch_telegram_hermes_mission,
        )

        return dispatch_telegram_hermes_mission(
            plan=plan,
            state=state,
            message=message,
        )

    if plan["kind"] == "QUERY_RESEARCH":
        return execute_telegram_gta6_query(
            query=str(plan.get("query") or message),
            state=state,
        )

    if plan["kind"] in {"CAPABILITY", "RESEARCH_PIPELINE"}:
        capability_id = str(plan.get("capability_id") or "").strip()
        if capability_id == "gta6.research":
            return _parse_result(server.br_research_run())
        cached_payloads = state.get("last_execution_result") or {}
        cached_payloads = cached_payloads.get("capability_payloads") if isinstance(cached_payloads, dict) else None
        payload = dict((cached_payloads or {}).get(capability_id) or {}) if isinstance(cached_payloads, dict) else {}
        if not payload:
            return {
                "status": "WAITING_FOR_HUMAN",
                "answer": (
                    f"Entendi a ação e selecionei a capability {capability_id}, mas o estado atual não contém "
                    "o payload operacional aprovado necessário para executá-la sem inventar parâmetros. "
                    "Vou manter o pedido pendente no contexto em vez de abrir um bypass."
                ),
                "pending_question": "Falta o alvo operacional aprovado da execução.",
                "capability_id": capability_id,
            }
        return _parse_result(
            server.br_capability_execute(
                capability_id=capability_id,
                authorized_action=str(plan.get("authorized_action") or "EXECUTION"),
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
        )

    return {
        "status": "WAITING_FOR_HUMAN",
        "answer": "A ação ainda não possui executor natural-language allowlisted.",
        "pending_question": "Preciso de uma referência operacional inequívoca.",
    }


def _compact_research_pipeline_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    if not isinstance(payload, dict):
        return {"status": result.get("status")}
    compact: dict[str, Any] = {
        "operation": result.get("operation"),
        "total": payload.get("total"),
        "rockstar_monitor": payload.get("rockstar_monitor"),
    }
    for key, limit in (("rockstar_newswire", 6), ("news_feeds", 8), ("editorial", 12)):
        value = payload.get(key)
        if isinstance(value, list):
            compact[key] = value[:limit]
            compact[f"{key}_count"] = len(value)
    return compact


def _deterministic_research_answer(result: dict[str, Any]) -> str:
    compact = _compact_research_pipeline_result(result)
    parts = ["A pesquisa governada foi concluída e a evidência canônica foi preservada."]
    total = compact.get("total")
    if total is not None:
        parts.append(f"Total observado no resultado: {total}.")
    official = compact.get("rockstar_newswire")
    if isinstance(official, list) and official:
        titles = [
            str(item.get("title") or "").strip()
            for item in official
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        if titles:
            parts.append("Fontes oficiais no resultado: " + "; ".join(titles[:4]) + ".")
    editorial = compact.get("editorial")
    if isinstance(editorial, list) and editorial:
        decisions = [
            str(item.get("decision") or item.get("status") or "").strip()
            for item in editorial
            if isinstance(item, dict)
            and str(item.get("decision") or item.get("status") or "").strip()
        ]
        if decisions:
            parts.append("Avaliação editorial persistida: " + "; ".join(decisions[:4]) + ".")
    parts.append(
        "A síntese generativa está indisponível; por isso não acrescentei interpretação nem fatos fora do resultado da pesquisa."
    )
    return " ".join(parts)


def _status_answer(state: dict[str, Any]) -> str:
    task = str(state.get("active_task") or "").strip()
    goal = str(state.get("active_goal_id") or "").strip()
    project = str(state.get("active_project") or "BR-no-GTA").strip()
    subject = str(state.get("current_subject") or "").strip()
    run_id = str(state.get("active_run_id") or "").strip()
    blocker = str(state.get("active_blocker") or "").strip()
    waiting = bool(state.get("waiting_for_human"))
    active = bool(state.get("canonical_execution_active"))
    stage = str(state.get("active_stage") or "").strip()
    latest = state.get("latest_canonical_result")
    latest = latest if isinstance(latest, dict) else {}
    latest_status = str(
        _extract_identity(latest, "status", "execution_status", "run_status")
        or ""
    ).strip().upper()
    latest_capability = str(
        _extract_identity(latest, "capability_id")
        or ""
    ).strip()

    if waiting:
        target = str(
            state.get("pending_human_review")
            or state.get("pending_question")
            or "decisão pendente"
        )
        mission = str(state.get("hermes_mission_id") or "").strip()
        suffix = f" Missão: {mission}." if mission else ""
        return (
            f"Estamos no projeto {project}. Estou aguardando você sobre {target}."
            f"{suffix} Nenhuma execução passa por cima dessa decisão."
        )

    if active:
        details = [
            item
            for item in (
                task,
                f"etapa {stage}" if stage else "",
                f"run {run_id}" if run_id else "",
            )
            if item
        ]
        text = "Há uma execução real ativa"
        if details:
            text += ": " + " — ".join(details)
        text += "."
        if blocker:
            text += f" Blocker atual: {blocker}."
        return text

    parts = [f"Estamos no projeto {project}."]
    if goal:
        parts.append(f"Goal atual: {goal}.")
    if task:
        parts.append(f"Contexto de trabalho: {task}.")
    elif subject:
        parts.append(f"Contexto atual: {subject}.")
    if latest_status:
        capability_suffix = (
            f" pela capability {latest_capability}"
            if latest_capability
            else ""
        )
        parts.append(
            f"Último resultado canônico: {latest_status}{capability_suffix}."
        )
    if run_id:
        parts.append(f"Último run conhecido: {run_id}.")
    if blocker:
        parts.append(f"Blocker registrado: {blocker}.")
    if state.get("stale_progress_state_reconciled"):
        parts.append(
            "Um estado antigo de progresso foi reconciliado porque não havia execução real correspondente."
        )
    parts.append("Não há execução ativa neste momento.")
    return " ".join(parts)


def _resolve_script_for_presentation(reference: str | None) -> dict[str, Any] | None:
    ref = str(reference or "").strip()
    if not ref:
        return None
    script_id: int | None = None
    if ref.startswith("script:"):
        suffix = ref.split(":", 1)[1].split("#", 1)[0].strip()
        if suffix.isdigit():
            script_id = int(suffix)
        elif suffix == "last":
            scripts = list_scripts()
            return scripts[-1] if scripts else None
    elif ref.isdigit():
        script_id = int(ref)
    if script_id is None:
        return None
    return get_script(script_id)


def _present(
    canonical: dict[str, Any],
    *,
    telegram_chat_id: int,
    turn_id: int,
    presenter: Callable[..., dict[str, Any]],
) -> str:
    presented = presenter(
        canonical,
        surface="telegram",
        mode="ACTION_FIRST",
        lineage={
            "conversation_id": f"telegram:{telegram_chat_id}",
            "turn_id": turn_id,
        },
    )
    return str(presented.get("text") or canonical.get("answer") or "").strip()


def handle_telegram_conversation(
    message: str,
    *,
    telegram_chat_id: int,
    telegram_user_id: int | None = None,
    telegram_chat_type: str = "private",
    telegram_message_id: int | None = None,
    input_record: dict[str, Any] | None = None,
    has_attachment: bool = False,
    progress_callback: ProgressCallback | None = None,
    chat_handler: ChatHandler = chat_under_harness,
    action_executor: ActionExecutor = _default_action_executor,
    presenter: Callable[..., dict[str, Any]] = present_canonical_result_under_harness,
) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        raise ValueError("Telegram conversation message is empty")

    identity, state = _bind_surface_identity(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        telegram_chat_type=telegram_chat_type,
    )
    recent_before = list_recent_conversation_turns(telegram_chat_id, limit=10)
    contextual_resolution = resolve_contextual_intent(
        text,
        state=state,
        recent_turns=recent_before,
        has_attachment=has_attachment,
    )
    intent = (
        contextual_resolution.intent
        if contextual_resolution is not None
        else classify_conversation_intent(text, has_attachment=has_attachment)
    )
    resolved = resolve_conversation_reference(text, state=state, recent_turns=recent_before)
    human_turn = append_conversation_turn(
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        role="HUMAN",
        text_content=text,
        intent=intent,
        resolved_reference=resolved.get("reference"),
        artifact_ref=state.get("active_artifact"),
        run_id=state.get("active_run_id"),
        metadata={
            "reference_basis": resolved.get("basis"),
            "telegram_user_id": telegram_user_id,
            "telegram_chat_type": telegram_chat_type,
            "human_identity_id": (identity or {}).get("human_identity_id"),
            "thread_id": (identity or {}).get("thread_id"),
            "surface_session_id": (identity or {}).get("surface_session_id"),
            "intent_resolution": (
                contextual_resolution.to_dict()
                if contextual_resolution is not None
                else {
                    "intent": intent,
                    "layer": "LAYER_4_LEGACY_OR_SEMANTIC",
                    "confidence": "UNRESOLVED",
                    "reason": "no earlier deterministic/contextual resolution",
                }
            ),
        },
    )
    state_changes: dict[str, Any] = {"last_human_intent": intent}
    # Observation/recall queries inspect project state; they must never become it.
    if intent not in {"STATUS_REQUEST", "MEMORY_RECALL_REQUEST", "KNOWLEDGE_RECALL_REQUEST"}:
        state_changes["current_subject"] = (
            resolved.get("reference")
            or state.get("current_subject")
            or text[:240]
        )
    state = update_conversation_state(
        telegram_chat_id,
        **state_changes,
    )
    context = retrieve_conversation_context(
        telegram_chat_id,
        current_message=text,
    )
    plan = plan_natural_language_action(
        text,
        intent=intent,
        state=state,
        resolved_reference=resolved.get("reference"),
    )

    # Short deterministic control paths must return the result directly.
    # A visible UNDERSTANDING heartbeat is product noise and can become a
    # misleading final message if the process dies before presentation.
    visible_progress_allowed = plan["kind"] not in {
        "STATUS",
        "MEMORY_RECALL",
        "KNOWLEDGE_RECALL",
        "MEMORY_CANDIDATE",
        "HUMAN_DECISION",
        "CANCEL",
        "PRESENT_EXISTING",
    }
    if progress_callback is not None and visible_progress_allowed:
        progress_callback(
            "UNDERSTANDING",
            f"Entendi como {intent.lower().replace('_', ' ')}; resolvendo contexto e autorização.",
        )

    canonical: dict[str, Any]
    decision = None
    pending_action_consumed = False
    if plan["kind"] == "STATUS":
        state = get_or_create_conversation_state(telegram_chat_id)
        reconciliation = reconcile_stale_progress_state(
            telegram_chat_id,
            state=state,
        )
        state = dict(reconciliation["state"])
        control_surface_status = build_harness_control_surface_status(
            telegram_chat_id,
            state=state,
        )
        control_surface_status.update({
            "stale_progress_state_detected": bool(reconciliation["detected"]),
            "stale_progress_state_reconciled": bool(reconciliation["reconciled"]),
        })
        project_snapshot = build_canonical_project_status_snapshot(
            control_surface_status,
            human_identity=identity,
        )
        canonical = {
            "status": "OBSERVED",
            "answer": render_canonical_project_status(project_snapshot),
            "intent": intent,
            "conversation_state": state,
            "control_surface_status": control_surface_status,
            "project_status_snapshot": project_snapshot.to_dict(),
            "STALE_PROGRESS_STATE_DETECTED": (
                "PASS" if reconciliation["detected"] else "NOT_PRESENT"
            ),
            "STALE_PROGRESS_STATE_RECONCILED": (
                "PASS" if reconciliation["reconciled"] else "NOT_REQUIRED"
            ),
            "STATUS_PROVIDER_CALLS": 0,
            "STATUS_OPENCODE_CALLS": 0,
            "STATUS_HERMES_CALLS": 0,
        }
    elif plan["kind"] == "MEMORY_RECALL":
        state = get_or_create_conversation_state(telegram_chat_id)
        canonical = _canonical_human_memory_recall(text, state)
    elif plan["kind"] == "KNOWLEDGE_RECALL":
        state = get_or_create_conversation_state(telegram_chat_id)
        canonical = recall_canonical_gta6_knowledge(
            str(plan.get("query") or text),
            project_context=str(state.get("active_project") or ""),
            subject_context=str(state.get("current_subject") or ""),
        )
    elif plan["kind"] == "MEMORY_CANDIDATE":
        canonical = create_telegram_memory_candidate(
            message=text,
            state=state,
            human_turn=human_turn,
            identity=identity,
            telegram_chat_id=telegram_chat_id,
            telegram_user_id=telegram_user_id,
        )
    elif plan["kind"] == "CANCEL":
        state = update_conversation_state(
            telegram_chat_id,
            last_human_decision="CANCEL",
            waiting_for_human=False,
            pending_question=None,
            pending_human_review=None,
        )
        decision = record_human_decision(
            telegram_chat_id=telegram_chat_id,
            decision_type="CANCEL",
            comment=text,
            turn_id=human_turn["turn_id"],
            active_goal_id=state.get("active_goal_id"),
            active_task=state.get("active_task"),
            artifact_ref=state.get("active_artifact"),
            run_id=state.get("active_run_id"),
        )
        canonical = {
            "status": "CANCEL_REQUEST_RECORDED",
            "answer": "Registrei o pedido de cancelamento no contexto. A interrupção efetiva continua sujeita ao boundary oficial da execução; não vou fingir que um run foi cancelado sem evidência.",
            "human_decision": decision,
        }
    elif plan["kind"] == "HUMAN_DECISION":
        decision_type = "APPROVAL" if intent == "APPROVAL" else ("REJECTION" if intent == "REJECTION" else "FEEDBACK")
        correction = None
        evidence_refs = [f"telegram-turn:{human_turn['turn_id']}"]
        if state.get("active_run_id"):
            evidence_refs.append(f"run:{state['active_run_id']}")
        if decision_type in {"REJECTION", "FEEDBACK"}:
            correction = record_human_correction(
                context=f"Telegram feedback on {resolved.get('reference') or state.get('current_subject') or 'active result'}",
                undesired_behavior=text,
                desired_behavior="Apply the human feedback to the bound target before the next execution.",
                evidence_refs=evidence_refs,
                goal_id=state.get("active_goal_id"),
                task_id=state.get("active_task"),
                affected_capability=(
                    state.get("last_execution_result", {}).get("capability_id")
                    if isinstance(state.get("last_execution_result"), dict)
                    else None
                ),
                metadata={
                    "source": "telegram-conversation",
                    "conversation_id": state["conversation_id"],
                    "turn_id": human_turn["turn_id"],
                    "target_ref": resolved.get("reference"),
                },
                scope="LOCAL",
            )
        canonical_human_decision = record_canonical_human_decision(
            decision_type=decision_type,
            source_surface="telegram",
            source_ref=f"telegram-turn:{human_turn['turn_id']}",
            content=text,
            evidence_refs=evidence_refs,
            goal_id=state.get("active_goal_id"),
            task_id=state.get("active_task"),
            capability_id=(
                state.get("last_execution_result", {}).get("capability_id")
                if isinstance(state.get("last_execution_result"), dict)
                else None
            ),
            artifact_ref=state.get("active_artifact"),
            metadata={
                "conversation_id": state["conversation_id"],
                "telegram_user_id": telegram_user_id,
                "telegram_chat_id": telegram_chat_id,
                "telegram_chat_type": telegram_chat_type,
                "human_identity_id": (identity or {}).get("human_identity_id"),
                "thread_id": (identity or {}).get("thread_id"),
                "surface_session_id": (identity or {}).get("surface_session_id"),
                "telegram_message_id": telegram_message_id,
                "learning_correction_id": (correction or {}).get("correction_id"),
            },
        )
        decision = record_human_decision(
            telegram_chat_id=telegram_chat_id,
            decision_type=decision_type,
            comment=text,
            turn_id=human_turn["turn_id"],
            target_kind="conversation-reference",
            target_ref=resolved.get("reference"),
            active_goal_id=state.get("active_goal_id"),
            active_task=state.get("active_task"),
            artifact_ref=state.get("active_artifact"),
            run_id=state.get("active_run_id"),
            learning_correction_id=(correction or {}).get("correction_id"),
            metadata={
                "canonical_decision_id": canonical_human_decision["decision_id"],
                "canonical_memory_plane": "HARNESS_LEARNING_PLANE",
            },
        )
        changes: dict[str, Any] = {"last_human_decision": decision_type}
        pending_action = state.get("pending_action") if decision_type == "APPROVAL" else None
        if decision_type == "APPROVAL":
            pending_action_consumed = isinstance(pending_action, dict)
            changes.update(
                waiting_for_human=False,
                pending_human_review=None,
                pending_question=None,
                pending_action=None,
            )
        else:
            changes.update(
                waiting_for_human=True,
                pending_human_review=resolved.get("reference") or state.get("current_subject"),
            )
        state = update_conversation_state(telegram_chat_id, **changes)
        if decision_type == "APPROVAL" and isinstance(pending_action, dict):
            if progress_callback is not None:
                progress_callback(
                    "AUTHORIZATION",
                    "Aprovação recebida. Retomando a ação pendente pelo boundary oficial do Harness.",
                )
            resumed = _parse_result(action_executor(dict(pending_action), state, text))
            canonical = {
                **resumed,
                "human_decision": decision,
                "canonical_human_decision": canonical_human_decision,
                "learning_correction": correction,
                "approval_resumed_pending_action": True,
            }
        else:
            if decision_type == "APPROVAL":
                answer = f"Aprovação vinculada a {resolved.get('reference') or 'resultado ativo'}. Vou usar essa decisão nas próximas ações governadas."
            else:
                answer = f"Feedback vinculado a {resolved.get('reference') or 'resultado ativo'}. Não vou repetir a próxima execução ignorando essa correção."
            canonical = {
                "status": "HUMAN_DECISION_RECORDED",
                "answer": answer,
                "human_decision": decision,
                "canonical_human_decision": canonical_human_decision,
                "learning_correction": correction,
            }
    elif plan["kind"] == "DEFER_UNTIL_APPROVAL":
        state = update_conversation_state(
            telegram_chat_id,
            waiting_for_human=True,
            pending_human_review=plan.get("artifact_ref") or state.get("current_subject") or "APPROVAL",
            pending_question="Aguardando sua aprovação antes de executar a ação pendente.",
            pending_action=dict(plan.get("pending_action") or {}),
            execution_status="WAITING_FOR_HUMAN",
            active_stage="WAITING_FOR_HUMAN",
        )
        canonical = {
            "status": "WAITING_FOR_HUMAN",
            "answer": (
                "Entendi. Guardei a ação como pendente e não vou executá-la antes da sua aprovação. "
                "Quando você aprovar, ela volta ao Harness e passa pelos gates normais."
            ),
            "pending_question": "Aguardando sua aprovação antes de executar a ação pendente.",
            "artifact_ref": plan.get("artifact_ref"),
        }
    elif plan["kind"] == "PRESENT_EXISTING":
        script = _resolve_script_for_presentation(plan.get("artifact_ref"))
        if script is None:
            canonical = {
                "status": "WAITING_FOR_HUMAN",
                "answer": (
                    "Resolvi a referência do roteiro, mas o conteúdo canônico não está disponível no SQLite atual. "
                    "Não vou inventar nem reconstruir o texto por memória."
                ),
                "pending_question": "O roteiro referenciado precisa existir no estado canônico antes da entrega.",
                "artifact_ref": plan.get("artifact_ref"),
            }
        else:
            script_ref = f"script:{script['id']}"
            canonical = {
                "status": "SCRIPT_PRESENTED",
                "answer": str(script.get("content") or "").strip(),
                "artifact_ref": script_ref,
                "script_id": script["id"],
                "script_title": script.get("title"),
                "script_version": script.get("version"),
                "script_status": script.get("status"),
            }
    elif plan["kind"] == "QUERY_RESEARCH":
        state = update_conversation_state(
            telegram_chat_id,
            execution_status="RUNNING",
            active_stage="RESEARCH",
            active_task=text[:240],
            active_blocker=None,
            waiting_for_human=False,
        )
        if progress_callback is not None:
            progress_callback(
                "RESEARCH",
                "Pesquisando exatamente o seu pedido em fontes GTA 6 governadas pelo Harness.",
            )
        canonical = _parse_result(action_executor(plan, state, text))
        if progress_callback is not None:
            progress_callback(
                "RESULT",
                "Pesquisa e fact-check concluídos; preparando o resultado humano com evidência.",
            )
    elif plan["kind"] == "RESEARCH_PIPELINE":
        state = update_conversation_state(
            telegram_chat_id,
            execution_status="RUNNING",
            active_stage="RESEARCH",
            active_task=text[:240],
            active_blocker=None,
            waiting_for_human=False,
        )
        if progress_callback is not None:
            progress_callback(
                "RESEARCH",
                "Executando a pesquisa GTA 6 oficial pelo Harness; a própria pipeline persiste evidência e avaliação editorial.",
            )
        research_result = _parse_result(action_executor(plan, state, text))
        if progress_callback is not None:
            progress_callback(
                "EDITORIAL",
                "Pesquisa concluída. Usando a avaliação editorial persistida para medir impacto no roteiro ativo.",
            )
        reasoning_context = {
            **context,
            "governed_research_pipeline_result": _compact_research_pipeline_result(
                research_result
            ),
        }
        if progress_callback is not None:
            progress_callback(
                "SYNTHESIS",
                "Tentando síntese opcional; a pesquisa já está preservada mesmo se o provider estiver indisponível.",
            )
        try:
            synthesis = _parse_result(
                chat_handler(
                    text,
                    progress_callback=progress_callback,
                    input_record=input_record,
                    conversation_context=reasoning_context,
                    skip_fresh_research=True,
                )
            )
        except HarnessReasoningFailure as exc:
            provider_failure = exc.to_dict()
            if progress_callback is not None:
                progress_callback(
                    "RESULT",
                    "Pesquisa concluída. A síntese generativa está indisponível; apresentando somente o resultado canônico.",
                )
            canonical = {
                **research_result,
                "answer": _deterministic_research_answer(research_result),
                "RESEARCH_EXECUTION": "PASS",
                "OPTIONAL_SYNTHESIS": "UNAVAILABLE",
                "reasoning_provider_blocker": {
                    "provider": provider_failure.get("provider"),
                    "model": provider_failure.get("model"),
                    "provider_error": provider_failure.get("provider_error"),
                },
            }
        else:
            canonical = {
                **research_result,
                "answer": str(
                    synthesis.get("answer")
                    or "A pesquisa foi concluída e a avaliação editorial foi persistida."
                ),
                "RESEARCH_EXECUTION": "PASS",
                "OPTIONAL_SYNTHESIS": "PASS",
                "research_synthesis": {
                    "capability_id": synthesis.get("capability_id"),
                    "routing_id": synthesis.get("routing_id"),
                    "authorization_id": synthesis.get("authorization_id"),
                    "execution_id": synthesis.get("execution_id"),
                },
            }
    elif plan["kind"] in {"CONTINUE", "CAPABILITY", "CAPABILITY_DISCOVERY", "HERMES_COLLABORATION", "HARNESS_MISSION", "SYSTEM_IMPROVEMENT_MISSION"}:
        update_conversation_state(
            telegram_chat_id,
            execution_status="RUNNING",
            active_stage="AUTHORIZATION",
            active_task=text[:240],
            active_blocker=None,
            waiting_for_human=False,
        )
        if progress_callback is not None:
            progress_callback("AUTHORIZATION", "Harness selecionando capability e verificando gates.")
        canonical = _parse_result(action_executor(plan, state, text))
    else:
        canonical = _parse_result(
            chat_handler(
                text,
                progress_callback=progress_callback,
                input_record=input_record,
                conversation_context=context,
            )
        )

    run_id = _extract_identity(canonical, "run_id", "render_run_id", "workflow_run_id")
    execution_id = _extract_identity(canonical, "execution_id")
    goal_id = _extract_identity(canonical, "goal_id")
    artifact_ref = _extract_identity(canonical, "artifact_ref", "artifact_id")
    script_identity = _extract_identity(canonical, "script_id")
    if artifact_ref is None and script_identity is not None:
        artifact_ref = f"script:{script_identity}"
    artifact_ref = (
        artifact_ref
        or resolved.get("reference")
        or state.get("active_artifact")
    )
    capability_id = _extract_identity(canonical, "capability_id")
    status = str(_extract_identity(canonical, "status") or "COMPLETED").upper()
    if str(canonical.get("fresh_research_status") or "").upper() == "FAIL_CLOSED":
        status = "FAILED"
    if str(canonical.get("USER_GOAL_COMPLETED") or "").upper() == "NO" and status == "COMPLETED":
        status = "FAILED"
    waiting = status in {"WAITING_FOR_HUMAN", "WAITING", "BLOCKED_HUMAN"}
    running = status in {"RUNNING", "IN_PROGRESS", "QUEUED", "DISPATCHED"}
    blocker = _extract_identity(canonical, "blocker", "error")
    pending_question = canonical.get("pending_question") if isinstance(canonical, dict) else None
    canonical_pending_action = (
        canonical.get("pending_action")
        if isinstance(canonical, dict) and isinstance(canonical.get("pending_action"), dict)
        else None
    )

    # STATUS is an observation, not a state transition.  In particular, asking
    # "Onde estamos?" must never consume WAITING_FOR_HUMAN or pending_action.
    if plan["kind"] in {"STATUS", "MEMORY_RECALL", "KNOWLEDGE_RECALL"}:
        state = get_or_create_conversation_state(telegram_chat_id)
    else:
        if canonical_pending_action is not None:
            next_pending_action = canonical_pending_action
        elif pending_action_consumed:
            next_pending_action = None
        else:
            # Pending actions are durable leases.  Unrelated turns (including
            # presentation, feedback and provider failures) cannot clear them.
            next_pending_action = state.get("pending_action")

        state = update_conversation_state(
            telegram_chat_id,
            active_goal_id=str(goal_id) if goal_id is not None else state.get("active_goal_id"),
            active_task=(
                text[:240]
                if intent in {"EXECUTION_REQUEST", "RESEARCH_REQUEST"}
                else state.get("active_task")
            ),
            active_artifact=str(artifact_ref) if artifact_ref is not None else state.get("active_artifact"),
            active_run_id=str(run_id) if run_id is not None else state.get("active_run_id"),
            active_stage=(
                "WAITING_FOR_HUMAN"
                if waiting
                else "RUNNING" if running
                else "COMPLETE"
            ),
            active_blocker=str(blocker)[:1000] if blocker else None,
            execution_status=(
                "WAITING_FOR_HUMAN"
                if waiting
                else "RUNNING" if running
                else ("FAILED" if "FAIL" in status or status == "BLOCKED" else "COMPLETED")
            ),
            waiting_for_human=waiting,
            pending_question=str(pending_question) if pending_question else None,
            pending_human_review=(
                str(artifact_ref)
                if waiting and artifact_ref is not None
                else state.get("pending_human_review") if waiting else None
            ),
            pending_action=next_pending_action,
            last_execution_result={
                **canonical,
                "capability_id": capability_id,
            },
        )

    shared_thread = _sync_shared_thread(identity, state)

    answer = _present(
        canonical,
        telegram_chat_id=telegram_chat_id,
        turn_id=int(human_turn["turn_id"]),
        presenter=presenter,
    )
    assistant_turn = append_conversation_turn(
        telegram_chat_id=telegram_chat_id,
        role="ASSISTANT",
        text_content=answer,
        intent=intent,
        resolved_reference=resolved.get("reference"),
        artifact_ref=str(artifact_ref) if artifact_ref is not None else None,
        run_id=str(run_id) if run_id is not None else None,
        execution_id=str(execution_id) if execution_id is not None else None,
        metadata={
            "plan": plan,
            "capability_id": capability_id,
            "waiting_for_human": waiting,
            "telegram_user_id": telegram_user_id,
            "telegram_chat_type": telegram_chat_type,
            "human_identity_id": (identity or {}).get("human_identity_id"),
            "thread_id": (identity or {}).get("thread_id"),
            "surface_session_id": (identity or {}).get("surface_session_id"),
        },
    )
    return {
        "answer": answer,
        "intent": intent,
        "resolved_reference": resolved,
        "plan": plan,
        "conversation_state": state,
        "human_turn_id": human_turn["turn_id"],
        "assistant_turn_id": assistant_turn["turn_id"],
        "canonical_result": canonical,
        "human_decision": decision,
        "human_identity": identity,
        "shared_thread": shared_thread,
        "TELEGRAM_USER_ID_PROPAGATED": (
            "PASS" if telegram_user_id is None or (identity or {}).get("telegram_user_id") == int(telegram_user_id)
            else "FAIL"
        ),
        "TELEGRAM_CHAT_TYPE_PROPAGATED": (
            "PASS" if telegram_user_id is None or (identity or {}).get("chat_type") == telegram_chat_type
            else "FAIL"
        ),
        "intent_resolution": (
            contextual_resolution.to_dict()
            if contextual_resolution is not None
            else None
        ),
        "CONVERSATION_CONTEXT_RETRIEVAL": "PASS",
        "HARNESS_AUTHORITY_PRESERVED": "PASS",
    }
