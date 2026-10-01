from pathlib import Path

WORKFLOW = Path(".github/workflows/owner-voice-human-audition-pack.yml")

def test_faster_whisper_runtime_pins_pyav_before_metadata_errors_removal():
    text=WORKFLOW.read_text(encoding="utf-8")
    install=text[text.index("Install strong private STT runtime"):]
    install=install[:install.index("Quality-rank real Telegram owner references")]
    assert '"faster-whisper==1.2.0"' in install
    assert '"av==18.0.0"' in install
    assert 'from importlib.metadata import version' in install
    assert 'major=int(version("av").split(".",1)[0])' in install
    assert 'assert major < 19' in install
    assert 'PYAV_FASTER_WHISPER_COMPATIBILITY=PASS' in install
