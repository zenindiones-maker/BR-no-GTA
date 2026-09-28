#!/usr/bin/env bash
set -euo pipefail

oauth_token="${CLAUDE_CODE_OAUTH_TOKEN:-}"
api_key="${ANTHROPIC_API_KEY:-}"

if [[ -n "$oauth_token" && -n "$api_key" ]]; then
  echo "CLAUDE_CODE_AUTH=FAIL REASON=AMBIGUOUS_CREDENTIALS" >&2
  exit 2
fi

if [[ -z "$oauth_token" && -z "$api_key" ]]; then
  echo "CLAUDE_CODE_AUTH=FAIL REASON=MISSING_CREDENTIAL" >&2
  exit 2
fi

if [[ -n "$oauth_token" ]]; then
  auth_method="OAUTH_SUBSCRIPTION"
else
  auth_method="ANTHROPIC_API_KEY"
fi

if ! claude auth status >/dev/null 2>&1; then
  echo "CLAUDE_CODE_AUTH=FAIL REASON=AUTH_STATUS_REJECTED METHOD=$auth_method" >&2
  exit 1
fi

echo "CLAUDE_CODE_AUTH_METHOD=$auth_method"
echo "CLAUDE_CODE_AUTH_STATUS=PASS"
