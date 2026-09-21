from __future__ import annotations

import json
import os
import time
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.main import initialize_application
from app.services.telegram_harness_service import (
    build_harness_connection_proof,
    list_governed_brand_assets,
    register_telegram_brand_asset_under_harness,
)
from app.services.telegram_conversation_service import handle_telegram_conversation
from app.services.telegram_learning_service import ingest_telegram_input_under_harness
from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
    update_conversation_state,
)


API_ROOT = "https://api.telegram.org/bot"
PAIR_TEXT = os.getenv("TELEGRAM_PAIR_TEXT", "oi harness").strip().casefold()
STATE_FILE = Path(
    os.getenv(
        "TELEGRAM_CONTROL_STATE_FILE",
        str(Path.home() / ".local/state/br-no-gta/telegram-control.json"),
    )
)
MAX_REPLY_CHARS = 3800


class TelegramApiError(RuntimeError):
    pass


def _split_telegram_text(text: str, *, limit: int = MAX_REPLY_CHARS) -> list[str]:
    rendered = str(text or "").strip() or "OK"
    if limit < 256:
        raise ValueError("Telegram message limit is too small")
    payload_limit = limit - 24
    chunks: list[str] = []
    remaining = rendered
    while len(remaining) > payload_limit:
        candidates = [
            remaining.rfind("\n\n", 0, payload_limit),
            remaining.rfind("\n", 0, payload_limit),
            remaining.rfind(" ", 0, payload_limit),
        ]
        cut = max(candidates)
        if cut < payload_limit // 2:
            cut = payload_limit
        chunk = remaining[:cut].rstrip()
        chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    if remaining or not chunks:
        chunks.append(remaining or "OK")
    if len(chunks) == 1:
        return chunks
    total = len(chunks)
    return [f"{index}/{total}\n\n{chunk}" for index, chunk in enumerate(chunks, start=1)]


class TelegramProgressReporter:
    """Stage-aware Telegram progress plus low-noise heartbeat for long operations."""

    def __init__(self, api: "TelegramApi", chat_id: int) -> None:
        self.api = api
        self.chat_id = int(chat_id)
        self.heartbeat_seconds = max(
            30.0,
            float(os.getenv("TELEGRAM_HEARTBEAT_SECONDS", "75")),
        )
        self.progress_min_seconds = max(
            5.0,
            float(os.getenv("TELEGRAM_PROGRESS_MIN_SECONDS", "20")),
        )
        self._stage = "STARTING"
        self._message = ""
        self._last_sent = time.monotonic()
        self._progress_message_id: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"telegram-heartbeat-{self.chat_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def __call__(self, stage: str, message: str) -> None:
        normalized_stage = str(stage or "WORKING").strip().upper()
        rendered = str(message or "").strip()
        now = time.monotonic()
        stage_changed = normalized_stage != self._stage
        self._stage = normalized_stage
        self._message = rendered
        try:
            update_conversation_state(
                self.chat_id,
                active_stage=normalized_stage,
                execution_status="RUNNING",
                active_blocker=None,
            )
        except Exception:
            pass
        if stage_changed or now - self._last_sent >= self.progress_min_seconds:
            body = f"AÇÃO: {rendered}\nAGORA: {normalized_stage}" if rendered else f"AGORA: {normalized_stage}"
            self._publish(body)
            self._last_sent = now

    def blocker(self, message: str) -> None:
        detail = str(message or "").strip()[:1000]
        self._stage = "BLOCKED"
        self._message = detail
        try:
            update_conversation_state(
                self.chat_id,
                active_stage="BLOCKED",
                active_blocker=detail,
                execution_status="FAILED",
            )
        except Exception:
            pass
        self._publish(f"BLOCKER: {detail}")
        self._last_sent = time.monotonic()

    def _publish(self, text: str) -> None:
        if self._progress_message_id is not None and hasattr(self.api, "edit"):
            try:
                self.api.edit(self.chat_id, self._progress_message_id, text)
                return
            except Exception:
                self._progress_message_id = None
        message_id = self.api.send(self.chat_id, text)
        if isinstance(message_id, int):
            self._progress_message_id = message_id

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(5.0):
            now = time.monotonic()
            if now - self._last_sent < self.heartbeat_seconds:
                continue
            stage = self._stage or "WORKING"
            self._publish(
                f"Ainda trabalhando — etapa: {stage}. Nenhum blocker novo."
            )
            self._last_sent = now


