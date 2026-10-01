from pathlib import Path

WORKFLOW=Path(".github/workflows/owner-voice-human-audition-pack.yml")

def test_human_audition_workflow_is_private_blind_and_dependency_pinned():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64" in text
    assert "TELEGRAM_BOT_TOKEN" in text
    assert "scripts/owner_voice_human_audition_pack.py" in text
    runtime=Path("scripts/owner_voice_human_audition_pack.py").read_text(encoding="utf-8")
    assert "owner_voice_chatterbox_ptbr_audition" in runtime
    runtime=Path("scripts/owner_voice_human_audition_pack.py").read_text(encoding="utf-8")
    assert "scripts.owner_voice_chatterbox_ptbr_audition" in runtime
    assert "scripts/owner_voice_human_audition_pack.py" in text
    runtime=Path("scripts/owner_voice_human_audition_pack.py").read_text(encoding="utf-8")
    assert "owner_voice_chatterbox_ptbr_audition" in runtime
    assert '--constraint "$CONSTRAINTS"' in text
    assert "-m pip check" in text
    assert "CHATTERBOX_DEPENDENCY_CHECK=PASS" in text
    assert "resemble-ai/chatterbox.git@5de7a54aa4e5e2baadb0182dde554908b48b85c2" in text
    assert "BR_OWNER_STT_MODEL: large-v3-turbo" in text
    assert "RAW_OWNER_AUDIO_IN_PUBLIC_ARTIFACT=0" in text
    assert "CLONE_AUDIO_IN_PUBLIC_ARTIFACT=0" in text
    assert "protect_content" in Path("scripts/owner_voice_human_audition_pack.py").read_text(encoding="utf-8")

def test_materialization_workflow_remains_audit_only():
    text=Path(".github/workflows/owner-voice-private-materialization.yml").read_text(encoding="utf-8")
    assert "scripts/owner_voice_chatterbox_ptbr_audition.py" not in text
    assert "scripts/owner_voice_human_audition_pack.py" not in text


def test_stt_install_is_reuse_first_and_does_not_unconditionally_apt_update():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "command -v ffmpeg" in text
    assert "sudo apt-get update -qq" not in text


def test_stt_bootstrap_avoids_unconditional_apt_and_is_bounded_observable():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert 'if ! command -v ffmpeg >/dev/null 2>&1; then' in text
    assert 'timeout 300' in text
    assert '--progress-bar off' in text
    assert 'STT_RUNTIME_INSTALL=PASS' in text


def test_faster_whisper_runtime_pins_pyav_compatible_with_metadata_errors():
    text=WORKFLOW.read_text(encoding="utf-8")
    install=text[text.index("Install strong private STT runtime"):]
    install=install[:install.index("Quality-rank real Telegram owner references")]
    assert '"av==18.0.0"' in install
    assert '"faster-whisper==1.2.0"' in install
    assert 'metadata_errors="ignore"' in Path("tests/fixtures/faster_whisper_pyav_contract.txt").read_text(encoding="utf-8")
