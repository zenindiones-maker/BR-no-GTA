from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_instance_role_can_read_only_project_tailscale_parameter() -> None:
    tf = read("modules/workstation/main.tf")
    assert "tailscale_auth_key_ssm_parameter_name" in tf
    assert "ssm:GetParameter" in tf
    assert "kms:Decrypt" in tf
    assert 'resource "aws_ssm_parameter" "tailscale_auth_key"' not in tf


def test_tailscale_parameter_name_is_project_specific() -> None:
    haze = read("stacks/hazewave/main.tf")
    br = read("stacks/br-no-gta/main.tf")
    assert 'tailscale_auth_key_ssm_parameter_name = "/cloud-media-workstations/hazewave/tailscale-auth-key"' in haze
    assert 'tailscale_auth_key_ssm_parameter_name = "/cloud-media-workstations/br-no-gta/tailscale-auth-key"' in br


def test_aws_preflight_fails_closed_and_queries_required_surfaces() -> None:
    text = read("scripts/aws_preflight.py")
    for token in (
        "get_caller_identity",
        "list_service_quotas",
        "describe_instance_type_offerings",
        "describe_instance_types",
        "get_products",
        "describe_volumes_modifications",
        "BLOCKED_AWS_AUTH",
        "BLOCKED_GPU_QUOTA",
        "BLOCKED_CAPACITY",
        "AWS_PRICE_EVIDENCE",
    ):
        assert token in text


def test_preflight_targets_sa_east_1_and_expected_instances() -> None:
    text = read("scripts/aws_preflight.py")
    assert '"sa-east-1"' in text
    assert '"g6f.2xlarge"' in text
    assert '"g6.2xlarge"' in text


def test_workstationctl_exposes_required_lifecycle_commands() -> None:
    text = read("scripts/workstationctl.py")
    for token in ("START", "STATUS", "CONNECT_READY", "STOP"):
        assert token in text
    assert "MONTHLY_BUDGET_USD_UNSET" in text
    assert "stop_instances" in text
    assert "start_instances" in text
    assert "describe_instance_status" in text


def test_workstationctl_never_terminates_instances() -> None:
    text = read("scripts/workstationctl.py")
    assert "terminate_instances" not in text
    assert "TerminateInstances" not in text


def test_cross_isolation_probe_tests_both_directions() -> None:
    text = read("scripts/cross_isolation_probe.py")
    assert "hazewave" in text
    assert "br-no-gta" in text
    assert "AccessDenied" in text
    assert "CROSS_PROJECT_STORAGE_ISOLATION=PASS" in text
