#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${1:-}"
case "$PROJECT" in
  hazewave) GROUP=hazewave; PLAYBOOK=hazewave.yml ;;
  br-no-gta) GROUP=br_no_gta; PLAYBOOK=br-no-gta.yml ;;
  *) echo "usage: $0 {hazewave|br-no-gta}" >&2; exit 2 ;;
esac

: "${MONTHLY_BUDGET_USD:?MONTHLY_BUDGET_USD_UNSET}"
: "${TF_BACKEND_CONFIG:?TF_BACKEND_CONFIG_UNSET}"
: "${NVIDIA_DRIVER_S3_URI:?NVIDIA_DRIVER_S3_URI_UNSET}"
: "${NVIDIA_DRIVER_SHA256:?NVIDIA_DRIVER_SHA256_UNSET}"

TOFU="$HOME/.local/bin/tofu"
VENV="$HOME/.local/share/cloud-media-workstations-venv"
STACK="$ROOT/stacks/$PROJECT"
cd "$STACK"
"$TOFU" init -input=false -backend-config="$TF_BACKEND_CONFIG" >/dev/null
INSTANCE_ID="$("$TOFU" output -raw instance_id)"
DATA_VOLUME_ID="$("$TOFU" output -raw data_volume_id)"
PROJECT_BUCKET="$("$TOFU" output -raw project_bucket)"

cleanup() {
  set +e
  "$VENV/bin/python" "$ROOT/scripts/workstationctl.py" "$PROJECT" STOP >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" "$PROJECT" START

for _ in $(seq 1 60); do
  online="$(aws ssm describe-instance-information --region sa-east-1 --filters "Key=InstanceIds,Values=$INSTANCE_ID" --query "InstanceInformationList[0].PingStatus" --output text 2>/dev/null || true)"
  [ "$online" = "Online" ] && break
  sleep 5
done
if [ "${online:-}" != "Online" ]; then
  echo "BLOCKED_AWS_AUTH_OR_SSM:SSM_OFFLINE" >&2
  exit 2
fi

INVENTORY="$(mktemp)"
trap 'rm -f "$INVENTORY"; cleanup' EXIT INT TERM
cat >"$INVENTORY" <<EOF
[$GROUP]
$INSTANCE_ID ansible_host=$INSTANCE_ID ansible_connection=amazon.aws.aws_ssm ansible_aws_ssm_region=sa-east-1 ansible_aws_ssm_bucket_name=$PROJECT_BUCKET
EOF

cd "$ROOT"
"$VENV/bin/ansible-playbook" \
  -i "$INVENTORY" \
  "ansible/$PLAYBOOK" \
  -e "data_volume_id=$DATA_VOLUME_ID" \
  -e "nvidia_driver_s3_uri=$NVIDIA_DRIVER_S3_URI" \
  -e "nvidia_driver_sha256=$NVIDIA_DRIVER_SHA256" \
  -e "project_bucket_name=$PROJECT_BUCKET"

"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" "$PROJECT" CONNECT_READY
echo "CONFIGURATION_RUNTIME_PROOF=PASS"
echo "FINAL_STOP=DEFERRED_TO_EXIT_TRAP"
