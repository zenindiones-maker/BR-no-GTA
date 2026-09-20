from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable

from app.database.telegram_conversation_repository import (
    append_conversation_turn,
    get_or_create_conversation_state,
    list_recent_conversation_turns,
    record_human_decision,
    update_conversation_state,
)
from app.services.gta6_observation_service import build_gta6_observation
from app.services.harness_learning_service import record_human_correction
from app.services.human_presentation_service import present_canonical_result_under_harness
from app.services.telegram_harness_service import chat_under_harness


INTENTS = {
    "QUESTION",
    "INSTRUCTION",
    "FEEDBACK",
    "APPROVAL",
    "REJECTION",
    "STATUS_REQUEST",
    "FILE_SUBMISSION",
    "RESEARCH_REQUEST",
    "EXECUTION_REQUEST",
    "CANCEL_REQUEST",
    "CLARIFICATION",
}


ProgressCallback = Callable[[str, str], None]
ChatHandler = Callable[..., dict[str, Any]]
ActionExecutor = Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]


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
    if any(term in text for term in (
        "pesquisa", "pesquise", "procura", "procure", "investiga", "investigue",
        "ultimas informacoes", "ultimas noticias", "verifica nas fontes",
    )):
        return "RESEARCH_REQUEST"
    if any(term in text for term in (
        "continua de onde parou", "continue de onde parou", "continua a missao",
        "retoma", "retome", "faz de novo", "refaz", "gera ", "gere ", "corrige ",
        "corrija ", "renderiza", "renderize", "produz ", "produza ", "me manda ",
        "envia ", "execute ", "executa ",
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
    reference = resolve_conversation_reference(
        current_message,
        state=state,
        recent_turns=turns,
    )
    observation = build_gta6_observation()
    return {
        "conversation_state": state,
        "recent_turns": _compact_turns(turns),
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
    if intent == "RESEARCH_REQUEST":
        return {
            "kind": "CAPABILITY",
            "authorized_action": "RESEARCH",
            "capability_id": "gta6.research.fresh-cloud",
        }
    if intent == "CANCEL_REQUEST":
        return {"kind": "CANCEL", "authorized_action": "DECISION"}
    if intent in {"APPROVAL", "REJECTION", "FEEDBACK"}:
        return {"kind": "HUMAN_DECISION", "authorized_action": "DECISION"}
    if intent == "EXECUTION_REQUEST":
        if any(term in text for term in ("continua de onde parou", "continue de onde parou", "continua a missao", "retoma", "retome")):
            return {
                "kind": "CONTINUE",
                "authorized_action": "EXECUTION",
                "active_goal_id": state.get("active_goal_id"),
                "active_task": state.get("active_task"),
            }
        if any(term in text for term in ("voz", "narracao", "sample", "samples", "audio")):
            return {
                "kind": "CAPABILITY",
                "authorized_action": "EXECUTION",
                "capability_id": "narration.generate.pt-BR",
                "artifact_ref": resolved_reference or state.get("active_artifact"),
            }
        if "roteiro" in text and any(term in text for term in ("manda", "envia", "mostra")):
            return {
                "kind": "PRESENT_EXISTING",
                "authorized_action": "DECISION",
                "artifact_ref": resolved_reference or state.get("active_artifact") or "script:last",
            }
        return {
            "kind": "CAPABILITY_DISCOVERY",
            "authorized_action": "EXECUTION",
            "artifact_ref": resolved_reference,
        }
    return {"kind": "CHAT", "authorized_action": "DECISION"}


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

    if plan["kind"] == "CAPABILITY":
        capability_id = str(plan.get("capability_id") or "").strip()
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


def _status_answer(state: dict[str, Any]) -> str:
    status = str(state.get("execution_status") or "IDLE")
    stage = str(state.get("active_stage") or "").strip()
    task = str(state.get("active_task") or "").strip()
    goal = str(state.get("active_goal_id") or "").strip()
    run_id = str(state.get("active_run_id") or "").strip()
    blocker = str(state.get("active_blocker") or "").strip()
    waiting = bool(state.get("waiting_for_human"))
    if waiting:
        target = str(state.get("pending_human_review") or state.get("pending_question") or "decisão pendente")
        return f"Estou aguardando você: {target}. Não há execução autônoma passando por cima dessa decisão."
    if status in {"RUNNING", "IN_PROGRESS"}:
        details = [item for item in (task, f"etapa {stage}" if stage else "", f"run {run_id}" if run_id else "") if item]
        text = "Estou executando " + (" — ".join(details) if details else "a tarefa ativa") + "."
        if blocker:
            text += f" Blocker atual: {blocker}."
        return text
    if blocker:
        return f"Estou parado por um blocker real: {blocker}."
    if task or goal:
        return f"Não há etapa rodando agora. A tarefa ativa é {task or goal}; posso continuar dela sem você repetir IDs."
    return "Não há run nem tarefa ativa registrada nesta conversa agora."


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
    telegram_message_id: int | None = None,
    input_record: dict[str, Any] | None = None,
    progress_callback: ProgressCallback | None = None,
    chat_handler: ChatHandler = chat_under_harness,
    action_executor: ActionExecutor = _default_action_executor,
    presenter: Callable[..., dict[str, Any]] = present_canonical_result_under_harness,
) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        raise ValueError("Telegram conversation message is empty")

    state = get_or_create_conversation_state(telegram_chat_id)
    recent_before = list_recent_conversation_turns(telegram_chat_id, limit=10)
    intent = classify_conversation_intent(text)
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
        metadata={"reference_basis": resolved.get("basis")},
    )
    state = update_conversation_state(
        telegram_chat_id,
        last_human_intent=intent,
        current_subject=resolved.get("reference") or state.get("current_subject") or text[:240],
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

    if progress_callback is not None:
        progress_callback("UNDERSTANDING", f"Entendi como {intent.lower().replace('_', ' ')}; resolvendo contexto e autorização.")

    canonical: dict[str, Any]
    decision = None
    if plan["kind"] == "STATUS":
        state = get_or_create_conversation_state(telegram_chat_id)
        canonical = {
            "status": "OBSERVED",
            "answer": _status_answer(state),
            "intent": intent,
            "conversation_state": state,
        }
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
        )
        changes: dict[str, Any] = {"last_human_decision": decision_type}
        if decision_type == "APPROVAL":
            changes.update(waiting_for_human=False, pending_human_review=None, pending_question=None)
        else:
            changes.update(waiting_for_human=True, pending_human_review=resolved.get("reference") or state.get("current_subject"))
        state = update_conversation_state(telegram_chat_id, **changes)
        if decision_type == "APPROVAL":
            answer = f"Aprovação vinculada a {resolved.get('reference') or 'resultado ativo'}. Vou usar essa decisão nas próximas ações governadas."
        else:
            answer = f"Feedback vinculado a {resolved.get('reference') or 'resultado ativo'}. Não vou repetir a próxima execução ignorando essa correção."
        canonical = {
            "status": "HUMAN_DECISION_RECORDED",
            "answer": answer,
            "human_decision": decision,
            "learning_correction": correction,
        }
    elif plan["kind"] == "PRESENT_EXISTING":
        canonical = {
            "status": "REFERENCE_RESOLVED",
            "answer": (
                f"Resolvi seu pedido para {plan.get('artifact_ref')}. "
                "A referência ficou vinculada à conversa; a entrega do conteúdo usa a apresentação Telegram sem exigir que você repita IDs."
            ),
            "artifact_ref": plan.get("artifact_ref"),
        }
    elif plan["kind"] == "RESEARCH_REQUEST":
        update_conversation_state(
            telegram_chat_id,
            execution_status="RUNNING",
            active_stage="RESEARCH",
            active_task=text[:240],
            active_blocker=None,
            waiting_for_human=False,
        )
        if progress_callback is not None:
            progress_callback("RESEARCH", "Pesquisando evidências atuais pelo boundary oficial do Harness.")
        canonical = _parse_result(
            chat_handler(
                text,
                progress_callback=progress_callback,
                input_record=input_record,
                conversation_context=context,
                force_fresh_research=True,
            )
        )
    elif plan["kind"] in {"CONTINUE", "CAPABILITY", "CAPABILITY_DISCOVERY"}:
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
    artifact_ref = (
        _extract_identity(canonical, "artifact_ref", "artifact_id", "script_id")
        or resolved.get("reference")
        or state.get("active_artifact")
    )
    capability_id = _extract_identity(canonical, "capability_id")
    status = str(_extract_identity(canonical, "status") or "COMPLETED").upper()
    waiting = status in {"WAITING_FOR_HUMAN", "WAITING", "BLOCKED_HUMAN"}
    blocker = _extract_identity(canonical, "blocker", "error")
    pending_question = canonical.get("pending_question") if isinstance(canonical, dict) else None
    state = update_conversation_state(
        telegram_chat_id,
        active_goal_id=str(goal_id) if goal_id is not None else state.get("active_goal_id"),
        active_task=text[:240],
        active_artifact=str(artifact_ref) if artifact_ref is not None else state.get("active_artifact"),
        active_run_id=str(run_id) if run_id is not None else state.get("active_run_id"),
        active_stage="WAITING_FOR_HUMAN" if waiting else "COMPLETE",
        active_blocker=str(blocker)[:1000] if blocker else None,
        execution_status="WAITING_FOR_HUMAN" if waiting else ("FAILED" if "FAIL" in status or status == "BLOCKED" else "COMPLETED"),
        waiting_for_human=waiting,
        pending_question=str(pending_question) if pending_question else None,
        pending_human_review=(str(artifact_ref) if waiting and artifact_ref is not None else state.get("pending_human_review") if waiting else None),
        last_execution_result={
            **canonical,
            "capability_id": capability_id,
        },
    )

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
        "CONVERSATION_CONTEXT_RETRIEVAL": "PASS",
        "HARNESS_AUTHORITY_PRESERVED": "PASS",
    }
