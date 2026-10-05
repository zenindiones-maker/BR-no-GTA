from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_state_bootstrap_creates_private_versioned_encrypted_bucket() -> None:
    text = read("bootstrap/state/main.tf")
    assert "aws_s3_bucket" in text
    assert "aws_s3_bucket_versioning" in text
    assert "aws_s3_bucket_server_side_encryption_configuration" in text
    assert "aws_s3_bucket_public_access_block" in text
    assert "prevent_destroy = true" in text


def test_each_stack_declares_s3_backend_with_lockfile() -> None:
    for stack in ("hazewave", "br-no-gta"):
        versions = read(f"stacks/{stack}/versions.tf")
        backend = read(f"stacks/{stack}/backend.hcl.example")
        assert 'backend "s3"' in versions
        assert "use_lockfile = true" in backend
    assert "hazewave/terraform.tfstate" in read("stacks/hazewave/backend.hcl.example")
    assert "br-no-gta/terraform.tfstate" in read("stacks/br-no-gta/backend.hcl.example")


def test_backup_only_uploads_canonical_source_and_masters_without_delete() -> None:
    script = read("scripts/workstation-backup")
    assert '"$MOUNT/source"' in script
    assert '"$MOUNT/masters"' in script
    assert "aws s3 sync" in script
    assert "--delete" not in script
    assert "PROJECT_BUCKET" in script


def test_backup_timer_is_installed_and_enabled() -> None:
    tasks = read("ansible/roles/workstation_common/tasks/main.yml")
    timer = read("ansible/roles/workstation_common/templates/workstation-backup.timer.j2")
    assert "workstation-backup.timer" in tasks
    assert "enabled: true" in tasks
    assert "OnCalendar=" in timer


def test_backup_role_receives_only_own_project_bucket() -> None:
    tasks = read("ansible/roles/workstation_common/tasks/main.yml")
    assert "project_bucket_name" in tasks
    haze = read("stacks/hazewave/main.tf")
    br = read("stacks/br-no-gta/main.tf")
    assert "cloud-media-hazewave-" in haze
    assert "cloud-media-br-no-gta-" in br
