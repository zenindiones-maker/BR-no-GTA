from __future__ import annotations

import json
from pathlib import Path

from app.services.realtime_voice_harness_gateway import (
    NEMOTRON_VOICECHAT_BOUNDARY,
    RealtimeVoiceHarnessGateway,
)


ROOT = Path(__file__).resolve().parents[1]


def test_realtime_gateway_exposes_only_harness_voice_turn():
    calls = []
    gateway = RealtimeVoiceHarnessGateway(
        harness_turn=lambda **payload: calls.append(payload) or {
            "canonical_text": "ok",
            "status": "COMPLETED",
            "execution_id": "exec-1",
            "spoken_summary": "ok",
            "requires_confirmation": False,
        }
    )
    result = gateway.on_turn(
        conversation_id="conv-1",
        transcript="confere a production",
        correlation_id="corr-1",
        user_identity="owner",
    )
    assert result["status"] == "COMPLETED"
    assert len(calls) == 1
    assert set(calls[0]) == {"conversation_id","transcript","intent_hint","correlation_id"}
    assert gateway.allowed_authority_tools == ("harness.voice.turn",)


def test_barge_in_interrupts_audio_not_harness_task():
    gateway = RealtimeVoiceHarnessGateway(harness_turn=lambda **_: {})
    state = gateway.on_audio_interrupt(execution_id="exec-ongoing")
    assert state["audio_interrupted"] is True
    assert state["task_cancelled"] is False


def test_nemotron_is_experimental_and_has_no_privileged_tools():
    assert NEMOTRON_VOICECHAT_BOUNDARY["model_id"] == "nvidia/NVIDIA-NemotronLabs-VoiceChat-11B"
    assert NEMOTRON_VOICECHAT_BOUNDARY["license"] == "openmdw-1.1"
    assert NEMOTRON_VOICECHAT_BOUNDARY["allowed_tools"] == ["harness.voice.turn"]
    assert NEMOTRON_VOICECHAT_BOUNDARY["production_eligible"] is False
    forbidden = {"github.write","youtube.publish","mission.authorize","provider.manage","secret.read","policy.modify"}
    assert not forbidden.intersection(NEMOTRON_VOICECHAT_BOUNDARY["allowed_tools"])


def test_cloudflare_voice_surface_is_pinned_and_subordinate():
    package = json.loads((ROOT / "integrations/cloudflare-voice/package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["agents"] == "0.24.0"
    server = (ROOT / "integrations/cloudflare-voice/src/server.ts").read_text(encoding="utf-8")
    assert 'from "agents/voice"' in server
    assert "@cloudflare/voice" not in server
    assert "harness.voice.turn" in server
    for forbidden in ("github.write","youtube.publish","mission.authorize","provider.manage","secret.read","policy.modify"):
        assert forbidden not in server
