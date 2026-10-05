from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")

def test_common_role_installs_audio_desktop_and_remote_stack() -> None:
    text = read("ansible/roles/workstation_common/tasks/main.yml")
    for package in ("pipewire", "wireplumber", "xfce4", "ffmpeg", "vulkan-tools"):
        assert package in text
    assert "sunshine" in text.lower()
    assert "reaper" in text.lower()

def test_reaper_and_sunshine_artifacts_are_digest_pinned() -> None:
    vars_text = read("ansible/group_vars/all.yml")
    assert 'reaper_version: "7.82"' in vars_text
    assert "a4aa961534f22ae5ae910e4ec0c200dcb4476c9f7556806fe09a9743cd582563" in vars_text
    assert 'sunshine_version: "2026.914.233613"' in vars_text
    assert "c38e9c705f650f8705f61702717e99bec34044c5028fcb8f23a08fe041292c21" in vars_text

def test_nvidia_driver_is_required_and_never_guessed() -> None:
    text = read("ansible/roles/nvidia_driver/tasks/main.yml")
    assert "BLOCKED_DRIVER_URI_UNSET" in text
    assert "nvidia_driver_sha256" in text
    assert "nvidia_driver_s3_uri" in text

def test_pipewire_defines_deterministic_sunshine_sink() -> None:
    text = read("ansible/roles/workstation_common/templates/10-sunshine-sink.conf.j2")
    assert "sunshine_sink" in text
    assert "Audio/Sink" in text

def test_headless_xorg_is_1080p60_capable_without_dummy_hdmi() -> None:
    text = read("ansible/roles/workstation_common/templates/10-nvidia-headless.conf.j2")
    assert "AllowEmptyInitialConfiguration" in text
    assert "1920x1080" in text
    assert "Virtual 1920 1080" in text

def test_tailscale_auth_is_read_from_ssm_not_repo_plaintext() -> None:
    text = read("ansible/roles/workstation_common/tasks/main.yml")
    assert "tailscale_auth_key_ssm_parameter" in text
    assert "aws ssm get-parameter" in text
    assert "--with-decryption" in text

def test_reaper_wrapper_emits_typed_receipt_and_hashes() -> None:
    text = read("scripts/reaper_render.py")
    assert "MediaExecutionResult/v1" in text
    assert "input_project_sha256" in text
    assert "output_sha256" in text
    assert "-renderproject" in text
    assert "ffprobe" in text

def test_auto_stop_requires_no_session_no_lease_no_render() -> None:
    text = read("scripts/workstation_autostop.py")
    assert "interactive_active" in text
    assert "active_leases" in text
    assert "protected_render_active" in text
    assert "STOP_IDLE" in text
    assert "shutdown" in text

def test_project_specific_media_packages_are_not_duplicated() -> None:
    haze = read("ansible/roles/hazewave/tasks/main.yml")
    br = read("ansible/roles/br_no_gta/tasks/main.yml")
    assert "kdenlive" not in haze
    assert "blender" not in haze
    assert "kdenlive" in br
    assert "blender" in br

def test_sunshine_admin_not_bound_publicly() -> None:
    text = read("ansible/roles/workstation_common/templates/sunshine.conf.j2")
    assert "origin_web_ui_allowed = lan" not in text.lower()
    assert "origin_web_ui_allowed = pc" in text.lower()

def test_playbook_is_split_by_project() -> None:
    haze = read("ansible/hazewave.yml")
    br = read("ansible/br-no-gta.yml")
    assert "hazewave" in haze
    assert "br_no_gta" not in haze
    assert "br_no_gta" in br


def test_autostop_understands_iso_lease_and_real_sunshine_session() -> None:
    text = read("scripts/workstation_autostop.py")
    assert "expires_at" in text
    assert "datetime.fromisoformat" in text
    assert "sunshine_session_active" in text
    assert "ss" in text
    assert 'process_running("sunshine")' not in text


def test_ssm_parameter_access_is_project_scoped_in_iac() -> None:
    module = read("modules/workstation/main.tf")
    variables = read("modules/workstation/variables.tf")
    haze = read("stacks/hazewave/main.tf")
    br = read("stacks/br-no-gta/main.tf")
    assert "ssm:GetParameter" in module
    assert "tailscale_auth_key_ssm_parameter" in variables
    assert "/cloud-media-workstations/hazewave/tailscale-auth-key" in haze
    assert "/cloud-media-workstations/br-no-gta/tailscale-auth-key" in br


def test_data_volume_is_resolved_by_ebs_volume_id() -> None:
    text = read("ansible/roles/workstation_common/tasks/main.yml")
    assert "data_volume_id" in text
    assert "SERIAL" in text
    assert "/dev/nvme1n1" not in text


def test_sunshine_credentials_come_from_project_scoped_ssm() -> None:
    text = read("ansible/roles/workstation_common/tasks/main.yml")
    haze = read("ansible/group_vars/hazewave.yml")
    br = read("ansible/group_vars/br_no_gta.yml")
    assert "sunshine_username_ssm_parameter" in text
    assert "sunshine_password_ssm_parameter" in text
    assert "sunshine --creds" in text
    assert "/cloud-media-workstations/hazewave/sunshine-" in haze
    assert "/cloud-media-workstations/br-no-gta/sunshine-" in br


def test_graphical_session_autostarts_sunshine_and_default_audio_sink() -> None:
    role = read("ansible/roles/workstation_common/tasks/main.yml")
    launcher = read("ansible/roles/workstation_common/files/cloud-media-session-start")
    assert "lightdm.conf.d" in role
    assert "autologin-user={{ media_user }}" in role
    assert ".config/autostart" in role
    assert "pactl set-default-sink sunshine_sink" in launcher
    assert "exec sunshine" in launcher
