from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
import unicodedata
from typing import Any

from app.main import initialize_application
from app.services.channel_branding_standard_service import (
    get_channel_branding_readiness,
    synchronize_channel_branding_standard_after_registration,
)
from app.services.telegram_fresh_research_service import requires_fresh_research
from app.services.telegram_harness_service import (
    HarnessReasoningFailure,
    list_governed_brand_assets,
)
from app.services.telegram_conversation_service import (
    classify_conversation_intent,
    handle_telegram_conversation,
)
from app.services.telegram_ingress_policy_service import (
    enroll_allowed_chat,
    parse_governed_telegram_ingress,
)
from app.services.human_presentation_service import (
    ACTION_FIRST,
    TECHNICAL_FULL,
    present_canonical_result_under_harness,
)
from app.database import harness_learning_repository
from app.database.harness_authorization_repository import (
    list_recent_harness_authorizations,
)
from app.services.telegram_learning_service import (
    extract_source_url,
    ingest_telegram_input_under_harness,
    list_recent_governed_telegram_inputs,
)
from app.database.telegram_user_input_repository import (
    get_telegram_user_input,
    list_recent_telegram_user_inputs,
)
from app.database.telegram_source_intelligence_repository import (
    get_editorial_signal_by_candidate,
    get_source_candidate_by_input,
    list_source_claims,
)
from app.database.telegram_presentation_repository import (
    get_latest_telegram_presentation_audit,
    record_telegram_presentation_audit,
)
from app.services.telegram_review_feedback_service import (
    is_render_review_feedback_message,
    record_render_review_feedback,
)
from scripts.telegram_harness_gateway import (
    PAIR_TEXT,
    STATE_FILE,
    TelegramApi,
    TelegramApiError,
    TelegramProgressReporter,
    _asset_reply,
    _chat_reply,
    _classify_brand_asset,
    _execute_command,
    _extract_attachment,
    _help_text,
    _load_state,
    _pairing_private_message,
    _register_attachment,
    _render_result,
    _save_state,
)


def _verify_attachment(api: TelegramApi, attachment: dict[str, Any]) -> dict[str, Any]:
    file_id = attachment.get("telegram_file_id")
    unique_id = attachment.get("telegram_file_unique_id")
    if not isinstance(file_id, str) or not file_id:
        raise ValueError("Telegram attachment has no file_id")
    if not isinstance(unique_id, str) or not unique_id:
        raise ValueError("Telegram attachment has no file_unique_id")
    remote = api.call("getFile", {"file_id": file_id}, timeout=20)
    if not isinstance(remote, dict) or not isinstance(remote.get("file_path"), str):
        raise TelegramApiError("Telegram getFile did not return a usable file path")
    verified = dict(attachment)
    verified["remote_verified"] = True
    return verified


def _ingest(
    *,
    user_id: int,
    chat_id: int,
    message: dict[str, Any],
    update_id: int,
    text: str,
    attachment: dict[str, Any] | None = None,
    classification_override: str | None = None,
) -> dict[str, Any]:
    return ingest_telegram_input_under_harness(
        {
            "telegram_user_id": user_id,
            "telegram_chat_id": chat_id,
            "telegram_message_id": int(message["message_id"]),
            "telegram_update_id": update_id,
            "input_kind": (
                str(attachment.get("media_kind"))
                if attachment is not None
                else "text"
            ),
            "text": text,
            "attachment": attachment,
            "classification_override": classification_override,
        }
    )


def _learning_evidence(result: dict[str, Any]) -> str:
    item = result.get("input") or {}
    memory_event_id = item.get("memory_event_id")
    memory_id = item.get("memory_id")
    return (
        "--- Telegram → Harness input capture ---\n"
        f"INGESTION={result.get('status')}\n"
        f"AUTHORITY={result.get('authority')}\n"
        f"CAPABILITY={result.get('capability_id')}\n"
        f"CLASSIFICATION={item.get('classification')}\n"
        f"INPUT_MEMORY_CAPTURED={'PASS' if memory_event_id is not None else 'FAIL'}\n"
        "EXECUTION_OUTCOME_LEARNED=NOT_OBSERVED\n"
        "USER_GOAL_COMPLETED=NOT_YET_EVALUATED\n"
        f"LEARNING_STATUS={item.get('learning_status')}\n"
        f"MEMORY_EVENT_ID={memory_event_id}\n"
        f"CLAIM_ID={item.get('claim_id')}\n"
        f"MEMORY_ID={memory_id}\n"
        f"ROUTING_ID={result.get('routing_id')}"
    )


