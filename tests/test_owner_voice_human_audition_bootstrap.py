from pathlib import Path

WORKFLOW=Path(".github/workflows/owner-voice-human-audition-pack.yml")


def _install_block() -> str:
    text=WORKFLOW.read_text(encoding="utf-8")
    install=text[text.index("Install strong private STT runtime"):]
    return install[:install.index("Quality-rank real Telegram owner references")]


def test_stt_bootstrap_is_bounded_observable_and_isolated():
    install=_install_block()
    assert "command -v ffmpeg" in install
    assert "sudo apt-get update -qq" not in install
    assert "python -m venv /tmp/br-owner-stt-venv" in install
    assert "timeout 300" in install
    assert "--progress-bar off" in install
    assert "STT_RUNTIME_INSTALL=PASS" in install


def test_stt_runtime_pins_exact_pyav_18_for_faster_whisper_1_2_0():
    install=_install_block()
    assert '"faster-whisper==1.2.0"' in install
    assert '"av==18.0.0"' in install
    assert 'assert version("av") == "18.0.0"' in install
    assert 'assert major < 19' in install
    assert "PYAV_FASTER_WHISPER_COMPATIBILITY=PASS" in install


def test_qa_and_pack_use_same_isolated_stt_runtime():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "/tmp/br-owner-stt-venv/bin/python scripts/owner_voice_reference_qa.py" in text
    assert "/tmp/br-owner-stt-venv/bin/python scripts/owner_voice_human_audition_pack.py" in text


def test_stt_runtime_command_paths_are_not_double_prefixed():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "/tmp/br-owner-stt-venv/bin//tmp/br-owner-stt-venv/bin/python" not in text
    assert text.count("/tmp/br-owner-stt-venv/bin/python scripts/owner_voice_reference_qa.py") == 1
    assert text.count("/tmp/br-owner-stt-venv/bin/python scripts/owner_voice_human_audition_pack.py") == 1
