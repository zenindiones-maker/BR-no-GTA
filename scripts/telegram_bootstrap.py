from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


API_BASE = "https://api.telegram.org"
EXPECTED_MESSAGES = {"oi harness", "/start"}


def _token() -> str:
    value = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not value:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    return value


def _api(method: str, *, payload: dict[str, object] | None = None) -> dict:
    token = _token()
    url = f"{API_BASE}/bot{token}/{method}"
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never include the request URL because it contains the bot token.
        raise RuntimeError(f"Telegram API HTTP {exc.code} for {method}") from exc
    if not isinstance(body, dict) or body.get("ok") is not True:
        description = body.get("description") if isinstance(body, dict) else "invalid response"
        raise RuntimeError(f"Telegram API rejected {method}: {description}")
    return body


def _select_message(updates: list[dict]) -> tuple[dict, dict]:
    candidates: list[tuple[dict, dict]] = []
    for update in updates:
        if not isinstance(update, dict):
            continue
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            continue
        if chat.get("type") != "private":
            continue
        if sender.get("is_bot") is True:
            continue
        text = str(message.get("text") or "").strip().lower()
        if text in EXPECTED_MESSAGES:
            candidates.append((update, message))

    if not candidates:
        raise RuntimeError(
            "No private /start or 'oi harness' message found. Send 'oi harness' to @Brnogta_bot and rerun."
        )
    return candidates[-1]


def main() -> int:
    response = _api("getUpdates")
    raw_updates = response.get("result")
    if not isinstance(raw_updates, list):
        raise RuntimeError("Telegram getUpdates result is not a list")

    update, message = _select_message(raw_updates)
    sender = message["from"]
    chat = message["chat"]

    user_id = int(sender["id"])
    chat_id = int(chat["id"])
    update_id = int(update["update_id"])
    username = str(sender.get("username") or "")

    # Deliberately print only non-secret bootstrap identity metadata.
    print("TELEGRAM_BOOTSTRAP=FOUND")
    print(f"TELEGRAM_USER_ID={user_id}")
    print(f"TELEGRAM_CHAT_ID={chat_id}")
    print(f"TELEGRAM_USERNAME={username or 'sem_username'}")
    print(f"TELEGRAM_UPDATE_ID={update_id}")

    _api(
        "sendMessage",
        payload={
            "chat_id": chat_id,
            "text": (
                "BR no GTA: conexão do bot com o runtime cloud confirmada. "
                "Sua mensagem chegou com sucesso. O ingress do DeepSeek Harness está sendo habilitado agora."
            ),
        },
    )
    print("TELEGRAM_REPLY=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # bootstrap must fail closed with a concise message
        print(f"TELEGRAM_BOOTSTRAP=FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
