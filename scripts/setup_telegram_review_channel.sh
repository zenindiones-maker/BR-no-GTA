#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HOME}/.local/state/br-no-gta"
SECRET_FILE="${HOME}/.config/br-no-gta/telegram.env"
CONTROL_STATE="${STATE_DIR}/telegram-control.json"
REVIEW_ENV="${HOME}/.config/br-no-gta/telegram-review.env"
MAINTENANCE_FILE="${STATE_DIR}/telegram-gateway.maintenance"
REPO="${GITHUB_ACTIONS_REPOSITORY:-zenindiones-maker/BR-no-GTA}"
PYTHON_BIN="${ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python)"
fi

if [[ ! -r "${SECRET_FILE}" ]]; then
  echo "TELEGRAM_REVIEW_SETUP=FAIL missing ${SECRET_FILE}" >&2
  exit 1
fi
if [[ ! -r "${CONTROL_STATE}" ]]; then
  echo "TELEGRAM_REVIEW_SETUP=FAIL Telegram control state not found; pair the private bot first" >&2
  exit 1
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "TELEGRAM_REVIEW_SETUP=FAIL gh CLI is required" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${SECRET_FILE}"
export TELEGRAM_BOT_TOKEN
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "TELEGRAM_REVIEW_SETUP=FAIL empty TELEGRAM_BOT_TOKEN" >&2
  exit 1
fi

ALLOWED_USER_ID="$(${PYTHON_BIN} - "${CONTROL_STATE}" <<'PY'
import json, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = state.get("allowed_user_id")
if not isinstance(value, int) or value <= 0:
    raise SystemExit("allowed_user_id missing")
print(value)
PY
)"
export TELEGRAM_ALLOWED_USER_ID="${ALLOWED_USER_ID}"

PAIR_CODE="BRREVIEW-$(${PYTHON_BIN} - <<'PY'
import secrets
print(secrets.token_hex(4).upper())
PY
)"
export TELEGRAM_REVIEW_PAIR_CODE="${PAIR_CODE}"

cd "${ROOT}"

# Pairing temporarily owns Telegram getUpdates. Keep the persistence supervisor
# from relaunching the normal gateway while this script is listening.
: > "${MAINTENANCE_FILE}"
cleanup_pairing() {
  rm -f "${MAINTENANCE_FILE}" 2>/dev/null || true
  bash scripts/telegram_termux_control.sh start >/dev/null 2>&1 || true
}
trap cleanup_pairing EXIT INT TERM

bash scripts/telegram_termux_control.sh stop >/dev/null 2>&1 || true

cat <<EOF
TELEGRAM_REVIEW_SETUP=WAITING

No Telegram:
1. Crie um canal privado ou grupo privado chamado: BR no GTA — Revisão
2. Adicione @Brnogta_bot como administrador com permissão para publicar mensagens.
3. Nesse canal/grupo, envie exatamente:

/review_here ${PAIR_CODE}

Aguardando por até 3 minutos...
EOF

PAIR_JSON="$(${PYTHON_BIN} - <<'PY'
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
ALLOWED_USER_ID = int(os.environ["TELEGRAM_ALLOWED_USER_ID"])
PAIR_CODE = os.environ["TELEGRAM_REVIEW_PAIR_CODE"].strip()
BASE = f"https://api.telegram.org/bot{TOKEN}"
EXPECTED = f"/review_here {PAIR_CODE}".casefold()


def call(method: str, payload: dict[str, str] | None = None, timeout: int = 40):
    request = urllib.request.Request(
        f"{BASE}/{method}",
        data=urllib.parse.urlencode(payload or {}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(str(body.get("description") or body))
    return body.get("result")


me = call("getMe", timeout=20)
bot_id = int(me["id"])
start = time.time()
offset = 0
conflicts = 0
while time.time() - start < 180:
    try:
        updates = call(
            "getUpdates",
            {
                "offset": str(offset),
                "timeout": "20",
                "allowed_updates": json.dumps(["message", "channel_post"]),
            },
            timeout=30,
        ) or []
    except urllib.error.HTTPError as exc:
        # A just-killed long poll may remain registered briefly at Telegram.
        # During maintenance no new local gateway can start, so retrying here
        # safely drains that stale request instead of aborting the setup.
        if exc.code == 409:
            conflicts += 1
            if conflicts == 1:
                print(
                    "TELEGRAM_REVIEW_SETUP=DRAINING_STALE_GETUPDATES",
                    file=sys.stderr,
                    flush=True,
                )
            time.sleep(2)
            continue
        raise

    conflicts = 0
    for update in updates:
        update_id = int(update.get("update_id") or 0)
        offset = max(offset, update_id + 1)
        message = update.get("message") or update.get("channel_post")
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "").strip().casefold()
        if text != EXPECTED:
            continue
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        chat_type = str(chat.get("type") or "")
        if not isinstance(chat_id, int) or chat_type not in {"group", "supergroup", "channel"}:
            continue
        sender = message.get("from") or {}
        if update.get("message") is not None:
            if int(sender.get("id") or 0) != ALLOWED_USER_ID:
                continue
        membership = call(
            "getChatMember",
            {"chat_id": str(chat_id), "user_id": str(bot_id)},
            timeout=20,
        ) or {}
        if membership.get("status") not in {"administrator", "creator"}:
            raise SystemExit("bot is not administrator in review destination")
        print(
            json.dumps(
                {
                    "chat_id": chat_id,
                    "chat_type": chat_type,
                    "title": chat.get("title") or "BR no GTA — Revisão",
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(0)
raise SystemExit("review destination pairing timed out")
PY
)"

REVIEW_CHAT_ID="$(${PYTHON_BIN} -c 'import json,sys; print(json.loads(sys.stdin.read())["chat_id"])' <<<"${PAIR_JSON}")"
REVIEW_CHAT_TYPE="$(${PYTHON_BIN} -c 'import json,sys; print(json.loads(sys.stdin.read())["chat_type"])' <<<"${PAIR_JSON}")"
REVIEW_TITLE="$(${PYTHON_BIN} -c 'import json,sys; print(json.loads(sys.stdin.read())["title"])' <<<"${PAIR_JSON}")"

umask 077
printf 'export TELEGRAM_REVIEW_CHAT_ID=%q\n' "${REVIEW_CHAT_ID}" > "${REVIEW_ENV}"
printf 'export TELEGRAM_REVIEW_CHAT_TYPE=%q\n' "${REVIEW_CHAT_TYPE}" >> "${REVIEW_ENV}"
chmod 600 "${REVIEW_ENV}"

gh variable set TELEGRAM_REVIEW_CHAT_ID --repo "${REPO}" --body "${REVIEW_CHAT_ID}" >/dev/null

rm -f "${MAINTENANCE_FILE}"
trap - EXIT INT TERM
bash scripts/telegram_termux_control.sh start >/dev/null

echo "TELEGRAM_REVIEW_SETUP=PASS"
echo "TELEGRAM_REVIEW_CHAT_TYPE=${REVIEW_CHAT_TYPE}"
echo "TELEGRAM_REVIEW_TITLE=${REVIEW_TITLE}"
echo "TELEGRAM_REVIEW_DESTINATION=SYNCED_TO_GITHUB_VARIABLE"
echo "RULE=Review delivery has no publication authority; public posting still requires br_youtube_pode_postar(publication_id)."