class TelegramApi:
    def __init__(self, token: str) -> None:
        token = token.strip()
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self._base_url = f"{API_ROOT}{token}"

    def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = 20,
    ) -> Any:
        body = urllib.parse.urlencode(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise TelegramApiError(f"Telegram HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TelegramApiError(f"Telegram network error: {exc.reason}") from exc

        if not data.get("ok"):
            raise TelegramApiError(str(data.get("description") or data))
        return data.get("result")

    def send(self, chat_id: int, text: str) -> int | None:
        last_message_id: int | None = None
        for chunk in _split_telegram_text(text):
            result = self.call("sendMessage", {"chat_id": str(chat_id), "text": chunk})
            if isinstance(result, dict) and isinstance(result.get("message_id"), int):
                last_message_id = int(result["message_id"])
        return last_message_id

    def edit(self, chat_id: int, message_id: int, text: str) -> None:
        chunks = _split_telegram_text(text)
        if len(chunks) != 1:
            raise ValueError("progress edit must fit in one Telegram message")
        self.call(
            "editMessageText",
            {
                "chat_id": str(chat_id),
                "message_id": str(int(message_id)),
                "text": chunks[0],
            },
        )

    def typing(self, chat_id: int) -> None:
        try:
            self.call(
                "sendChatAction",
                {"chat_id": str(chat_id), "action": "typing"},
                timeout=10,
            )
        except TelegramApiError:
            pass


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    try:
        STATE_FILE.chmod(0o600)
    except OSError:
        pass


def _help_text() -> str:
    return (
        "BR-no-GTA / DeepSeek Harness online.\n\n"
        "Pode falar comigo normalmente: mensagens comuns passam pelo raciocínio AI governado pelo Harness.\n\n"
        "Provas/controle:\n"
        "/harness — prova rota + autorização persistida do DeepSeek Harness\n"
        "/status — observação operacional canônica\n"
        "/assets — intro e marca d'água ativas\n"
        "/memoria <consulta> — Knowledge Brain\n"
        "/produzir <goal_id> — avança o Goal exato pelo Harness\n"
        "/preview <publication_id> — readiness da publicação\n"
        "/upload <publication_id> — despacha upload privado no cloud\n"
        "/upload_status <publication_id> — reconcilia upload privado\n"
        "/pode_postar <publication_id> — aprovação explícita para tornar público\n"
        "/publicacao_status <publication_id> — reconcilia visibilidade pública\n"
        "/evidence — auditoria técnica da conversa/última execução\n"
        "/help — mostra este menu\n\n"
        "Arquivos também entram na conversa: o A15 registra identidade/proveniência via getFile, "
        "sem baixar mídia pesada. Intro e marca d'água continuam reconhecidas pelas legendas explícitas.\n\n"
        "Telegram é ingress/control surface. Autoridade continua no DeepSeek Harness; render, mídia e upload pesado continuam no cloud."
    )


def _render_result(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
    else:
        parsed = value
    return json.dumps(parsed, ensure_ascii=False, indent=2, default=str)


def _publication_id(parts: list[str], command: str) -> int:
    if len(parts) != 2:
        raise ValueError(f"uso: {command} <publication_id>")
    try:
        publication_id = int(parts[1])
    except ValueError as exc:
        raise ValueError("publication_id precisa ser inteiro") from exc
    if publication_id <= 0:
        raise ValueError("publication_id precisa ser positivo")
    return publication_id


def _execute_command(text: str, *, chat_id: int | None = None) -> str:
    from app.integrations.deepseek_harness import server

    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", 1)[0].casefold()

    if command in {"/start", "/help", "/ajuda"}:
        return _help_text()
    if command == "/harness":
        return _render_result(build_harness_connection_proof())
    if command in {"/assets", "/brand", "/branding"}:
        return _render_result(list_governed_brand_assets())
    if command in {"/status", "/observe"}:
        return _render_result(server.br_observe())
    if command == "/evidence":
        if chat_id is None:
            raise ValueError("/evidence requer contexto de chat")
        state = get_or_create_conversation_state(chat_id)
        return _render_result({
            "conversation_id": state.get("conversation_id"),
            "active_goal_id": state.get("active_goal_id"),
            "active_task": state.get("active_task"),
            "active_run_id": state.get("active_run_id"),
            "active_stage": state.get("active_stage"),
            "execution_status": state.get("execution_status"),
            "last_execution_result": state.get("last_execution_result"),
        })
    if command in {"/memoria", "/memory"}:
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("uso: /memoria <consulta>")
        return _render_result(server.br_knowledge_query(parts[1].strip()))
    if command in {"/produzir", "/execute"}:
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("uso: /produzir <goal_id>")
        return _render_result(server.br_execution_process_next(goal_id=parts[1].strip()))

    arg_parts = text.strip().split()
    if command == "/preview":
        return _render_result(
            server.br_youtube_publication_preview(_publication_id(arg_parts, "/preview"))
        )
    if command == "/upload":
        return _render_result(
            server.br_youtube_publish(_publication_id(arg_parts, "/upload"))
        )
    if command in {"/upload_status", "/upload-status"}:
        return _render_result(
            server.br_youtube_publish_reconcile(
                _publication_id(arg_parts, "/upload_status")
            )
        )
    if command == "/pode_postar":
        return _render_result(
            server.br_youtube_pode_postar(
                _publication_id(arg_parts, "/pode_postar")
            )
        )
    if command in {"/publicacao_status", "/publicacao-status"}:
        return _render_result(
            server.br_youtube_publication_reconcile(
                _publication_id(arg_parts, "/publicacao_status")
            )
        )
    raise ValueError("comando não reconhecido. Use /help")


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _classify_brand_asset(text: str, file_name: str | None) -> str | None:
    haystack = _fold(f"{text or ''} {file_name or ''}")
    if any(term in haystack for term in ("marca d'agua", "marca dagua", "watermark", "marca-dagua")):
        return "watermark"
    if any(term in haystack for term in ("intro", "vinheta", "abertura do canal", "abertura canal")):
        return "intro"
    return None


def _extract_attachment(message: dict[str, Any]) -> dict[str, Any] | None:
    document = message.get("document")
    if isinstance(document, dict):
        return {
            "media_kind": "document",
            "telegram_file_id": document.get("file_id"),
            "telegram_file_unique_id": document.get("file_unique_id"),
            "file_name": document.get("file_name"),
            "mime_type": document.get("mime_type"),
            "file_size": document.get("file_size"),
        }

    video = message.get("video")
    if isinstance(video, dict):
        return {
            "media_kind": "video",
            "telegram_file_id": video.get("file_id"),
            "telegram_file_unique_id": video.get("file_unique_id"),
            "file_name": video.get("file_name"),
            "mime_type": video.get("mime_type") or "video/mp4",
            "file_size": video.get("file_size"),
            "width": video.get("width"),
            "height": video.get("height"),
            "duration_seconds": video.get("duration"),
        }

    animation = message.get("animation")
    if isinstance(animation, dict):
        return {
            "media_kind": "animation",
            "telegram_file_id": animation.get("file_id"),
            "telegram_file_unique_id": animation.get("file_unique_id"),
            "file_name": animation.get("file_name"),
            "mime_type": animation.get("mime_type") or "video/mp4",
            "file_size": animation.get("file_size"),
            "width": animation.get("width"),
            "height": animation.get("height"),
            "duration_seconds": animation.get("duration"),
        }

    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        candidates = [item for item in photos if isinstance(item, dict)]
        if not candidates:
            return None
        photo = max(candidates, key=lambda item: int(item.get("file_size") or 0))
        return {
            "media_kind": "photo",
            "telegram_file_id": photo.get("file_id"),
            "telegram_file_unique_id": photo.get("file_unique_id"),
            "file_name": None,
            "mime_type": "image/jpeg",
            "file_size": photo.get("file_size"),
            "width": photo.get("width"),
            "height": photo.get("height"),
        }
    return None


def _private_message(update: dict[str, Any]) -> tuple[int, int, dict[str, Any], str] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    if not isinstance(sender, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str):
        text = message.get("caption")
    if not isinstance(text, str):
        text = ""
    try:
        return int(sender["id"]), int(chat["id"]), message, text.strip()
    except (KeyError, TypeError, ValueError):
        return None


def _verify_attachment_remote(
    *,
    api: TelegramApi,
    attachment: dict[str, Any],
) -> dict[str, Any]:
    file_id = attachment.get("telegram_file_id")
    file_unique_id = attachment.get("telegram_file_unique_id")
    if not isinstance(file_id, str) or not file_id:
        raise ValueError("Telegram attachment has no file_id")
    if not isinstance(file_unique_id, str) or not file_unique_id:
        raise ValueError("Telegram attachment has no file_unique_id")
    remote = api.call("getFile", {"file_id": file_id}, timeout=20)
    if not isinstance(remote, dict) or not isinstance(remote.get("file_path"), str):
        raise TelegramApiError("Telegram getFile did not return a usable file path")
    verified = dict(attachment)
    verified["remote_verified"] = True
    verified["remote_file_path"] = remote["file_path"]
    return verified


def _register_attachment(
    *,
    api: TelegramApi,
    attachment: dict[str, Any],
    asset_type: str,
    user_id: int,
    chat_id: int,
    message: dict[str, Any],
    update_id: int,
    caption: str,
) -> dict[str, Any]:
    # Real remote proof: getFile verifies the exact Telegram identity.
    # Media bytes remain remote; the A15 does not download the attachment.
    payload = _verify_attachment_remote(api=api, attachment=attachment)
    payload.update(
        asset_type=asset_type,
        telegram_user_id=user_id,
        telegram_chat_id=chat_id,
        telegram_message_id=int(message["message_id"]),
        telegram_update_id=update_id,
        caption=caption,
        remote_verified=True,
    )
    return register_telegram_brand_asset_under_harness(payload)


def _asset_reply(result: dict[str, Any]) -> str:
    asset = result.get("asset") or {}
    return (
        "ASSET_REGISTERED=PASS\n"
        f"HARNESS_AUTHORITY={result.get('authority')}\n"
        f"CAPABILITY={result.get('capability_id')}\n"
        f"ROUTING_ID={result.get('routing_id')}\n"
        f"AUTHORIZATION_ID={result.get('authorization_id')}\n"
        f"ASSET_ID={asset.get('id')}\n"
        f"ASSET_TYPE={asset.get('asset_type')}\n"
        f"REMOTE_GETFILE_VERIFIED={asset.get('remote_verified')}\n"
        f"TELEGRAM_FILE_UNIQUE_ID={asset.get('telegram_file_unique_id')}\n"
        f"FILE_NAME={asset.get('file_name')}\n"
        f"FILE_SIZE={asset.get('file_size')}\n"
        "MEDIA_BYTES_ON_A15=NO\n"
        "CANONICAL_METADATA=BR_SQLITE"
    )


def _chat_reply(result: dict[str, Any]) -> str:
    answer = str(result.get("answer") or "").strip() or "Concluído."
    state = result.get("conversation_state")
    if isinstance(state, dict) and bool(state.get("waiting_for_human")):
        target = (
            state.get("pending_human_review")
            or state.get("pending_question")
            or state.get("current_subject")
            or "sua decisão"
        )
        return f"Estou aguardando você sobre {target}.\n\n{answer}"
    return answer


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_GATEWAY=FAIL")
        print("TELEGRAM_GATEWAY_ERROR=TELEGRAM_BOT_TOKEN is not loaded in this process")
        return 2

    initialize_application()
    api = TelegramApi(token)
    me = api.call("getMe")
    webhook = api.call("getWebhookInfo")
    webhook_url = str((webhook or {}).get("url") or "").strip()
    if webhook_url:
        print("TELEGRAM_GATEWAY=FAIL")
        print("TELEGRAM_GATEWAY_ERROR=active Telegram webhook conflicts with Termux long polling")
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
                        + _help_text(),
                    )
                    continue

                if user_id != allowed_user_id:
                    print(f"TELEGRAM_REJECTED_USER_ID={user_id}", flush=True)
                    continue

                attachment = _extract_attachment(message)
                if attachment is not None:
                    asset_type = _classify_brand_asset(text, attachment.get("file_name"))
                    if asset_type is not None:
                        try:
                            result = _register_attachment(
                                api=api,
                                attachment=attachment,
                                asset_type=asset_type,
                                user_id=user_id,
                                chat_id=chat_id,
                                message=message,
                                update_id=update_id,
                                caption=text,
                            )
                        except Exception as exc:
                            reply = f"ASSET_REGISTERED=FAIL\n{type(exc).__name__}: {str(exc)[:1200]}"
                            print(
                                f"TELEGRAM_ASSET=FAIL USER_ID={user_id} ERROR={type(exc).__name__}",
                                flush=True,
                            )
                        else:
                            reply = _asset_reply(result)
                            print(
                                f"TELEGRAM_ASSET=PASS USER_ID={user_id} TYPE={asset_type} ASSET_ID={result['asset']['id']}",
                                flush=True,
                            )
                        api.send(chat_id, reply)
                        continue

                    api.typing(chat_id)
                    reporter = TelegramProgressReporter(api, chat_id)
                    reporter.start()
                    try:
                        verified_attachment = _verify_attachment_remote(
                            api=api,
                            attachment=attachment,
                        )
                        submission_text = text or (
                            "Arquivo enviado: "
                            + str(
                                verified_attachment.get("file_name")
                                or verified_attachment.get("media_kind")
                                or "anexo"
                            )
                        )
                        ingested = ingest_telegram_input_under_harness({
                            "telegram_user_id": user_id,
                            "telegram_chat_id": chat_id,
                            "telegram_message_id": int(message["message_id"]),
                            "telegram_update_id": update_id,
                            "input_kind": str(verified_attachment.get("media_kind") or "attachment"),
                            "text": submission_text,
                            "attachment": verified_attachment,
                        })
                        input_record = dict(ingested.get("input") or {})
                        conversation = handle_telegram_conversation(
                            submission_text,
                            telegram_chat_id=chat_id,
                            telegram_message_id=int(message["message_id"]),
                            input_record=input_record,
                            has_attachment=True,
                            progress_callback=reporter,
                        )
                        reply = _chat_reply(conversation)
                    except Exception as exc:
                        reporter.blocker(f"{type(exc).__name__}: {str(exc)[:900]}")
                        reply = f"COMMAND=FAIL\n{type(exc).__name__}: {str(exc)[:1200]}"
                        print(
                            f"TELEGRAM_FILE_SUBMISSION=FAIL USER_ID={user_id} ERROR={type(exc).__name__}",
                            flush=True,
                        )
                    else:
                        print(
                            f"TELEGRAM_FILE_SUBMISSION=PASS USER_ID={user_id} "
                            f"KIND={verified_attachment.get('media_kind')}",
                            flush=True,
                        )
                    finally:
                        reporter.stop()
                    api.send(chat_id, reply)
                    continue

                if not text:
                    continue

                api.typing(chat_id)
                try:
                    if text.startswith("/"):
                        reply = _execute_command(text, chat_id=chat_id)
                        command_name = text.split()[0]
                    else:
                        ingested = ingest_telegram_input_under_harness({
                            "telegram_user_id": user_id,
                            "telegram_chat_id": chat_id,
                            "telegram_message_id": int(message["message_id"]),
                            "telegram_update_id": update_id,
                            "input_kind": "text",
                            "text": text,
                        })
                        input_record = dict(ingested.get("input") or {})
                        reporter = TelegramProgressReporter(api, chat_id)
                        reporter.start()
                        try:
                            conversation = handle_telegram_conversation(
                                text,
                                telegram_chat_id=chat_id,
                                telegram_message_id=int(message["message_id"]),
                                input_record=input_record,
                                progress_callback=reporter,
                            )
                        except Exception as exc:
                            reporter.blocker(f"{type(exc).__name__}: {str(exc)[:900]}")
                            raise
                        finally:
                            reporter.stop()
                        reply = _chat_reply(conversation)
                        command_name = "natural-language"
                except Exception as exc:  # command boundary: never crash the listener
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
