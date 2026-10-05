#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${1:-}"
case "$PROJECT" in
  hazewave|br-no-gta) ;;
  *) echo "usage: $0 {hazewave|br-no-gta}" >&2; exit 2 ;;
esac

: "${MONTHLY_BUDGET_USD:?MONTHLY_BUDGET_USD_UNSET}"
: "${BUDGET_EMAIL:?BUDGET_EMAIL_UNSET}"
: "${TF_BACKEND_CONFIG:?TF_BACKEND_CONFIG_UNSET}"

export TF_VAR_monthly_budget_usd="$MONTHLY_BUDGET_USD"
export TF_VAR_budget_email="$BUDGET_EMAIL"
export TF_VAR_deploy_resources=true

STATE_DIR="$ROOT/.runtime/$PROJECT"
mkdir -p "$STATE_DIR"
PREFLIGHT_RECEIPT="$STATE_DIR/aws-preflight.json"

emergency_stop() {
  set +e
  ids="$(aws ec2 describe-instances \
    --region sa-east-1 \
    --filters \
      "Name=tag:Project,Values=$PROJECT" \
      "Name=tag:Purpose,Values=persistent-media-workstation" \
      "Name=instance-state-name,Values=pending,running" \
    --query 'Reservations[].Instances[].InstanceId' \
    --output text 2>/dev/null)"
  if [ -n "$ids" ] && [ "$ids" != "None" ]; then
    aws ec2 stop-instances --region sa-east-1 --instance-ids $ids >/dev/null 2>&1 || true
    echo "EMERGENCY_STOP_ATTEMPTED=$ids" >&2
  fi
}
trap emergency_stop ERR INT TERM

PYTHONPATH="$ROOT/runtime" \
  "$HOME/.local/share/cloud-media-workstations-venv/bin/python" \
  "$ROOT/scripts/aws_preflight.py" | tee "$PREFLIGHT_RECEIPT"

python3 - "$PREFLIGHT_RECEIPT" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
if p.get("monthly_budget_status") != "SET":
    raise SystemExit("MONTHLY_BUDGET_USD_UNSET")
if p.get("region") != "sa-east-1":
    raise SystemExit("REGION_MUST_BE_SA_EAST_1")
if p.get("gpu_quota",{}).get("available_vcpus",0) < 16:
    raise SystemExit("BLOCKED_GPU_QUOTA")
print("AWS_PREFLIGHT=PASS")
print("BLOCKED_CAPACITY_UNPROVEN=EXPECTED_UNTIL_RUN_INSTANCES")
PY

SSM_PARAMETER="/cloud-media-workstations/$PROJECT/tailscale-auth-key"
parameter_type="$(aws ssm get-parameter \
  --region sa-east-1 \
  --name "$SSM_PARAMETER" \
  --query 'Parameter.Type' \
  --output text)"
if [ "$parameter_type" != "SecureString" ]; then
  echo "BLOCKED_TAILSCALE_SECRET: expected SecureString at $SSM_PARAMETER" >&2
  exit 2
fi

STACK="$ROOT/stacks/$PROJECT"
TOFU="$HOME/.local/bin/tofu"
cd "$STACK"
"$TOFU" init -input=false -backend-config="$TF_BACKEND_CONFIG"
"$TOFU" plan -input=false \
  -var='deploy_resources=true' \
  -var="monthly_budget_usd=$MONTHLY_BUDGET_USD" \
  -var="budget_email=$BUDGET_EMAIL" \
  -out="$STATE_DIR/plan.tfplan"
"$TOFU" apply -input=false "$STATE_DIR/plan.tfplan"

instance_id="$("$TOFU" output -raw instance_id)"
state="$(aws ec2 describe-instances \
  --region sa-east-1 \
  --instance-ids "$instance_id" \
  --query 'Reservations[0].Instances[0].State.Name' \
  --output text)"

if [ "$state" != "stopped" ]; then
  aws ec2 stop-instances --region sa-east-1 --instance-ids "$instance_id" >/dev/null
  aws ec2 wait instance-stopped --region sa-east-1 --instance-ids "$instance_id"
fi

trap - ERR INT TERM
echo "PROVISIONED_PROJECT=$PROJECT"
echo "INSTANCE_ID=$instance_id"
echo "FINAL_STATE=STOPPED"
