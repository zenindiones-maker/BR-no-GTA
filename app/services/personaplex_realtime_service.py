from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlencode, urlparse, urlunparse


PERSONAPLEX_CODE_REPOSITORY = "NVIDIA/personaplex"
PERSONAPLEX_CODE_REVISION = "3428dfd95309a7f3c84fd93259ded0f810d1ff91"
PERSONAPLEX_MODEL_ID = "nvidia/personaplex-7b-v1"
PERSONAPLEX_MODEL_REVISION = "fdaf4090a61cb315c138a1faee287ffd6c716309"
PERSONAPLEX_CODE_LICENSE = "MIT"
PERSONAPLEX_MODEL_LICENSE = "nvidia-open-model-license"
PERSONAPLEX_SAMPLE_RATE_HZ = 24_000
PERSONAPLEX_WS_PATH = "/api/chat"
PERSONAPLEX_ALLOWED_TOOLS = ("harness.voice.turn",)
PERSONAPLEX_SUPPORTED_LANGUAGES = ("en",)


class PersonaPlexUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PersonaPlexRuntimeProfile:
    provider_id: str = "nvidia-personaplex"
    model_id: str = PERSONAPLEX_MODEL_ID
    model_revision: str = PERSONAPLEX_MODEL_REVISION
    code_repository: str = PERSONAPLEX_CODE_REPOSITORY
    code_revision: str = PERSONAPLEX_CODE_REVISION
    code_license: str = PERSONAPLEX_CODE_LICENSE
    model_license: str = PERSONAPLEX_MODEL_LICENSE
    sample_rate_hz: int = PERSONAPLEX_SAMPLE_RATE_HZ
    full_duplex: bool = True
    supports_voice_prompt: bool = True
    supports_role_prompt: bool = True
    production_eligible: bool = False
    ptbr_eligible: bool = False


PERSONAPLEX_EXPERIMENTAL = PersonaPlexRuntimeProfile()


@dataclass(frozen=True)
class PersonaPlexSessionRequest:
    language: str
    voice_prompt_name: str
    text_prompt: str
    seed: int = 42_424_242

    def validate(self) -> None:
        language = self.language.strip().lower().replace("_", "-")
        if language not in PERSONAPLEX_SUPPORTED_LANGUAGES:
            raise PersonaPlexUnavailable("PERSONAPLEX_LANGUAGE_UNSUPPORTED")

        name = self.voice_prompt_name.strip()
        if (
            not name
            or "/" in name
            or "\\" in name
            or name in {".", ".."}
            or name.startswith(".")
        ):
            raise PersonaPlexUnavailable("PERSONAPLEX_VOICE_PROMPT_NAME_INVALID")

        if not self.text_prompt.strip():
            raise PersonaPlexUnavailable("PERSONAPLEX_TEXT_PROMPT_REQUIRED")


def authorize_personaplex_tools(requested_tools: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(str(tool).strip() for tool in requested_tools if str(tool).strip())
    forbidden = set(normalized) - set(PERSONAPLEX_ALLOWED_TOOLS)
    if forbidden:
        raise PermissionError("PERSONAPLEX_PRIVILEGED_TOOL_FORBIDDEN")
    return normalized


def build_personaplex_websocket_url(
    base_url: str,
    request: PersonaPlexSessionRequest,
) -> str:
    request.validate()

    parsed = urlparse(str(base_url).strip())
    if parsed.scheme not in {"ws", "wss"}:
        raise PersonaPlexUnavailable("PERSONAPLEX_RUNTIME_URL_INVALID")

    host = (parsed.hostname or "").lower()
    if parsed.scheme == "ws" and host not in {"127.0.0.1", "localhost", "::1"}:
        raise PersonaPlexUnavailable("PERSONAPLEX_REMOTE_PLAINTEXT_FORBIDDEN")

    path = parsed.path.rstrip("/")
    if not path:
        path = PERSONAPLEX_WS_PATH
    elif path != PERSONAPLEX_WS_PATH:
        raise PersonaPlexUnavailable("PERSONAPLEX_RUNTIME_PATH_INVALID")

    query = urlencode(
        {
            "voice_prompt": request.voice_prompt_name,
            "text_prompt": request.text_prompt,
            "seed": int(request.seed),
        }
    )
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


def encode_personaplex_audio_frame(opus_payload: bytes) -> bytes:
    if not isinstance(opus_payload, (bytes, bytearray)) or not opus_payload:
        raise ValueError("non-empty Opus payload required")
    return b"\x01" + bytes(opus_payload)


def decode_personaplex_server_frame(frame: bytes) -> tuple[str, bytes | str | None]:
    if not isinstance(frame, (bytes, bytearray)) or not frame:
        raise ValueError("non-empty PersonaPlex frame required")

    kind = int(frame[0])
    payload = bytes(frame[1:])
    if kind == 0:
        if payload:
            raise ValueError("invalid PersonaPlex handshake frame")
        return ("handshake", None)
    if kind == 1:
        return ("audio", payload)
    if kind == 2:
        return ("text", payload.decode("utf-8"))
    raise ValueError("unknown PersonaPlex frame type")


def personaplex_route_status(language: str) -> dict[str, object]:
    normalized = str(language).strip().lower().replace("_", "-")
    supported = normalized in PERSONAPLEX_SUPPORTED_LANGUAGES
    return {
        "provider_id": PERSONAPLEX_EXPERIMENTAL.provider_id,
        "model_id": PERSONAPLEX_MODEL_ID,
        "model_revision": PERSONAPLEX_MODEL_REVISION,
        "language": normalized,
        "language_supported": supported,
        "ptbr_eligible": False,
        "production_eligible": False,
        "full_duplex": True,
        "allowed_tools": list(PERSONAPLEX_ALLOWED_TOOLS),
        "status": "EXPERIMENTAL_READY" if supported else "BLOCKED_UNSUPPORTED_LANGUAGE",
    }
