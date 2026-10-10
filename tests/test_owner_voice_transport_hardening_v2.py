"""Regression tests for the real BR_OWNER_V1 Telegram delivery path.

Only synthetic WAV fixtures; no network or owner audio.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest

from app.services.owner_voice_delivery_codec_v2 import encode_private_opus
from app.services.owner_voice_single_clone_delivery_service import SingleCloneDeliveryLedger
from scripts.owner_voice_single_clone_delivery import TelegramSingleCloneApi


def _voice_api():
    return TelegramSingleCloneApi(
        "synthetic",
        identity_gate="PASS",
        content_audio_prescreen="PASS",
        review_token="f" * 20,
        identity_anchor_telegram_input_id=123,
        pronunciation_reference_telegram_input_ids=[],
        vice_city_reference_telegram_input_id=None,
    )


def test_send_voice_uses_ogg_opus_not_wav(monkeypatch, tmp_path):
    import scripts.owner_voice_single_clone_delivery as delivery
    calls = []
    def fake_post(token, method, *, data, files=None):
        calls.append((method, files))
        assert method == "sendVoice"
        assert list(files) == ["voice"]
        assert files["voice"][2] == "audio/ogg"
        return {"message_id": 901}
    monkeypatch.setattr(delivery, "_telegram_post", fake_post)
    ogg = tmp_path / "probe.ogg"
    ogg.write_bytes(b"OggS-synthetic-only")
    assert _voice_api().send_clone_audio(chat_id=-1001, clone_path=ogg, protect_content=True) == 901
    assert len(calls) == 1


def test_wav_is_never_sent_directly(monkeypatch, tmp_path):
    import scripts.owner_voice_single_clone_delivery as delivery
    monkeypatch.setattr(delivery, "_telegram_post",
        lambda *a, **k: pytest.fail("WAV MUST NOT BE SENT"))
    wav = tmp_path / "probe.wav"
    wav.write_bytes(b"RIFF-not-real")
    with pytest.raises(RuntimeError, match="SINGLE_CLONE_TELEGRAM_OPUS_REQUIRED"):
        _voice_api().send_clone_audio(chat_id=-1001, clone_path=wav, protect_content=True)


def test_opus_encoder_validates_codec_and_private_workspace(tmp_path):
    private=tmp_path / "private"
    private.mkdir()
    source=private / "synthetic.wav"
    with wave.open(str(source),"wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00"*16000)
    output=encode_private_opus(source,private / "voice",private_workspace=private)
    assert output.is_file() and output.stat().st_size > 0
    probe=subprocess.run(
        ["ffprobe","-v","error","-select_streams","a:0",
         "-show_entries","stream=codec_name","-of","default=nw=1:nk=1",str(output)],
        capture_output=True,text=True,check=True,
    )
    assert probe.stdout.strip()=="opus"


def test_codec_rejects_source_outside_private_workspace(tmp_path):
    source=tmp_path / "outside.wav"
    source.write_bytes(b"not-private")
    private=tmp_path / "private"
    private.mkdir()
    with pytest.raises(ValueError, match="OWNER_AUDIO_OUTSIDE_PRIVATE_WORKSPACE"):
        encode_private_opus(source,private,private_workspace=private)


class FakeStore:
    def __init__(self):
        self.sha="s0"
        self.head=None
    def snapshot(self,mission_id):
        from types import SimpleNamespace
        return SimpleNamespace(head_sha=self.sha,mission_head=self.head)
    def transact(self,*,mission_id,expected_head_sha,expected_state_version,mission_head,immutable_objects=None):
        assert expected_head_sha==self.sha
        self.sha="s"+str(int(self.sha[1:])+1)
        self.head=dict(mission_head)
        return self.sha


def test_ledger_replay_fails_on_different_audio_and_destination():
    ledger=SingleCloneDeliveryLedger(store=FakeStore(),clone_id="synthetic-stable-id")
    args=dict(telegram_chat_id=-1001,reference_source_message_id=501,
        clone_sha256="a"*64,authority_ref="test-owner-voice")
    original=ledger.create(**args)
    assert ledger.create(**args)==original
    with pytest.raises(ValueError,match="SINGLE_CLONE_LEDGER_PAYLOAD_COLLISION"):
        ledger.create(**{**args,"clone_sha256":"b"*64})
    with pytest.raises(ValueError,match="SINGLE_CLONE_LEDGER_PAYLOAD_COLLISION"):
        ledger.create(**{**args,"telegram_chat_id":-1002})


def test_retry_identity_does_not_depend_on_github_run_attempt():
    src=Path("scripts/owner_voice_single_human_clone.py").read_text(encoding="utf-8")
    assert 'GITHUB_RUN_ATTEMPT' not in src.split('clone_id=f"BR_OWNER_V1_SINGLE_CLONE_',1)[1].split('}',1)[0]


def test_recovery_workflow_push_trigger_is_scoped_to_isolated_branch():
    source=Path(".github/workflows/owner-voice-single-human-clone.yml").read_text(encoding="utf-8")
    assert "work/owner-voice-safe-ingress-recovery-20261010" in source
