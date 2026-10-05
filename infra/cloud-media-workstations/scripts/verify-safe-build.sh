#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/.local/share/cloud-media-workstations-venv"
TOFU="$HOME/.local/bin/tofu"

cd "$ROOT"

echo "=== PYTEST ==="
"$VENV/bin/pytest" -q

echo "=== PY COMPILE ==="
PYTHONPATH=runtime "$VENV/bin/python" -m py_compile   scripts/aws_preflight.py   scripts/driver_discovery.py   scripts/workstationctl.py   scripts/cross_isolation_probe.py   scripts/reaper_render.py   scripts/workstation_autostop.py

echo "=== BASH SYNTAX ==="
bash -n   scripts/provision.sh   scripts/configure.sh   scripts/acceptance.sh   scripts/workstation-backup   scripts/workstation-gpu-proof   scripts/workstation-connect-ready-proof

echo "=== ANSIBLE SYNTAX ==="
"$VENV/bin/ansible-playbook" --syntax-check   -i ansible/inventory.example.ini ansible/hazewave.yml
"$VENV/bin/ansible-playbook" --syntax-check   -i ansible/inventory.example.ini ansible/br-no-gta.yml

echo "=== TOFU FORMAT / INIT / VALIDATE ==="
"$TOFU" fmt -recursive
"$TOFU" fmt -check -recursive
for stack in hazewave br-no-gta; do
  cd "$ROOT/stacks/$stack"
  "$TOFU" init -backend=false -input=false
  "$TOFU" validate
done
cd "$ROOT"

echo "=== SECRET SCAN ==="
PYTHONPATH=runtime "$VENV/bin/python" scripts/secret_scan.py

echo "CLOUD_MEDIA_WORKSTATIONS_SAFE_BUILD_GATE=PASS"
