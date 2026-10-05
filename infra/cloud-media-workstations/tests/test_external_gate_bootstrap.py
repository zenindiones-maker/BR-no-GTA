from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_provisioner_policy_is_region_and_project_scoped() -> None:
    text = read("bootstrap/auth/provisioner-policy.json")
    assert '"aws:RequestedRegion"' in text
    assert '"sa-east-1"' in text
    assert '"aws:RequestTag/ManagedBy"' in text
    assert '"OpenTofu"' in text
    assert '"iam:CreateUser"' not in text
    assert '"iam:CreateAccessKey"' not in text
    assert '"Action": "*"' not in text


def test_provisioner_policy_limits_ssm_to_workstation_namespace() -> None:
    text = read("bootstrap/auth/provisioner-policy.json")
    assert "parameter/cloud-media-workstations/*" in text
    assert '"ssm:PutParameter"' in text
    assert '"ssm:GetParameter"' in text


def test_aws_cli_bootstrap_is_session_local_and_does_not_write_credentials() -> None:
    text = read("scripts/bootstrap-aws-auth.sh")
    assert "aws configure sso" in text
    assert "aws sts get-caller-identity" in text
    assert "AWS_ACCESS_KEY_ID" not in text
    assert "AWS_SECRET_ACCESS_KEY" not in text
    assert "~/.aws/credentials" not in text


def test_external_gate_verifier_checks_sts_budget_backend_and_project_secrets() -> None:
    text = read("scripts/verify-external-gates.sh")
    for required in (
        "aws sts get-caller-identity",
        "MONTHLY_BUDGET_USD",
        "BUDGET_EMAIL",
        "TF_BACKEND_CONFIG",
        "/cloud-media-workstations/hazewave/tailscale-auth-key",
        "/cloud-media-workstations/br-no-gta/tailscale-auth-key",
        "SecureString",
    ):
        assert required in text


def test_state_backend_uses_s3_native_lockfile_and_encryption() -> None:
    for project in ("hazewave", "br-no-gta"):
        text = read(f"stacks/{project}/backend.hcl.example")
        assert "encrypt = true" in text
        assert "use_lockfile = true" in text
    state = read("bootstrap/state/main.tf")
    assert 'status = "Enabled"' in state
    assert 'sse_algorithm = "AES256"' in state


def test_external_gate_runbook_keeps_apply_separate_from_auth() -> None:
    text = read("docs/aws-external-gates.md")
    assert "PHASE 1 — AUTH ONLY" in text
    assert "PHASE 5 — PLAN ONLY" in text
    assert "PHASE 6 — APPLY" in text
    assert "Do not run PHASE 6" in text


def test_safe_build_lints_new_gate_scripts() -> None:
    text = read("scripts/verify-safe-build")
    assert "bootstrap-aws-auth.sh" in text
    assert "verify-external-gates.sh" in text
