from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_preflight_queries_identity_region_quota_capacity_and_pricing() -> None:
    text = read("scripts/aws_preflight.py")
    for needle in (
        "sts.get_caller_identity",
        "service-quotas",
        "describe_instance_type_offerings",
        "describe_instance_types",
        "pricing",
        "AmazonEC2",
        "AmazonEC2CurrentGeneration",
        "CostEvidence/v1",
    ):
        assert needle in text


def test_preflight_is_fixed_to_sa_east_1_and_target_instance_types() -> None:
    text = read("scripts/aws_preflight.py")
    assert 'REGION = "sa-east-1"' in text
    assert '"g6f.2xlarge"' in text
    assert '"g6.2xlarge"' in text


def test_preflight_never_claims_capacity_from_offering_only() -> None:
    text = read("scripts/aws_preflight.py")
    assert "AZ_OFFERING_NOT_CAPACITY_GUARANTEE" in text
    assert "BLOCKED_CAPACITY_UNPROVEN" in text


def test_monthly_budget_is_required_before_deploy_script_apply() -> None:
    text = read("scripts/provision.sh")
    assert "MONTHLY_BUDGET_USD_UNSET" in text
    assert "TF_VAR_monthly_budget_usd" in text
    assert "deploy_resources=true" in text


def test_ssm_tailscale_parameter_is_project_scoped_and_not_plaintext_in_state() -> None:
    tf = read("modules/workstation/main.tf")
    vars_tf = read("modules/workstation/variables.tf")
    assert "tailscale_auth_key_ssm_parameter" in vars_tf
    assert "ssm:GetParameter" in tf
    assert "kms:Decrypt" in tf
    assert "aws_ssm_parameter" not in tf


def test_budget_action_is_automatic_stop_not_notification_only() -> None:
    tf = read("modules/workstation/main.tf")
    assert 'action_type        = "RUN_SSM_DOCUMENTS"' in tf
    assert 'approval_model     = "AUTOMATIC"' in tf
    assert 'action_sub_type = "STOP_EC2_INSTANCES"' in tf


def test_default_plan_is_non_chargeable() -> None:
    for stack in ("hazewave", "br-no-gta"):
        vars_text = read(f"stacks/{stack}/variables.tf")
        assert "default     = false" in vars_text
        assert "default     = null" in vars_text
