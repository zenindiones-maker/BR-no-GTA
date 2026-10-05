#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-sa-east-1}"
PROFILE_ARGS=()
if [ -n "${AWS_PROFILE:-}" ]; then
  PROFILE_ARGS=(--profile "$AWS_PROFILE")
fi

command -v aws >/dev/null 2>&1 || { echo "BLOCKED_AWS_CLI_UNAVAILABLE" >&2; exit 2; }

aws sts get-caller-identity "${PROFILE_ARGS[@]}" --region "$REGION" >/dev/null
echo "STS=PASS"

: "${MONTHLY_BUDGET_USD:?MONTHLY_BUDGET_USD_UNSET}"
: "${BUDGET_EMAIL:?BUDGET_EMAIL_UNSET}"
: "${TF_BACKEND_CONFIG:?TF_BACKEND_CONFIG_UNSET}"

[ -r "$TF_BACKEND_CONFIG" ] || { echo "BLOCKED_BACKEND_CONFIG_NOT_READABLE" >&2; exit 2; }

case "$MONTHLY_BUDGET_USD" in
  ''|*[!0-9.]* ) echo "BLOCKED_INVALID_MONTHLY_BUDGET_USD" >&2; exit 2 ;;
esac

for parameter in   /cloud-media-workstations/hazewave/tailscale-auth-key   /cloud-media-workstations/br-no-gta/tailscale-auth-key
do
  parameter_type="$(aws ssm get-parameter     "${PROFILE_ARGS[@]}"     --region "$REGION"     --name "$parameter"     --query 'Parameter.Type'     --output text)"
  [ "$parameter_type" = "SecureString" ] || {
    echo "BLOCKED_TAILSCALE_SECRET:$parameter:expected=SecureString:actual=$parameter_type" >&2
    exit 2
  }
done

echo "MONTHLY_BUDGET_STATUS=SET"
echo "BUDGET_EMAIL_STATUS=SET"
echo "BACKEND_CONFIG=PASS"
echo "TAILSCALE_PROJECT_SCOPED_SECRETS=PASS"
echo "EXTERNAL_GATES=PASS"
