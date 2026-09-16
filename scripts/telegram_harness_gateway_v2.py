from __future__ import annotations

import json
import os
import time
from typing import Any

from app.main import initialize_application
from app.services.channel_branding_standard_service import (
    get_channel_branding_readiness,
    synchronize_channel_branding_standard_after_registration,
)
from app.services.telegram_harness_service import (
    chat_under_harness,
    list_governed_brand_assets,
)
from app.services.telegram_learning_service import (
    ingest_telegram_input_under_harness,
    list_recent_governed_telegram_inputs,
)
from scripts.telegram_harness_gateway import (
    PAIR_TEXT,
    STATE_FILE,
    TelegramApi,
    TelegramApiError,
    _asset_reply,
    _chat_reply,
    _classify_brand_asset,
    _execute_command,
    _extract_attachment,
    _help_text,
    _load_state,
    _private_message,
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
    memory_id = item.get("memory_id")
    learned = "PASS" if memory_id is not None else "CAPTURED"
    return (
        "--- Telegram → Harness ingest ---\n"
        f"INGESTION={result.get('status')}\n"
        f"AUTHORITY={result.get('authority')}\n"
        f"CAPABILITY={result.get('capability_id')}\n"
        f"CLASSIFICATION={item.get('classification')}\n"
        f"LEARNING={learned}\n"
        f"LEARNING_STATUS={item.get('learning_status')}\n"
        f"MEMORY_EVENT_ID={item.get('memory_event_id')}\n"
        f"CLAIM_ID={item.get('claim_id')}\n"
        f"MEMORY_ID={memory_id}\n"
        f"ROUTING_ID={result.get('routing_id')}"
    )


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
            + "Mensagens comuns são capturadas com proveniência antes do raciocínio. "
            + "Ideias, temas, padrões, notas e notícias são aprendidos de forma tipada; notícias ficam marcadas como incertas até verificação. "
            + "Quando intro e marca d'água oficiais estiverem ambas verificadas, o padrão BR_NO_GTA_VIDEO_BRANDING_V1 é ativado e passa a ser obrigatório para novos vídeos."
        )
    return _execute_command(text)


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_GATEWAY=FAIL", flush=True)
        print("TELEGRAM_GATEWAY_ERROR=TELEGRAM_BOT_TOKEN is not loaded in this process", flush=True)
        return 2

    initialize_application()
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
    print(f"TELEGRAM_BOT_USERNAME={username or ''}", flush=True)
    print("TELEGRAM_HARNESS_SMART_CHAT=ENABLED", flush=True)
    print("TELEGRAM_BRAND_ASSET_INTAKE=ENABLED", flush=True)
    print("TELEGRAM_TOTAL_INGRESS=ENABLED", flush=True)
    print("TELEGRAM_GTA6_LEARNING=ENABLED", flush=True)
    print("TELEGRAM_CHANNEL_BRANDING_STANDARD=ENABLED", flush=True)
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

                parsed = _private_message(update)
                if parsed is None:
                    continue
                user_id, chat_id, message, text = parsed

                if allowed_user_id is None:
                    if text.casefold() != PAIR_TEXT:
                        continue
                    allowed_user_id = user_id
                    state["allowed_user_id"] = user_id
                    state["chat_id"] = chat_id
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

                if user_id != allowed_user_id:
                    print(f"TELEGRAM_REJECTED_USER_ID={user_id}", flush=True)
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
                    api.send(chat_id, reply)
                    continue

                if not text:
                    continue

                api.typing(chat_id)
                try:
                    if text.startswith("/"):
                        reply = _execute_v2_command(text)
                        command_name = text.split()[0]
                    else:
                        learned = _ingest(
                            user_id=user_id,
                            chat_id=chat_id,
                            message=message,
                            update_id=update_id,
                            text=text,
                        )
                        api.send(
                            chat_id,
                            "🧠 DeepSeek Harness capturou sua mensagem com proveniência. Roteando raciocínio governado no cloud...",
                        )
                        reply = _chat_reply(chat_under_harness(text)) + "\n\n" + _learning_evidence(learned)
                        command_name = "natural-language"
                except Exception as exc:
                    reply = f"COMMAND=FAIL\n{type(exc).__name__}: {str(exc)[:1200]}"
                    print(
                        f"TELEGRAM_COMMAND=FAIL USER_ID={user_id} ERROR={type(exc).__name__}",
                        flush=True,
                    )
                else:
                    print(
                        f"TELEGRAM_COMMAND=PASS USER_ID={user_id} COMMAND={command_name}",
                        flush=True,
                    )
                api.send(chat_id, reply)

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
