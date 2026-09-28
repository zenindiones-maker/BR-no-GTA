from __future__ import annotations

from pathlib import Path

import pytest

from app.services.speech.models import (
    SpeechAnalysis, SpeechEngine, SpeechQuality, SpeechSegment,
)
from app.services.telegram_voice_service import process_telegram_voice_turn
from scripts.telegram_harness_gateway import _extract_attachment


class FakeTelegram:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.sent = []
    def materialize_file(self, file_id: str) -> Path:
        path = self.tmp_path / "voice.ogg"
        path.write_bytes(b"fake-ogg")
        return path
    def send_voice(self, *, chat_id: int, voice_path: Path, caption: str | None = None):
        self.sent.append((chat_id, voice_path.suffix, caption))
        return {"ok": True, "message_id": 999}


class FakeSpeechProvider:
    provider_name = "fake-stt"
    model_name = "fake-stt-v1"
    model_version = "1"
    def analyze(self, source_path, *, language=None):
        return SpeechAnalysis(
            source_path=str(source_path),
            duration_seconds=2.0,
            source_language="pt-BR",
            language_probability=0.99,
            segments=(SpeechSegment(segment_id="s1",start_seconds=0,end_seconds=2,text="onde está o vídeo?"),),
            speech_seconds=2.0,
            words_per_minute=120.0,
            quality=SpeechQuality(transcription_confidence=0.98,timestamp_confidence=0.98),
            engine=SpeechEngine(provider="fake-stt",model="fake-stt-v1",version="1"),
        )


class FakeTTS:
    provider_id = "qwen3-tts"
    model_id = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    def __init__(self):
        self.requests = []
    def synthesize(self, request, output_path):
        self.requests.append(request)
        output_path.write_bytes(b"fake-wav")
        return {"audio_path": str(output_path), "audio_sha256": "d" * 64}


def test_authorized_telegram_voice_converges_to_harness_and_send_voice(tmp_path):
    telegram = FakeTelegram(tmp_path)
    tts = FakeTTS()
    captured = {}
    def harness_turn(transcript: str, **kwargs):
        captured["transcript"] = transcript
        return {
            "answer": "Production está em execução.",
            "authority": "deepseek_harness",
            "execution_id": "exec-1",
        }
    result = process_telegram_voice_turn(
        update={
            "message": {
                "message_id": 10,
                "from": {"id": 111},
                "chat": {"id": -222, "type": "supergroup"},
                "voice": {"file_id": "file-voice-1", "file_unique_id": "uniq-1", "duration": 2},
            }
        },
        allowed_user_id=111,
        state={"allowed_chat_ids": [-222]},
        telegram=telegram,
        speech_provider=FakeSpeechProvider(),
        harness_turn=harness_turn,
        tts_provider=tts,
        work_dir=tmp_path,
        audio_normalizer=lambda source, target: (target.write_bytes(source.read_bytes()), target)[1],
        audio_encoder=lambda source, target: (target.write_bytes(source.read_bytes()), target)[1],
    )
    assert captured["transcript"] == "onde está o vídeo?"
    assert result["authority"] == "deepseek_harness"
    assert result["voice_turn"]["authorized_human"] is True
    assert result["voice_turn"]["surface"] == "TELEGRAM"
    assert result["send_voice"]["ok"] is True
    assert telegram.sent[0][0] == -222
    assert telegram.sent[0][1] == ".ogg"
    assert tts.requests[0].voice_identity_id == "BR_OWNER_V1"


def test_unauthorized_telegram_voice_is_rejected_before_file_download(tmp_path):
    telegram = FakeTelegram(tmp_path)
    with pytest.raises(PermissionError, match="authorized"):
        process_telegram_voice_turn(
            update={
                "message": {
                    "message_id": 10,
                    "from": {"id": 999},
                    "chat": {"id": -222, "type": "supergroup"},
                    "voice": {"file_id": "file-secret", "file_unique_id": "uniq-secret", "duration": 2},
                }
            },
            allowed_user_id=111,
            state={"allowed_chat_ids": [-222]},
            telegram=telegram,
            speech_provider=FakeSpeechProvider(),
            harness_turn=lambda *_a, **_k: {},
            tts_provider=FakeTTS(),
            work_dir=tmp_path,
            audio_normalizer=lambda source, target: target,
            audio_encoder=lambda source, target: target,
        )
    assert not (tmp_path / "voice.ogg").exists()


def test_telegram_attachment_extractor_preserves_voice_and_audio_identity():
    voice = _extract_attachment({
        "voice": {
            "file_id": "voice-file-id",
            "file_unique_id": "voice-unique-id",
            "duration": 17,
            "mime_type": "audio/ogg",
            "file_size": 12345,
        }
    })
    assert voice == {
        "media_kind": "voice",
        "telegram_file_id": "voice-file-id",
        "telegram_file_unique_id": "voice-unique-id",
        "file_name": None,
        "mime_type": "audio/ogg",
        "file_size": 12345,
        "duration_seconds": 17,
    }

    audio = _extract_attachment({
        "audio": {
            "file_id": "audio-file-id",
            "file_unique_id": "audio-unique-id",
            "duration": 31,
            "mime_type": "audio/mpeg",
            "file_size": 67890,
            "file_name": "owner-reference.mp3",
        }
    })
    assert audio["media_kind"] == "audio"
    assert audio["telegram_file_id"] == "audio-file-id"
    assert audio["telegram_file_unique_id"] == "audio-unique-id"
    assert audio["duration_seconds"] == 31


def test_first_authorized_group_can_bootstrap_once_without_authorizing_other_senders():
    from app.services.telegram_ingress_policy_service import (
        bootstrap_first_allowed_chat,
        configured_allowed_chat_ids,
        parse_governed_telegram_ingress,
    )

    state: dict = {}
    state, bootstrapped = bootstrap_first_allowed_chat(
        state,
        chat_id=-222,
        authorized_user_id=111,
        sender_user_id=111,
    )
    assert bootstrapped is True
    assert configured_allowed_chat_ids(state) == {-222}

    update = {
        "message": {
            "message_id": 77,
            "from": {"id": 111},
            "chat": {"id": -222, "type": "supergroup"},
            "text": "teste",
        }
    }
    ingress = parse_governed_telegram_ingress(
        update,
        allowed_user_id=111,
        state=state,
    )
    assert ingress is not None and ingress.accepted is True

    state, bootstrapped = bootstrap_first_allowed_chat(
        state,
        chat_id=-333,
        authorized_user_id=111,
        sender_user_id=111,
    )
    assert bootstrapped is False
    assert configured_allowed_chat_ids(state) == {-222}

    with pytest.raises(PermissionError):
        bootstrap_first_allowed_chat(
            {},
            chat_id=-444,
            authorized_user_id=111,
            sender_user_id=999,
        )
