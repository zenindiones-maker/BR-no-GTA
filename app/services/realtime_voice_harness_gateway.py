from __future__ import annotations

import hashlib
from typing import Any, Callable

from app.services.voice_plane_contracts import VoiceSynthesisRequest


NEMOTRON_VOICECHAT_BOUNDARY = {
    "schema": "NemotronVoiceChatBoundary/v1",
    "model_id": "nvidia/NVIDIA-NemotronLabs-VoiceChat-11B",
    "model_revision": "443794e",
    "license": "openmdw-1.1",
    "language_status": "ENGLISH_MODEL_CURRENTLY",
    "allowed_tools": ["harness.voice.turn"],
    "production_eligible": False,
    "status": "EXPERIMENTAL_READY",
}


class RealtimeVoiceHarnessGateway:
    allowed_authority_tools = ("harness.voice.turn",)

    def __init__(self, *, harness_turn: Callable[..., dict[str, Any]]) -> None:
        self._harness_turn = harness_turn

    @staticmethod
    def deterministic_session_id(*, conversation_id: str, user_identity: str) -> str:
        seed = f"{conversation_id}:{user_identity}:br-no-gta-voice-v1"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def on_turn(
        self,
        *,
        conversation_id: str,
        transcript: str,
        correlation_id: str,
        user_identity: str,
        intent_hint: str | None = None,
    ) -> dict[str, Any]:
        if not str(user_identity).strip():
            raise PermissionError("authenticated realtime voice user required")
        if not str(transcript).strip():
            raise ValueError("voice transcript is required")
        result = self._harness_turn(
            conversation_id=conversation_id,
            transcript=transcript,
            intent_hint=intent_hint,
            correlation_id=correlation_id,
        )
        if not isinstance(result, dict):
            raise RuntimeError("invalid Harness voice result")
        return result

    def on_audio_interrupt(self, *, execution_id: str | None) -> dict[str, Any]:
        return {
            "schema": "RealtimeAudioInterruption/v1",
            "execution_id": execution_id,
            "audio_interrupted": True,
            "task_cancelled": False,
        }


class HarnessQwenTTSProvider:
    def __init__(self, *, runtime_provider: Any, voice_identity_id: str) -> None:
        self.runtime_provider = runtime_provider
        self.voice_identity_id = voice_identity_id

    def synthesize_text(
        self,
        *,
        text: str,
        correlation_id: str,
        output_path: str,
    ) -> dict[str, Any]:
        request = VoiceSynthesisRequest(
            voice_identity_id=self.voice_identity_id,
            text=text,
            language="pt-BR",
            usage="INTERACTIVE",
            rate=1.0,
            style="REALTIME",
            segment_id=correlation_id,
            correlation_id=correlation_id,
        )
        return self.runtime_provider.synthesize(request, output_path)