def _reasoning_outcome_evidence(result: dict[str, Any]) -> str:
    return (
        "--- Telegram → Harness execution outcome ---\n"
        f"INPUT_MEMORY_CAPTURED={result.get('INPUT_MEMORY_CAPTURED')}\n"
        f"EXECUTION_OUTCOME_LEARNED={result.get('EXECUTION_OUTCOME_LEARNED')}\n"
        f"USER_GOAL_COMPLETED={result.get('USER_GOAL_COMPLETED')}\n"
        f"EPISODE_ID={result.get('episode_id')}\n"
        f"RETRIEVED_FAILURE_MEMORIES={','.join(result.get('retrieved_failure_memory_ids') or []) or 'NONE'}"
    )


def _input_presentation_lineage(
    input_record: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(input_record, dict):
        return {}
    return {
        "telegram_input_id": input_record.get("id"),
        "telegram_message_id": input_record.get("telegram_message_id"),
        "telegram_update_id": input_record.get("telegram_update_id"),
        "memory_event_id": input_record.get("memory_event_id"),
        "classification": input_record.get("classification"),
        "input_kind": input_record.get("input_kind"),
        "source_url": input_record.get("source_url"),
    }


def _reasoning_failure_presentation(
    exc: HarnessReasoningFailure,
    *,
    input_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = exc.to_dict()
    error = payload.get("provider_error")
    error = error if isinstance(error, dict) else {}
    canonical_failure = {
        "status": "FAILED",
        "success": False,
        "error": {
            "code": str(error.get("code") or "provider_failure"),
            "message": str(
                error.get("message")
                or error.get("safe_message")
                or "Falha observada no executor de raciocínio."
            ),
        },
        "answer": (
            "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE. "
            "A tarefa exige raciocínio semântico e nenhum provider elegível está disponível agora. "
            "Status e controles determinísticos continuam funcionando."
        ),
    }
    return present_canonical_result_under_harness(
        canonical_failure,
        surface="telegram",
        mode=ACTION_FIRST,
        lineage={
            **_input_presentation_lineage(input_record),
            "episode_id": payload.get("episode_id"),
            "failure_memory_id": payload.get("failure_memory_id"),
            "execution_id": payload.get("execution_id"),
        },
    )


def _reasoning_failure_reply(exc: HarnessReasoningFailure) -> str:
    return str(_reasoning_failure_presentation(exc)["text"])


def _generic_failure_presentation(
    exc: Exception,
    *,
    input_record: dict[str, Any] | None = None,
    command: str | None = None,
    telegram_message_id: int | None = None,
    telegram_update_id: int | None = None,
) -> dict[str, Any]:
    canonical_failure = {
        "status": "FAILED",
        "success": False,
        "error": {
            "code": type(exc).__name__,
            "message": str(exc)[:1200] or type(exc).__name__,
        },
        "answer": (
            "Corrija a causa mostrada acima e repita a ação. "
            "Use /evidence quando houver input persistido."
        ),
    }
    return present_canonical_result_under_harness(
        canonical_failure,
        surface="telegram",
        mode=ACTION_FIRST,
        lineage={
            **_input_presentation_lineage(input_record),
            "command": command,
            "telegram_message_id": (
                _input_presentation_lineage(input_record).get("telegram_message_id")
                or telegram_message_id
            ),
            "telegram_update_id": (
                _input_presentation_lineage(input_record).get("telegram_update_id")
                or telegram_update_id
            ),
            "presentation_error": type(exc).__name__,
        },
    )


def _editorial_action(result: dict[str, Any]) -> str | None:
    intelligence = result.get("source_intelligence")
    if not isinstance(intelligence, dict):
        return None
    signal = intelligence.get("editorial_signal")
    if not isinstance(signal, dict):
        return None
    decision = str(signal.get("harness_decision") or "").strip()
    labels = {
        "USE_FOR_VIDEO": "usar como oportunidade de vídeo",
        "MERGE_WITH_EXISTING_GOAL": "mesclar com pauta já existente",
        "STORE_FOR_FUTURE": "guardar para uso editorial futuro",
        "REJECT_LOW_EVIDENCE": "não usar editorialmente por evidência insuficiente",
        "REJECT_SATURATED": "não abrir nova pauta por saturação/duplicidade",
    }
    return labels.get(decision, decision or None)


def _present_chat_v2(
    result: dict[str, Any],
    *,
    input_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return present_canonical_result_under_harness(
        result,
        surface="telegram",
        mode=ACTION_FIRST,
        lineage=_input_presentation_lineage(input_record),
    )


def _chat_reply_v2(result: dict[str, Any]) -> str:
    return str(_present_chat_v2(result)["text"])


def _source_evidence_payload(input_id: int | None = None) -> dict[str, Any]:
    if input_id is None:
        rows = list_recent_telegram_user_inputs(limit=50)
        record = rows[0] if rows else None
    else:
        record = get_telegram_user_input(input_id)
    if record is None:
        raise ValueError("nenhuma entrada Telegram foi encontrada")
    candidate = get_source_candidate_by_input(int(record["id"]))
    claims = (
        list_source_claims(candidate["candidate_id"])
        if candidate is not None else []
    )
    signal = (
        get_editorial_signal_by_candidate(candidate["candidate_id"])
        if candidate is not None else None
    )
    safe_input = {
        key: record.get(key)
        for key in (
            "id", "telegram_message_id", "telegram_update_id", "input_kind",
            "classification", "learning_status", "source_url", "source_state",
            "memory_event_id", "claim_id", "memory_id",
            "execution_outcome_status", "execution_episode_id",
            "execution_failure_memory_id", "created_at", "updated_at",
        )
    }
    episode = None
    if record.get("execution_episode_id"):
        episode = harness_learning_repository.get_episode(
            str(record["execution_episode_id"])
        )
    authorizations = [
        item
        for item in list_recent_harness_authorizations(limit=200)
        if (item.get("lineage") or {}).get("telegram_input_id") == record.get("id")
    ]
    episode_lineage = dict((episode or {}).get("lineage") or {})
    actual_outcome = dict((episode or {}).get("actual_outcome") or {})
    source_versions = dict((episode or {}).get("source_versions") or {})
    executor_binding = next(
        (
            (item.get("lineage") or {}).get("selected_executor_binding")
            or (item.get("lineage") or {}).get("executor_binding")
            for item in authorizations
            if (item.get("lineage") or {}).get("selected_executor_binding")
            or (item.get("lineage") or {}).get("executor_binding")
        ),
        None,
    )
    provider = (
        (episode or {}).get("provider")
        or actual_outcome.get("provider")
        or episode_lineage.get("provider")
    )
    model = (
        actual_outcome.get("model")
        or source_versions.get("model")
        or episode_lineage.get("model")
    )
    competence = []
    if episode is not None:
        competence = harness_learning_repository.list_competence(
            capability_id=episode.get("capability_id"),
            agent_id=episode.get("agent_id"),
            limit=20,
        )
    fact_check_results = [
        {
            "claim_id": item.get("claim_id"),
            "statement": item.get("statement"),
            "fact_check_result": item.get("fact_check_result"),
            "verification_status": item.get("verification_status"),
            "source_hierarchy": item.get("source_hierarchy"),
            "source_refs": item.get("source_refs"),
            "evidence_refs": item.get("evidence_refs"),
        }
        for item in claims
    ]
    return {
        "INPUT_CAPTURED": "PASS" if record.get("memory_event_id") else "FAIL",
        "SOURCE_LEARNED": (
            "PASS"
            if candidate is not None
            and candidate.get("source_state") in {
                "VERIFIED",
                "CONTRADICTED",
                "INSUFFICIENT_EVIDENCE",
                "MEMORY_ELIGIBLE",
            }
            else "PENDING"
        ),
        "CLAIM_VERIFIED": (
            "PASS"
            if any(item.get("verification_status") == "VERIFIED" for item in claims)
            else "NO"
        ),
        "SEMANTIC_MEMORY_PROMOTED": (
            "PASS" if any(item.get("semantic_memory_id") for item in claims) else "NO"
        ),
        "EDITORIAL_SIGNAL_CREATED": "PASS" if signal is not None else "NO",
        "EDITORIAL_SIGNAL_USED": (
            "PASS" if signal is not None and signal.get("status") == "USED" else "NO"
        ),
        "input": safe_input,
        "source_candidate": candidate,
        "claims": claims,
        "editorial_signal": signal,
        "reasoning_episode": episode,
        "routing": [dict(item.get("lineage") or {}) for item in authorizations],
        "harness_authorizations": authorizations,
        "execution": {
            "execution_id": (episode or {}).get("execution_id"),
            "provider": provider,
            "model": model,
            "executor_binding": executor_binding,
            "capability_id": (episode or {}).get("capability_id"),
            "agent_id": (episode or {}).get("agent_id"),
            "skill_id": (episode or {}).get("skill_id"),
            "skill_version": (episode or {}).get("skill_version"),
            "status": (episode or {}).get("status"),
            "error": (episode or {}).get("error"),
            "tool_calls": (episode or {}).get("tool_calls"),
            "artifact_refs": (episode or {}).get("artifact_refs"),
            "timestamps": {
                "started_at": (episode or {}).get("started_at"),
                "finished_at": (episode or {}).get("finished_at"),
                "created_at": (episode or {}).get("created_at"),
            },
        },
        "source_provenance": {
            "source_url": (candidate or {}).get("source_url"),
            "source_content_resolution": (candidate or {}).get("source_content_resolution"),
            "source_hierarchy": (candidate or {}).get("source_hierarchy"),
            "research_dossier_id": (candidate or {}).get("research_dossier_id"),
            "evidence_refs": (candidate or {}).get("evidence_refs"),
            "state_history": (candidate or {}).get("state_history"),
        },
        "ResearchDossier": {
            "research_dossier_id": (candidate or {}).get("research_dossier_id"),
            "payload": ((candidate or {}).get("payload") or {}).get("research_dossier"),
        },
        "FactCheckResult": fact_check_results,
        "ClaimLedger": claims,
        "LearningContext": {
            "episode": episode,
            "competence": competence,
            "memory_event_id": record.get("memory_event_id"),
            "memory_id": record.get("memory_id"),
            "execution_failure_memory_id": record.get("execution_failure_memory_id"),
        },
        "presentation_audit": get_latest_telegram_presentation_audit(int(record["id"])),
        "AUDIT_DETAILS_PRESERVED": "PASS",
        "EVIDENCE_COMMAND_AVAILABLE": "PASS",
    }


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _conversation_classification_override(text: str) -> str | None:
    """Questions are captured as questions unless a URL makes them source input."""
    normalized = _fold(text).strip()
    if extract_source_url(text) is not None:
        return None
    if requires_fresh_research(text):
        return "question"
    if normalized.endswith("?") or normalized.startswith(
        (
            "me diga",
            "explique",
            "quero que voce me diga",
            "quero saber",
            "qual ",
            "quais ",
            "como ",
            "quando ",
            "onde ",
            "quem ",
            "o que ",
        )
    ):
        return "question"
    return None


def _attachment_reply(result: dict[str, Any]) -> str:
    item = result.get("input") or {}
    lines = [
        "TELEGRAM_INPUT=PASS",
        f"HARNESS_AUTHORITY={result.get('authority')}",
        f"CLASSIFICATION={item.get('classification')}",
        f"LEARNING_STATUS={item.get('learning_status')}",
        f"INPUT_ID={item.get('id')}",
        f"MEMORY_EVENT_ID={item.get('memory_event_id')}",
        f"CLAIM_ID={item.get('claim_id')}",
        f"MEMORY_ID={item.get('memory_id')}",
        f"REMOTE_GETFILE_VERIFIED={item.get('remote_verified')}",
        f"TELEGRAM_FILE_UNIQUE_ID={item.get('telegram_file_unique_id')}",
        "MEDIA_BYTES_ON_A15=NO",
    ]
    if item.get("learning_status") == "pending_cloud_analysis":
        lines.extend(
            [
                "CONTENT_ANALYSIS=PENDING_CLOUD_ANALYSIS",
                "NOTE=O arquivo foi preservado por identidade/proveniência, mas não vou fingir que analisei pixels/áudio antes da capability cloud existir.",
            ]
        )
    return "\n".join(lines)


def _branding_reply(readiness: dict[str, Any]) -> str:
    return (
        "CHANNEL_BRANDING_STANDARD=PASS\n"
        f"STANDARD={readiness.get('standard')}\n"
        f"ACTIVE={readiness.get('active')}\n"
        f"READY={readiness.get('ready')}\n"
        f"REQUIRED={','.join(readiness.get('required_asset_types') or [])}\n"
        f"MISSING={','.join(readiness.get('missing_asset_types') or []) or 'NONE'}\n"
        f"ENFORCEMENT={readiness.get('enforcement')}\n"
        "RULE=Quando ACTIVE=True, todo novo vídeo falha fechado se não houver exatamente uma intro e uma marca d'água oficiais verificadas."
    )


def _execute_v2_command(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", 1)[0].casefold()
    if command in {"/inbox", "/ingress", "/alimentacao"}:
        return _render_result(list_recent_governed_telegram_inputs(limit=20))
    if command in {"/evidence", "/debug", "/evidencia"}:
        input_id = None
        if len(parts) == 2 and parts[1].strip():
            try:
                input_id = int(parts[1].strip())
            except ValueError as exc:
                raise ValueError("uso: /evidence [telegram_input_id]") from exc
        audit = _source_evidence_payload(input_id)
        presentation = present_canonical_result_under_harness(
            audit,
            surface="telegram",
            mode=TECHNICAL_FULL,
            lineage={
                "telegram_input_id": (audit.get("input") or {}).get("id"),
                "audit_command": command,
            },
        )
        return str(presentation["text"])
    if command in {"/aprendeu", "/learned"}:
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("uso: /aprendeu <consulta>")
        return _execute_command(f"/memoria {parts[1].strip()}")
    if command in {"/assets", "/branding", "/marca"}:
        return _render_result(
            {
                "brand_assets": list_governed_brand_assets(),
                "channel_standard": get_channel_branding_readiness(),
            }
        )
    if command in {"/help", "/start", "/ajuda"}:
        return (
            _help_text()
            + "\n\nAprendizado e padrão do canal:\n"
            + "/inbox — mostra entradas Telegram capturadas pelo Harness\n"
            + "/aprendeu <consulta> — prova o que entrou no Knowledge Brain\n"
            + "/assets — mostra intro/marca d'água e o padrão obrigatório do canal\n"
            + "/evidence [input_id] — mostra a telemetria completa de fonte/claims/editorial\n"
            + "Mensagens comuns são capturadas com proveniência antes do raciocínio. "
            + "Notícias e URLs viram SourceCandidate e exigem fetch + fact-check antes de qualquer promoção semântica. "
            + "Quando intro e marca d'água oficiais estiverem ambas verificadas, o padrão BR_NO_GTA_VIDEO_BRANDING_V1 é ativado e passa a ser obrigatório para novos vídeos."
        )
    return _execute_command(text)


def _handle_live_natural_language_message(
    *,
    api: TelegramApi,
    user_id: int,
    chat_id: int,
    message: dict[str, Any],
    update_id: int,
    text: str,
    chat_type: str = "private",
    conversation_handler=None,
    action_executor=None,
    chat_handler=None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Execute the exact live v2 ingress through ConversationService.

    This helper is intentionally testable without Telegram long-polling.  It
    preserves the real ingress/provenance record, then delegates intent/state
    resolution to ConversationService.  It never calls ai.reasoning.text
    directly.
    """

    learned = _ingest(
        user_id=user_id,
        chat_id=chat_id,
        message=message,
        update_id=update_id,
        text=text,
        classification_override=_conversation_classification_override(text),
    )
    preclassified_intent = classify_conversation_intent(text)
    deterministic_control = preclassified_intent in {
        "STATUS_REQUEST",
        "MEMORY_RECALL_REQUEST",
    }
    reporter = None if deterministic_control else TelegramProgressReporter(api, chat_id)
    if reporter is not None:
        reporter.start()
    kwargs: dict[str, Any] = {
        "telegram_user_id": user_id,
        "telegram_chat_id": chat_id,
        "telegram_chat_type": chat_type,
        "telegram_message_id": int(message["message_id"]),
        "input_record": learned["input"],
        "progress_callback": reporter,
    }
    if action_executor is not None:
        kwargs["action_executor"] = action_executor
    if chat_handler is not None:
        kwargs["chat_handler"] = chat_handler
    handler = conversation_handler or handle_telegram_conversation
    try:
        conversation = handler(text, **kwargs)
    finally:
        if reporter is not None:
            reporter.stop()

    reply = _chat_reply(conversation)
    canonical = conversation.get("canonical_result")
    if isinstance(canonical, dict):
        presentation = _present_chat_v2(
            canonical,
            input_record=learned["input"],
        )
        audit = record_telegram_presentation_audit(
            telegram_input_id=int(learned["input"]["id"]),
            presentation=presentation,
            reply_text=reply,
        )
        print(
            "TELEGRAM_PRESENTATION=PASS "
            f"MODE={presentation.get('mode')} "
            f"CANONICAL_UNCHANGED={presentation.get('canonical_unchanged')} "
            f"INPUT_ID={audit.get('telegram_input_id')} "
            f"REPLY_SHA256={audit.get('reply_sha256')} "
            f"AUTHORITY={presentation.get('authority')}",
            flush=True,
        )
    return reply, learned, conversation


def _send_final_human_response(
    *,
    api: TelegramApi,
    chat_id: int,
    reply: str,
    runtime_revision: str,
) -> int | None:
    digest = hashlib.sha256(str(reply).encode("utf-8")).hexdigest()
    try:
        message_id = api.send(chat_id, reply)
    except Exception as exc:
        print(
            "FINAL_HUMAN_RESPONSE_SENT=NO "
            f"SEND_PROCESS_PID={os.getpid()} "
            f"SEND_RUNTIME_REVISION={runtime_revision or 'UNSPECIFIED'} "
            f"REPLY_SHA256={digest} "
            f"ERROR={type(exc).__name__}",
            flush=True,
        )
        raise
    print(
        "FINAL_HUMAN_RESPONSE_SENT=PASS "
        f"TELEGRAM_SEND_MESSAGE_ID={message_id if message_id is not None else 'UNKNOWN'} "
        f"SEND_PROCESS_PID={os.getpid()} "
        f"SEND_RUNTIME_REVISION={runtime_revision or 'UNSPECIFIED'} "
        f"REPLY_SHA256={digest}",
        flush=True,
    )
    return message_id


def _acquire_runtime_singleton():
    lock_path = Path(
        os.getenv(
            "TELEGRAM_GATEWAY_RUNTIME_LOCK_FILE",
            str(STATE_FILE.parent / "telegram-gateway.runtime.lock"),
        )
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def _write_runtime_revision_proof() -> dict[str, Any]:
    revision = os.getenv("BR_TELEGRAM_GATEWAY_REVISION", "").strip()
    revision_file = os.getenv("TELEGRAM_GATEWAY_REVISION_FILE", "").strip()
    proof = {
        "pid": os.getpid(),
        "revision": revision,
    }
    if not revision or not revision_file:
        return proof
    path = Path(revision_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        f"{proof['pid']} {revision}\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return proof


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_GATEWAY=FAIL", flush=True)
        print("TELEGRAM_GATEWAY_ERROR=TELEGRAM_BOT_TOKEN is not loaded in this process", flush=True)
        return 2

    runtime_lock = _acquire_runtime_singleton()
    if runtime_lock is None:
        print("TELEGRAM_GATEWAY=FAIL", flush=True)
        print("TELEGRAM_GATEWAY_ERROR=DUPLICATE_RUNTIME_LOCK_HELD", flush=True)
        return 4

    initialize_application()
    revision_proof = _write_runtime_revision_proof()
    api = TelegramApi(token)
    me = api.call("getMe")
    webhook = api.call("getWebhookInfo")
    webhook_url = str((webhook or {}).get("url") or "").strip()
    if webhook_url:
        print("TELEGRAM_GATEWAY=FAIL", flush=True)
        print("TELEGRAM_GATEWAY_ERROR=active Telegram webhook conflicts with Termux long polling", flush=True)
        return 3

    state = _load_state()
    allowed_env = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
    allowed_user_id: int | None = None
    if allowed_env:
        allowed_user_id = int(allowed_env)
    elif state.get("allowed_user_id") is not None:
        allowed_user_id = int(state["allowed_user_id"])

    offset = int(state.get("offset") or 0)
    username = (me or {}).get("username") if isinstance(me, dict) else None
    print("TELEGRAM_GATEWAY=ONLINE", flush=True)
    print(
        "TELEGRAM_GATEWAY_REVISION="
        + (str(revision_proof.get("revision") or "UNSPECIFIED")),
        flush=True,
    )
    print(f"TELEGRAM_GATEWAY_PID={revision_proof.get('pid')}", flush=True)
    print(f"TELEGRAM_BOT_USERNAME={username or ''}", flush=True)
    print(
        "TELEGRAM_BOT_CAN_JOIN_GROUPS="
        + ("YES" if bool((me or {}).get("can_join_groups")) else "NO"),
        flush=True,
    )
    print(
        "TELEGRAM_BOT_CAN_READ_ALL_GROUP_MESSAGES="
        + ("YES" if bool((me or {}).get("can_read_all_group_messages")) else "NO"),
        flush=True,
    )
    print(
        "TELEGRAM_GROUP_NATURAL_LANGUAGE_READY="
        + (
            "PASS"
            if bool((me or {}).get("can_join_groups"))
            and bool((me or {}).get("can_read_all_group_messages"))
            else "FAIL"
        ),
        flush=True,
    )
    print("TELEGRAM_HARNESS_SMART_CHAT=ENABLED", flush=True)
    print("TELEGRAM_BRAND_ASSET_INTAKE=ENABLED", flush=True)
    print("TELEGRAM_TOTAL_INGRESS=ENABLED", flush=True)
    print("TELEGRAM_GTA6_LEARNING=ENABLED", flush=True)
    print("TELEGRAM_CHANNEL_BRANDING_STANDARD=ENABLED", flush=True)
    print("TELEGRAM_FRESH_GTA6_RESEARCH=ENABLED", flush=True)
    if allowed_user_id is None:
        print(f"TELEGRAM_PAIRING=WAITING_TEXT:{PAIR_TEXT}", flush=True)
    else:
        print(f"TELEGRAM_ALLOWED_USER_ID={allowed_user_id}", flush=True)

    while True:
        try:
            updates = api.call(
                "getUpdates",
                {
                    "offset": str(offset),
                    "timeout": "30",
                    "allowed_updates": json.dumps(["message"]),
                },
                timeout=40,
            )
            if not isinstance(updates, list):
                updates = []

            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = int(update.get("update_id") or 0)
                if update_id >= offset:
                    offset = update_id + 1
                    state["offset"] = offset

                if allowed_user_id is None:
                    parsed = _pairing_private_message(update)
                    if parsed is None:
                        continue
                    user_id, chat_id, message, text = parsed
                    if text.casefold() != PAIR_TEXT:
                        continue
                    allowed_user_id = user_id
                    state["allowed_user_id"] = user_id
                    state["chat_id"] = chat_id
                    state["allowed_chat_ids"] = sorted({
                        *[int(item) for item in (state.get("allowed_chat_ids") or [])],
                        int(chat_id),
                    })
                    _save_state(state)
                    print(
                        f"TELEGRAM_PAIRING=PASS USER_ID={user_id} CHAT_ID={chat_id}",
                        flush=True,
                    )
                    api.send(
                        chat_id,
                        "BR-no-GTA conectado. Seu Telegram foi pareado como control surface do DeepSeek Harness.\n\n"
                        + _execute_v2_command("/help"),
                    )
                    continue

                ingress = parse_governed_telegram_ingress(
                    update,
                    allowed_user_id=allowed_user_id,
                    state=state,
                )
                if ingress is None:
                    continue
                user_id = ingress.user_id
                chat_id = ingress.chat_id
                message = ingress.message
                text = ingress.text
                chat_type = ingress.chat_type

                if not ingress.authorized_sender:
                    print(
                        f"TELEGRAM_REJECTED_USER_ID={user_id} CHAT_ID={chat_id} CHAT_TYPE={chat_type}",
                        flush=True,
                    )
                    continue

                if (
                    not ingress.authorized_chat
                    and chat_type in {"group", "supergroup"}
                    and text.split("@", 1)[0].casefold() == "/allow_here"
                ):
                    state = enroll_allowed_chat(
                        state,
                        chat_id=chat_id,
                        authorized_user_id=allowed_user_id,
                        sender_user_id=user_id,
                    )
                    _save_state(state)
                    api.send(
                        chat_id,
                        "Este chat foi autorizado como superfície do mesmo humano/projeto. "
                        "Outros remetentes continuam sem autorização.",
                    )
                    print(
                        f"TELEGRAM_CHAT_ENROLLED=PASS USER_ID={user_id} CHAT_ID={chat_id} CHAT_TYPE={chat_type}",
                        flush=True,
                    )
                    continue

                if not ingress.authorized_chat:
                    print(
                        f"TELEGRAM_REJECTED_CHAT=YES USER_ID={user_id} CHAT_ID={chat_id} CHAT_TYPE={chat_type}",
                        flush=True,
                    )
                    continue

                attachment = _extract_attachment(message)
                if attachment is not None:
                    try:
                        verified = _verify_attachment(api, attachment)
                        asset_type = _classify_brand_asset(text, verified.get("file_name"))
                        if asset_type is not None:
                            brand_result = _register_attachment(
                                api=api,
                                attachment=attachment,
                                asset_type=asset_type,
                                user_id=user_id,
                                chat_id=chat_id,
                                message=message,
                                update_id=update_id,
                                caption=text,
                            )
                            readiness = synchronize_channel_branding_standard_after_registration(
                                registration_result=brand_result,
                            )
                            learned = _ingest(
                                user_id=user_id,
                                chat_id=chat_id,
                                message=message,
                                update_id=update_id,
                                text=text,
                                attachment=verified,
                                classification_override="brand_asset",
                            )
                            reply = (
                                _asset_reply(brand_result)
                                + "\n\n"
                                + _branding_reply(readiness)
                                + "\n\n"
                                + _learning_evidence(learned)
                            )
                            print(
                                f"TELEGRAM_ASSET=PASS USER_ID={user_id} TYPE={asset_type} ASSET_ID={brand_result['asset']['id']} BRANDING_STANDARD_ACTIVE={readiness['active']}",
                                flush=True,
                            )
                        else:
                            learned = _ingest(
                                user_id=user_id,
                                chat_id=chat_id,
                                message=message,
                                update_id=update_id,
                                text=text,
                                attachment=verified,
                            )
                            reply = _attachment_reply(learned)
                            print(
                                f"TELEGRAM_INGRESS=PASS USER_ID={user_id} CLASS={learned['input']['classification']} INPUT_ID={learned['input']['id']}",
                                flush=True,
                            )
                    except Exception as exc:
                        reply = f"TELEGRAM_INPUT=FAIL\n{type(exc).__name__}: {str(exc)[:1200]}"
                        print(
                            f"TELEGRAM_INGRESS=FAIL USER_ID={user_id} ERROR={type(exc).__name__}",
                            flush=True,
                        )
                    _send_final_human_response(
                        api=api,
                        chat_id=chat_id,
                        reply=reply,
                        runtime_revision=str(revision_proof.get("revision") or ""),
                    )
                    continue

                if not text:
                    continue

                api.typing(chat_id)
                learned: dict[str, Any] | None = None
                command_name = text.split()[0] if text.startswith("/") else "natural-language"
                try:
                    if is_render_review_feedback_message(message, text):
                        learned = _ingest(
                            user_id=user_id,
                            chat_id=chat_id,
                            message=message,
                            update_id=update_id,
                            text=text,
                            classification_override="chat",
                        )
                        feedback = record_render_review_feedback(
                            message=message,
                            input_record=learned["input"],
                            text=text,
                        )
                        reply = (
                            _render_result(feedback)
                            + "\n\n"
                            + _learning_evidence(learned)
                            + "\n\nPUBLICATION_AUTHORITY=NONE"
                        )
                        command_name = "CHANGES_REQUESTED"
                    elif text.startswith("/"):
                        reply = _execute_v2_command(text)
                        command_name = text.split()[0]
                    else:
                        reply, learned, conversation = _handle_live_natural_language_message(
                            api=api,
                            user_id=user_id,
                            chat_id=chat_id,
                            message=message,
                            update_id=update_id,
                            text=text,
                            chat_type=chat_type,
                        )
                        print(
                            "TELEGRAM_CONVERSATION_SERVICE=PASS "
                            f"USER_ID={user_id} "
                            f"INTENT={conversation.get('intent')} "
                            f"PLAN={(conversation.get('plan') or {}).get('kind')}",
                            flush=True,
                        )
                        if conversation.get("intent") == "STATUS_REQUEST":
                            status_result = conversation.get("canonical_result")
                            status_result = (
                                status_result
                                if isinstance(status_result, dict)
                                else {}
                            )
                            print(
                                "TELEGRAM_STATUS_RESULT=PASS "
                                f"STALE_PROGRESS_STATE_DETECTED={status_result.get('STALE_PROGRESS_STATE_DETECTED')} "
                                f"STALE_PROGRESS_STATE_RECONCILED={status_result.get('STALE_PROGRESS_STATE_RECONCILED')} "
                                f"STATUS_PROVIDER_CALLS={status_result.get('STATUS_PROVIDER_CALLS')} "
                                f"STATUS_OPENCODE_CALLS={status_result.get('STATUS_OPENCODE_CALLS')} "
                                f"STATUS_HERMES_CALLS={status_result.get('STATUS_HERMES_CALLS')}",
                                flush=True,
                            )
                        command_name = "natural-language"
                except HarnessReasoningFailure as exc:
                    input_record = (
                        learned.get("input")
                        if isinstance(learned, dict)
                        and isinstance(learned.get("input"), dict)
                        else None
                    )
                    presentation = _reasoning_failure_presentation(
                        exc,
                        input_record=input_record,
                    )
                    reply = str(presentation["text"])
                    if input_record is not None:
                        audit = record_telegram_presentation_audit(
                            telegram_input_id=int(input_record["id"]),
                            presentation=presentation,
                            reply_text=reply,
                        )
                        print(
                            "TELEGRAM_PRESENTATION=PASS "
                            f"MODE={presentation.get('mode')} "
                            "OUTCOME=FAIL "
                            f"INPUT_ID={audit.get('telegram_input_id')} "
                            f"REPLY_SHA256={audit.get('reply_sha256')}",
                            flush=True,
                        )
                    payload = exc.to_dict()
                    print(
                        "TELEGRAM_COMMAND_EXECUTION=FAIL "
                        f"USER_ID={user_id} "
                        f"ERROR=HarnessReasoningFailure "
                        f"EPISODE_ID={payload.get('episode_id')} "
                        f"FAILURE_MEMORY_ID={payload.get('failure_memory_id')} "
                        f"PROVIDER={payload.get('provider')} "
                        f"MODEL={payload.get('model')}",
                        flush=True,
                    )
                except Exception as exc:
                    input_record = (
                        learned.get("input")
                        if isinstance(learned, dict)
                        and isinstance(learned.get("input"), dict)
                        else None
                    )
                    presentation = _generic_failure_presentation(
                        exc,
                        input_record=input_record,
                        command=command_name,
                        telegram_message_id=int(message.get("message_id") or 0) or None,
                        telegram_update_id=update_id,
                    )
                    reply = str(presentation["text"])
                    if input_record is not None:
                        audit = record_telegram_presentation_audit(
                            telegram_input_id=int(input_record["id"]),
                            presentation=presentation,
                            reply_text=reply,
                        )
                        print(
                            "TELEGRAM_PRESENTATION=PASS "
                            f"MODE={presentation.get('mode')} "
                            "OUTCOME=FAIL "
                            f"INPUT_ID={audit.get('telegram_input_id')} "
                            f"REPLY_SHA256={audit.get('reply_sha256')}",
                            flush=True,
                        )
                    print(
                        f"TELEGRAM_COMMAND_EXECUTION=FAIL USER_ID={user_id} ERROR={type(exc).__name__}",
                        flush=True,
                    )
                else:
                    print(
                        f"TELEGRAM_COMMAND_EXECUTION=PASS USER_ID={user_id} COMMAND={command_name}",
                        flush=True,
                    )
                _send_final_human_response(
                    api=api,
                    chat_id=chat_id,
                    reply=reply,
                    runtime_revision=str(revision_proof.get("revision") or ""),
                )

            _save_state(state)
        except KeyboardInterrupt:
            print("TELEGRAM_GATEWAY=STOPPED", flush=True)
            return 0
        except TelegramApiError as exc:
            print(f"TELEGRAM_GATEWAY_RETRY={str(exc)[:1000]}", flush=True)
            time.sleep(5)
        except Exception as exc:
            print(
                f"TELEGRAM_GATEWAY_RETRY={type(exc).__name__}:{str(exc)[:1000]}",
                flush=True,
            )
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
