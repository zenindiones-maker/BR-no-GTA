from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.main import initialize_application


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


class TelegramApi:
    def __init__(self, token: str) -> None:
        token = token.strip()
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self._base_url = f"{API_ROOT}{token}"

    def call(self, method: str, payload: dict[str, Any] | None = None, *, timeout: int = 20) -> Any:
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

    def send(self, chat_id: int, text: str) -> None:
        rendered = text.strip() or "OK"
        if len(rendered) > MAX_REPLY_CHARS:
            rendered = rendered[: MAX_REPLY_CHARS - 90] + "\n\n[resposta truncada no Telegram; evidência completa permanece no sistema]"
        self.call("sendMessage", {"chat_id": str(chat_id), "text": rendered})


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
        "Comandos:\n"
        "/status — observação operacional\n"
        "/memoria <consulta> — Knowledge Brain\n"
        "/produzir <goal_id> — avança o Goal exato pelo Harness\n"
        "/preview <publication_id> — readiness da publicação\n"
        "/upload <publication_id> — despacha upload privado no cloud\n"
        "/upload_status <publication_id> — reconcilia upload privado\n"
        "/pode_postar <publication_id> — aprovação explícita para tornar público\n"
        "/publicacao_status <publication_id> — reconcilia visibilidade pública\n"
        "/help — mostra este menu\n\n"
        "O Telegram é somente ingress/control surface. Render, mídia e upload pesado continuam no cloud."
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


def _execute_command(text: str) -> str:
    from app.integrations.deepseek_harness import server

    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", 1)[0].casefold()

    if command in {"/start", "/help", "/ajuda"}:
        return _help_text()

    if command in {"/status", "/observe"}:
        return _render_result(server.br_observe())

    if command in {"/memoria", "/memory"}:
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("uso: /memoria <consulta>")
        return _render_result(server.br_knowledge_query(parts[1].strip()))

    if command in {"/produzir", "/execute"}:
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("uso: /produzir <goal_id>")
        goal_id = parts[1].strip()
        return _render_result(server.br_execution_process_next(goal_id=goal_id))

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


def _private_message(update: dict[str, Any]) -> tuple[int, int, str] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    sender = message.get("from")
    text = message.get("text")
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    if not isinstance(sender, dict) or not isinstance(text, str):
        return None
    try:
        return int(sender["id"]), int(chat["id"]), text.strip()
    except (KeyError, TypeError, ValueError):
        return None


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
                user_id, chat_id, text = parsed

                if allowed_user_id is None:
                    if text.casefold() != PAIR_TEXT:
                        continue
                    allowed_user_id = user_id
                    state["allowed_user_id"] = user_id
                    state["chat_id"] = chat_id
                    _save_state(state)
                    print(f"TELEGRAM_PAIRING=PASS USER_ID={user_id} CHAT_ID={chat_id}", flush=True)
                    api.send(
                        chat_id,
                        "BR-no-GTA conectado. Seu Telegram foi pareado como control surface do DeepSeek Harness.\n\n"
                        + _help_text(),
                    )
                    continue

                if user_id != allowed_user_id:
                    print(f"TELEGRAM_REJECTED_USER_ID={user_id}", flush=True)
                    continue

                if not text.startswith("/"):
                    api.send(chat_id, "Harness online. Envie /help para ver os comandos.")
                    continue

                try:
                    reply = _execute_command(text)
                except Exception as exc:  # command boundary: never crash the listener
                    reply = f"COMMAND=FAIL\n{type(exc).__name__}: {str(exc)[:1200]}"
                    print(
                        f"TELEGRAM_COMMAND=FAIL USER_ID={user_id} ERROR={type(exc).__name__}",
                        flush=True,
                    )
                else:
                    print(
                        f"TELEGRAM_COMMAND=PASS USER_ID={user_id} COMMAND={text.split()[0]}",
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
