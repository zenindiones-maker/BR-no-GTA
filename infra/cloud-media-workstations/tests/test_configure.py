from __future__ import annotations

from pathlib import Path

import pytest

from workstation_runtime.configure import (
    ConfigurationFailed,
    build_ansible_bundle,
    ssm_configuration_commands,
)


def test_bundle_is_deterministic_and_hash_bound(tmp_path: Path) -> None:
    root = tmp_path / "src"
    (root / "ansible").mkdir(parents=True)
    (root / "ansible" / "hazewave.yml").write_text("---\n", encoding="utf-8")
    (root / "ansible" / "requirements.yml").write_text("---\ncollections: []\n", encoding="utf-8")

    a = build_ansible_bundle(root=root, output=tmp_path / "a.tar.gz")
    b = build_ansible_bundle(root=root, output=tmp_path / "b.tar.gz")
    assert a.sha256 == b.sha256
    assert (tmp_path / "a.tar.gz").read_bytes() == (tmp_path / "b.tar.gz").read_bytes()


def test_ssm_configuration_has_no_ssh_or_plaintext_secrets() -> None:
    commands = ssm_configuration_commands(
        project="hazewave",
        bundle_s3_uri="s3://bucket/bootstrap/abc.tar.gz",
        bundle_sha256="a" * 64,
        data_volume_id="vol-0123",
        project_bucket_name="bucket",
        nvidia_driver_s3_uri="s3://ec2-linux-nvidia-drivers/latest/driver.run",
        nvidia_driver_sha256="b" * 64,
    )
    joined = "\n".join(commands)
    assert "ansible-playbook" in joined
    assert "hazewave.yml" in joined
    assert "data_volume_id=vol-0123" in joined
    assert "TAILSCALE_AUTH_KEY" not in joined
    assert "sunshine_password" not in joined
    assert "ssh " not in joined.lower()
    assert "aws s3 cp" in joined


def test_br_configuration_selects_only_br_playbook() -> None:
    joined = "\n".join(
        ssm_configuration_commands(
            project="br-no-gta",
            bundle_s3_uri="s3://bucket/bootstrap/abc.tar.gz",
            bundle_sha256="a" * 64,
            data_volume_id="vol-0456",
            project_bucket_name="bucket",
            nvidia_driver_s3_uri="s3://drivers/driver.run",
            nvidia_driver_sha256="b" * 64,
        )
    )
    assert "br-no-gta.yml" in joined
    assert "hazewave.yml" not in joined


def test_unknown_project_fails_closed() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_PROJECT"):
        ssm_configuration_commands(
            project="other",
            bundle_s3_uri="s3://x/x",
            bundle_sha256="a" * 64,
            data_volume_id="vol-x",
            project_bucket_name="x",
            nvidia_driver_s3_uri="s3://x/driver.run",
            nvidia_driver_sha256="b" * 64,
        )
