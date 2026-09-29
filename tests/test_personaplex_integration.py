from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.personaplex_realtime_service import (
    PERSONAPLEX_CODE_REVISION,
    PERSONAPLEX_EXPERIMENTAL,
    PERSONAPLEX_MODEL_REVISION,
    PersonaPlexSessionRequest,
    PersonaPlexUnavailable,
    authorize_personaplex_tools,
    build_personaplex_websocket_url,
    decode_personaplex_server_frame,
    encode_personaplex_audio_frame,
    personaplex_route_status,
)


ROOT = Path(__file__).resolve().parents[1]


def test_personaplex_is_pinned_and_experimental_only():
    lock = json.loads(
        (ROOT / "integrations/personaplex/runtime.lock.json").read_text(encoding="utf-8")
    )
    assert lock["upstream"]["repository"] == "NVIDIA/personaplex"
    assert lock["upstream"]["repository_revision"] == PERSONAPLEX_CODE_REVISION
    assert lock["model"]["id"] == "nvidia/personaplex-7b-v1"
    assert lock["model"]["revision"] == PERSONAPLEX_MODEL_REVISION
    assert PERSONAPLEX_EXPERIMENTAL.full_duplex is True
    assert PERSONAPLEX_EXPERIMENTAL.production_eligible is False
    assert PERSONAPLEX_EXPERIMENTAL.ptbr_eligible is False


def test_personaplex_ptbr_route_fails_closed():
    request = PersonaPlexSessionRequest(
        language="pt-BR",
        voice_prompt_name="owner.wav",
        text_prompt="Você conversa em português brasileiro.",
    )
    with pytest.raises(PersonaPlexUnavailable, match="LANGUAGE_UNSUPPORTED"):
        build_personaplex_websocket_url("wss://voice.example.test", request)

    status = personaplex_route_status("pt-BR")
    assert status["language_supported"] is False
    assert status["ptbr_eligible"] is False
    assert status["production_eligible"] is False


def test_personaplex_allows_only_harness_voice_turn():
    assert authorize_personaplex_tools(["harness.voice.turn"]) == ("harness.voice.turn",)
    with pytest.raises(PermissionError, match="PRIVILEGED_TOOL_FORBIDDEN"):
        authorize_personaplex_tools(["harness.voice.turn", "github.write"])


def test_personaplex_runtime_requires_secure_remote_transport():
    request = PersonaPlexSessionRequest(
        language="en",
        voice_prompt_name="NATM1.pt",
        text_prompt="You enjoy having a good conversation.",
    )
    url = build_personaplex_websocket_url("wss://voice.example.test", request)
    assert url.startswith("wss://voice.example.test/api/chat?")
    assert "voice_prompt=NATM1.pt" in url
    assert "text_prompt=" in url

    loopback = build_personaplex_websocket_url("ws://127.0.0.1:8998", request)
    assert loopback.startswith("ws://127.0.0.1:8998/api/chat?")

    with pytest.raises(PersonaPlexUnavailable, match="REMOTE_PLAINTEXT_FORBIDDEN"):
        build_personaplex_websocket_url("ws://voice.example.test:8998", request)


def test_personaplex_protocol_frames_match_upstream_contract():
    assert encode_personaplex_audio_frame(b"opus") == b"\x01opus"
    assert decode_personaplex_server_frame(b"\x00") == ("handshake", None)
    assert decode_personaplex_server_frame(b"\x01opus") == ("audio", b"opus")
    assert decode_personaplex_server_frame("olá".encode("utf-8").join([b"\x02", b""])) == (
        "text",
        "olá",
    )
    with pytest.raises(ValueError, match="unknown"):
        decode_personaplex_server_frame(b"\x09bad")
