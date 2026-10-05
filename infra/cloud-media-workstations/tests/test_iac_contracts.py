from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_two_stacks_have_independent_backend_keys() -> None:
    haze = read("stacks/hazewave/backend.hcl.example")
    br = read("stacks/br-no-gta/backend.hcl.example")
    assert "hazewave/terraform.tfstate" in haze
    assert "br-no-gta/terraform.tfstate" in br
    assert haze != br


def test_hazewave_targets_g6f_with_required_storage() -> None:
    text = read("stacks/hazewave/main.tf")
    assert '"g6f.2xlarge"' in text
    assert "root_volume_gib" in text and "= 80" in text
    assert "data_volume_gib" in text and "= 250" in text
    assert '"/srv/hazewave"' in text


def test_br_targets_full_l4_g6_with_required_storage() -> None:
    text = read("stacks/br-no-gta/main.tf")
    assert '"g6.2xlarge"' in text
    assert "root_volume_gib" in text and "= 100" in text
    assert "data_volume_gib" in text and "= 500" in text
    assert '"/srv/br-no-gta"' in text


def test_spot_is_not_used() -> None:
    all_tf = "\n".join(p.read_text(encoding="utf-8") for p in ROOT.rglob("*.tf"))
    assert "spot_instance_request" not in all_tf
    assert 'market_type = "spot"' not in all_tf
    assert "aws_spot" not in all_tf


def test_security_group_defines_no_ingress_rules() -> None:
    text = read("modules/workstation/main.tf")
    assert "aws_vpc_security_group_ingress_rule" not in text
    assert "ingress {" not in text


def test_compute_is_fail_closed_without_budget() -> None:
    text = read("modules/workstation/main.tf")
    assert 'error_message = "MONTHLY_BUDGET_USD_UNSET"' in text
    assert "var.monthly_budget_usd != null" in text
    assert "depends_on = [aws_budgets_budget_action.stop_instance]" in text


def test_each_project_gets_own_role_bucket_volume_and_log_group() -> None:
    text = read("modules/workstation/main.tf")
    assert '"${var.project_slug}-media-workstation"' in text
    assert 'bucket = var.project_bucket_name' in text
    assert '"${var.project_slug}-media-data"' in text
    assert '"/cloud-media-workstations/${var.project_slug}"' in text


def test_data_volume_is_encrypted_and_not_delete_on_stop() -> None:
    text = read("modules/workstation/main.tf")
    assert "encrypted         = true" in text
    assert "aws_ebs_volume" in text
    assert "delete_on_termination = false" in text


def test_snapshot_policy_is_tag_scoped_per_project() -> None:
    text = read("modules/workstation/main.tf")
    assert "aws_dlm_lifecycle_policy" in text
    assert 'Project = var.project_slug' in text
    assert 'BackupClass = "media-data"' in text


def test_bucket_policy_explicitly_denies_other_workstation_role() -> None:
    text = read("modules/workstation/main.tf")
    assert "DenyCrossProjectWorkstation" in text
    assert "var.denied_workstation_role_name" in text


def test_stack_defaults_do_not_create_chargeable_resources() -> None:
    for stack in ("hazewave", "br-no-gta"):
        text = read(f"stacks/{stack}/variables.tf")
        assert 'variable "deploy_resources"' in text
        assert "default     = false" in text
        assert 'variable "monthly_budget_usd"' in text
        assert "default     = null" in text


def test_runtime_bootstrap_uses_ssm_not_public_ssh() -> None:
    text = read("modules/workstation/main.tf")
    assert "AmazonSSMManagedInstanceCore" in text
    assert "22" not in read("modules/workstation/network.tf")
