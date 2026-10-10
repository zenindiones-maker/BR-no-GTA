#!/usr/bin/env bash
# Existing A15 control plane -> existing Codespace: ephemeral Telegram credentials.
# Credential bytes travel once over SSH stdin; never in argv, logs, git or disk.
set +x
set -euo pipefail
umask 077

case "$#" in
  1) ;;
  *) echo "ACTION_INVALID_EXPECT_VERIFY_TARGET_OR_SEND" >&2; exit 2 ;;
esac
case "$1" in
  --verify-target|--send) MODE="$1" ;;
  *) echo "ACTION_INVALID_EXPECT_VERIFY_TARGET_OR_SEND" >&2; exit 2 ;;
esac

CS="br-v23-recovery-gxp67g5g7wphwxjw"
REPO="zenindiones-maker/BR-no-GTA"
SHA="$BR_OWNER_AUDITED_SHA"
if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "AUDITED_COMMIT_NOT_EXACT_SHA" >&2
  exit 2
fi
if [[ ! -r "$HOME/.config/br-no-gta/telegram.env" ]]; then
  echo "LOCAL_TELEGRAM_TOKEN_SOURCE_MISSING" >&2
  exit 2
fi
# Canonical trusted owner-controlled Termux configuration already exists.
# Do not source anything copied from Codespace, a web request, or GitHub logs.
source "$HOME/.config/br-no-gta/telegram.env"
if [[ -r "$HOME/.config/br-no-gta/telegram-review.env" ]]; then
  source "$HOME/.config/br-no-gta/telegram-review.env"
fi
TELEGRAM_REVIEW_CHAT_ID="${TELEGRAM_REVIEW_CHAT_ID:-}"
if [[ -z "$TELEGRAM_REVIEW_CHAT_ID" ]]; then
  # Existing repository variable set by the authorized pairing helper.
  TELEGRAM_REVIEW_CHAT_ID="$(gh variable get TELEGRAM_REVIEW_CHAT_ID -R "$REPO" 2>/dev/null || true)"
fi
if [[ ! "${TELEGRAM_BOT_TOKEN:-}" =~ ^[0-9]{5,}:[A-Za-z0-9_-]{25,}$ ]]; then
  echo "LOCAL_BOT_TOKEN_INVALID_OR_MISSING" >&2
  exit 2
fi
if [[ ! "$TELEGRAM_REVIEW_CHAT_ID" =~ ^-[0-9]{5,20}$ ]]; then
  echo "LOCAL_PRIVATE_REVIEW_CHAT_ID_INVALID_OR_MISSING" >&2
  exit 2
fi
if ! gh api "/repos/$REPO/commits/$SHA" --jq '.sha' >/dev/null 2>&1; then
  echo "AUDITED_COMMIT_NOT_ACCESSIBLE" >&2
  exit 2
fi
# Never start a shut-down Codespace or allow a different repository.
DETAILS="$(gh api "/user/codespaces/$CS" --jq '[.repository.full_name,.state] | join(" ")')"
if [[ "$DETAILS" != "$REPO Available" && "$DETAILS" != "$REPO Running" ]]; then
  echo "EXISTING_CODESPACE_NOT_AVAILABLE_NO_AUTO_START" >&2
  exit 2
fi

# Probe stdin forwarding without sending secrets. gh codespace ssh accepts a
# noninteractive command and may forward a pipe as the remote stdin.
CANARY_CMD="$(cat <<'REMOTE'
bash -lc 'set -euo pipefail
IFS= read -r proof || exit 10
[[ "$proof" == "BR_NO_GTA_EPHEMERAL_STDIN_V1" ]] || exit 11
printf "SSH_STDIN_CANARY=PASS\n"
'
REMOTE
)"
CANARY="$(printf 'BR_NO_GTA_EPHEMERAL_STDIN_V1\n' | gh codespace ssh -c "$CS" -- "$CANARY_CMD")" || {
  echo "SSH_STDIN_PROBE_FAILED_NO_SECRETS_SENT" >&2
  exit 2
}
if [[ "$CANARY" != "SSH_STDIN_CANARY=PASS" ]]; then
  echo "SSH_STDIN_PROBE_UNVERIFIED_NO_SECRETS_SENT" >&2
  exit 2
fi
echo "$CANARY"

REMOTE_CMD="$(cat <<'REMOTE'
bash -lc 'set +x
set -euo pipefail
umask 077
if [[ "${CODESPACES:-}" != "true" ||
      "${CODESPACE_NAME:-}" != "br-v23-recovery-gxp67g5g7wphwxjw" ||
      "${GITHUB_REPOSITORY:-}" != "zenindiones-maker/BR-no-GTA" ]]; then
  echo "REMOTE_IDENTITY_DENIED" >&2
  exit 3
fi
IFS= read -r token || exit 4
IFS= read -r chat || exit 4
IFS= read -r sha || exit 4
IFS= read -r mode || exit 4
if [[ ! "$token" =~ ^[0-9]{5,}:[A-Za-z0-9_-]{25,}$ ||
      ! "$chat" =~ ^-[0-9]{5,20}$ ||
      ! "$sha" =~ ^[0-9a-f]{40}$ ||
      ( "$mode" != "--verify-target" && "$mode" != "--send" ) ]]; then
  echo "REMOTE_INPUT_CONTRACT_DENIED" >&2
  exit 4
fi
repo=""
for candidate in "${CODESPACE_VSCODE_FOLDER:-}" /workspaces/BR-no-GTA /workspaces/BR "$HOME/BR-no-GTA" "$HOME/BR" /home/codespace/BR-no-GTA /home/vscode/BR-no-GTA; do
  [[ -n "$candidate" ]] || continue
  if git -C "$candidate" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    repo="$(git -C "$candidate" rev-parse --show-toplevel)"
    break
  fi
done
if [[ -z "$repo" ]]; then
  echo "REMOTE_BR_REPOSITORY_NOT_FOUND" >&2
  exit 4
fi
cd "$repo"
git fetch --quiet --no-tags origin work/br-owner-voice-coherent-qa-recovery-v1
git merge-base --is-ancestor "$sha" FETCH_HEAD || {
  echo "PINNED_COMMIT_NOT_IN_AUTHORIZED_BRANCH" >&2; exit 5;
}
export TELEGRAM_BOT_TOKEN="$token"
export TELEGRAM_REVIEW_CHAT_ID="$chat"
unset token chat
git show "$sha:scripts/owner_voice_survey_telegram_delivery.py" | python3 - "$mode"
'
REMOTE
)"
echo "EPHEMERAL_CREDENTIAL_TRANSPORT=SSH_STDIN_ONLY"
echo "A15_AUDIO_PROCESSING=FORBIDDEN"
# Tokens/chat remain on the phone only in its EXISTING trusted config and
# travel ephemerally over encrypted SSH stdin. They never enter process argv.
printf '%s\n%s\n%s\n%s\n' "$TELEGRAM_BOT_TOKEN" "$TELEGRAM_REVIEW_CHAT_ID" "$SHA" "$MODE" |
  gh codespace ssh -c "$CS" -- "$REMOTE_CMD"
