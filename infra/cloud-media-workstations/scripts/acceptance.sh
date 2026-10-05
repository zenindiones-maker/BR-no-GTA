#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/.local/share/cloud-media-workstations-venv"
: "${MONTHLY_BUDGET_USD:?MONTHLY_BUDGET_USD_UNSET}"

stop_both() {
  set +e
  "$VENV/bin/python" "$ROOT/scripts/workstationctl.py" hazewave STOP >/dev/null 2>&1 || true
  "$VENV/bin/python" "$ROOT/scripts/workstationctl.py" br-no-gta STOP >/dev/null 2>&1 || true
}
trap stop_both EXIT INT TERM

instance_id() {
  aws ec2 describe-instances --region sa-east-1 \
    --filters "Name=tag:Project,Values=$1" "Name=tag:Purpose,Values=persistent-media-workstation" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text
}

run_ssm() {
  local project="$1"; shift
  local command="$*"
  local iid; iid="$(instance_id "$project")"
  local cid
  cid="$(aws ssm send-command --region sa-east-1 --instance-ids "$iid" \
    --document-name AWS-RunShellScript \
    --parameters "commands=[\"$command\"]" \
    --query 'Command.CommandId' --output text)'
  aws ssm wait command-executed --region sa-east-1 --command-id "$cid" --instance-id "$iid"
  aws ssm get-command-invocation --region sa-east-1 --command-id "$cid" --instance-id "$iid" \
    --query '{Status:Status,Stdout:StandardOutputContent,Stderr:StandardErrorContent}' --output json
}

human_checkpoint() {
  local project="$1"
  local var="$2"
  if [ "${!var:-}" != "PASS" ]; then
    echo "HUMAN_MOONLIGHT_REAPER_CHECKPOINT_REQUIRED=$project" >&2
    echo "Set $var=PASS only after Moonlight audio + REAPER edit/save + interactive render are actually verified." >&2
    exit 3
  fi
}

echo '=== HAZEWAVE ACCEPTANCE ==='
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" hazewave START
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" hazewave CONNECT_READY
human_checkpoint hazewave HUMAN_HAZEWAVE_CHECKPOINT
run_ssm hazewave "test -f /srv/hazewave/acceptance/acceptance.rpp && test -f /srv/hazewave/acceptance/interactive-render.wav"
run_ssm hazewave "/usr/local/bin/reaper-render /srv/hazewave/acceptance/acceptance.rpp /srv/hazewave/acceptance/cli-render.wav > /srv/hazewave/acceptance/reaper-cli-receipt.json"
run_ssm hazewave "grep -q \"\\\"status\\\": \\\"PASS\\\"\" /srv/hazewave/acceptance/reaper-cli-receipt.json"
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" hazewave STOP
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" hazewave START
run_ssm hazewave "test -f /srv/hazewave/acceptance/acceptance.rpp && test -f /srv/hazewave/acceptance/cli-render.wav && test -f /srv/hazewave/acceptance/reaper-cli-receipt.json"
echo "HAZEWAVE_PERSISTENCE_AFTER_RESTART=PASS"
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" hazewave STOP

echo '=== BR-NO-GTA ACCEPTANCE ==='
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" br-no-gta START
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" br-no-gta CONNECT_READY
run_ssm br-no-gta "/usr/local/bin/workstation-gpu-proof /srv/br-no-gta/acceptance/gpu-proof"
human_checkpoint br-no-gta HUMAN_BR_CHECKPOINT
run_ssm br-no-gta "test -f /srv/br-no-gta/acceptance/acceptance.rpp && test -f /srv/br-no-gta/acceptance/interactive-render.wav"
run_ssm br-no-gta "/usr/local/bin/reaper-render /srv/br-no-gta/acceptance/acceptance.rpp /srv/br-no-gta/acceptance/cli-render.wav > /srv/br-no-gta/acceptance/reaper-cli-receipt.json"
run_ssm br-no-gta "grep -q \"\\\"status\\\": \\\"PASS\\\"\" /srv/br-no-gta/acceptance/reaper-cli-receipt.json"
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" br-no-gta STOP
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" br-no-gta START
run_ssm br-no-gta "test -f /srv/br-no-gta/acceptance/acceptance.rpp && test -f /srv/br-no-gta/acceptance/cli-render.wav && test -f /srv/br-no-gta/acceptance/reaper-cli-receipt.json"
echo "BR_PERSISTENCE_AFTER_RESTART=PASS"
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" br-no-gta STOP

echo '=== CROSS-PROJECT ISOLATION ==='
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" hazewave START
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" br-no-gta START
"$VENV/bin/python" "$ROOT/scripts/cross_isolation_probe.py"
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" hazewave STOP
"$VENV/bin/python" "$ROOT/scripts/workstationctl.py" br-no-gta STOP

for project in hazewave br-no-gta; do
  state="$(aws ec2 describe-instances --region sa-east-1 --instance-ids "$(instance_id "$project")" --query "Reservations[0].Instances[0].State.Name" --output text)"
  if [ "$state" != "stopped" ]; then
    echo "FINAL_STATE=FAIL:$project:$state" >&2
    exit 4
  fi
done

echo "PERSISTENCE_AFTER_RESTART=PASS"
echo "FINAL_STATE=STOPPED"
echo "CLOUD_MEDIA_WORKSTATIONS_ACCEPTANCE=PASS"
