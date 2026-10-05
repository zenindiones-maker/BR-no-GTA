from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_tailscale_ssm_parameter_is_project_scoped_in_iam() -> None:
    text = read("modules/workstation/main.tf")
    assert '"ssm:GetParameter"' in text
    assert "tailscale_auth_key_ssm_parameter" in text
    assert 'parameter/${trimprefix(var.tailscale_auth_key_ssm_parameter, "/")}' in text


def test_stacks_use_distinct_tailscale_parameter_names() -> None:
    haze = read("stacks/hazewave/main.tf")
    br = read("stacks/br-no-gta/main.tf")
    assert '"/cloud-media-workstations/hazewave/tailscale-auth-key"' in haze
    assert '"/cloud-media-workstations/br-no-gta/tailscale-auth-key"' in br


def test_no_plaintext_tailscale_key_in_repo() -> None:
    text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in ROOT.rglob("*")
        if p.is_file()
        and ".terraform" not in p.parts
        and ".git" not in p.parts
        and "__pycache__" not in p.parts
        and p != Path(__file__).resolve()
        and p.name != "verify-safe-build"
    )
    assert "tskey-auth-" not in text


def test_auto_stop_systemd_timer_is_installed_and_enabled() -> None:
    tasks = read("ansible/roles/workstation_common/tasks/main.yml")
    service = read("ansible/roles/workstation_common/templates/workstation-autostop.service.j2")
    timer = read("ansible/roles/workstation_common/templates/workstation-autostop.timer.j2")
    assert "workstation-autostop.timer" in tasks
    assert "enabled: true" in tasks
    assert "/usr/local/bin/workstation-autostop" in service
    assert "OnUnitActiveSec=60s" in timer


def test_headless_desktop_autologin_and_sunshine_user_service_are_configured() -> None:
    tasks = read("ansible/roles/workstation_common/tasks/main.yml")
    lightdm = read("ansible/roles/workstation_common/templates/lightdm-media.conf.j2")
    assert "autologin-user={{ media_user }}" in lightdm
    assert "user-session=xfce" in lightdm
    assert "loginctl enable-linger" in tasks
    assert "sunshine.service" in tasks


def test_ansible_requirements_pin_all_used_collections() -> None:
    text = read("ansible/requirements.yml")
    assert "ansible.posix" in text
    assert "community.general" in text
