from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Callable
import urllib.request

from app.services.voice_plane_contracts import VoiceSynthesisRequest


@dataclass(frozen=True)
class VoiceProviderProfile:
    profile_id: str
    provider_id: str
    model_id: str
    model_revision: str
    license: str
    supports_voice_clone: bool
    supports_ptbr: bool
    supports_streaming: bool
    supports_long_form: bool
    supports_pronunciation_control: bool
    supports_batch: bool
    cost_class: str
    usage_kinds: tuple[str, ...]
    latency_rank: int
    watermark_policy: str


QWEN_OWNER_INTERACTIVE = VoiceProviderProfile(
    profile_id="QWEN_OWNER_INTERACTIVE",
    provider_id="qwen3-tts",
    model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    model_revision="5d83992",
    license="Apache-2.0",
    supports_voice_clone=True,
    supports_ptbr=True,
    supports_streaming=True,
    supports_long_form=False,
    supports_pronunciation_control=True,
    supports_batch=True,
    cost_class="SELF_HOSTED_COMPUTE",
    usage_kinds=("INTERACTIVE", "AUDITION", "PRONUNCIATION_TEST"),
    latency_rank=10,
    watermark_policy="NONE_DECLARED_BY_PROFILE",
)

QWEN_OWNER_LONG_FORM = VoiceProviderProfile(
    profile_id="QWEN_OWNER_LONG_FORM",
    provider_id="qwen3-tts",
    model_id="Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    model_revision="fd4b254",
    license="Apache-2.0",
    supports_voice_clone=True,
    supports_ptbr=True,
    supports_streaming=True,
    supports_long_form=True,
    supports_pronunciation_control=True,
    supports_batch=True,
    cost_class="SELF_HOSTED_COMPUTE",
    usage_kinds=("LONG_FORM", "AUDITION", "PRONUNCIATION_TEST"),
    latency_rank=30,
    watermark_policy="NONE_DECLARED_BY_PROFILE",
)

CHATTERBOX_PTBR_PROFILE = VoiceProviderProfile(
    profile_id="CHATTERBOX_OWNER_PTBR",
    provider_id="chatterbox",
    model_id="ResembleAI/Chatterbox-Multilingual-pt-br",
    model_revision="b3952f1",
    license="MIT",
    supports_voice_clone=True,
    supports_ptbr=True,
    supports_streaming=False,
    supports_long_form=True,
    supports_pronunciation_control=False,
    supports_batch=True,
    cost_class="SELF_HOSTED_COMPUTE",
    usage_kinds=("INTERACTIVE", "LONG_FORM", "AUDITION", "PRONUNCIATION_TEST"),
    latency_rank=40,
    watermark_policy="PERTH_WATERMARK_PRESERVE_IF_EMITTED",
)


@dataclass(frozen=True)
class VoiceRouteRequest:
    usage: str
    language: str
    voice_identity_id: str
    required_voice_identity_revision: str | None = None


class VoiceProviderUnavailable(RuntimeError):
    pass


def _eligible(
    request: VoiceRouteRequest,
    profile: VoiceProviderProfile,
    certified_provider_ids: tuple[str, ...],
) -> bool:
    return bool(
        profile.provider_id in set(certified_provider_ids)
        and request.usage in profile.usage_kinds
        and profile.supports_voice_clone
        and request.language.lower().replace("_", "-") in {"pt-br", "pt"}
        and profile.supports_ptbr
        and (request.usage != "LONG_FORM" or profile.supports_long_form)
    )


def select_voice_provider(
    request: VoiceRouteRequest,
    *,
    candidates: tuple[VoiceProviderProfile, ...],
    certified_provider_ids: tuple[str, ...],
    sticky_provider_id: str | None = None,
    sticky_model_id: str | None = None,
) -> VoiceProviderProfile:
    eligible = tuple(
        profile
        for profile in candidates
        if _eligible(request, profile, certified_provider_ids)
    )
    if request.usage == "LONG_FORM" and (sticky_provider_id or sticky_model_id):
        exact = tuple(
            profile
            for profile in eligible
            if profile.provider_id == sticky_provider_id
            and profile.model_id == sticky_model_id
        )
        if len(exact) != 1:
            raise RuntimeError("VOICE_IDENTITY_STICKY target is unavailable")
        return exact[0]
    if not eligible:
        raise VoiceProviderUnavailable("VOICE_PROVIDER_UNAVAILABLE")
    return sorted(
        eligible,
        key=lambda profile: (
            profile.latency_rank,
            profile.provider_id,
            profile.model_id,
            profile.model_revision,
        ),
    )[0]


class PrivateVoiceRuntimeProvider:
    """Provider-neutral client for private br_voice_runtime."""

    def __init__(
        self,
        *,
        profile: VoiceProviderProfile,
        base_url: str,
        auth_token_env: str = "BR_VOICE_RUNTIME_TOKEN",
        transport: Callable[[str, dict[str, Any], dict[str, str]], bytes] | None = None,
    ) -> None:
        self.profile = profile
        self.provider_id = profile.provider_id
        self.model_id = profile.model_id
        self.model_revision = profile.model_revision
        self.base_url = str(base_url).rstrip("/")
        if not self.base_url.startswith(("http://127.0.0.1:", "https://")):
            raise ValueError("voice runtime must be loopback or HTTPS")
        self.auth_token_env = auth_token_env
        self._transport = transport or self._http_transport

    def _http_transport(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> bytes:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.read()

    def synthesize(
        self,
        request: VoiceSynthesisRequest,
        output_path: str | Path,
    ) -> dict[str, Any]:
        token = str(os.environ.get(self.auth_token_env) or "").strip()
        if not token:
            raise VoiceProviderUnavailable("VOICE_RUNTIME_AUTH_UNAVAILABLE")
        payload = {
            **request.to_dict(),
            "provider": self.provider_id,
            "model": self.model_id,
            "model_revision": self.model_revision,
        }
        audio = self._transport(
            self.base_url + "/v1/speech",
            payload,
            {"authorization": "Bearer " + token},
        )
        if not audio:
            raise VoiceProviderUnavailable("TTS_EMPTY_OUTPUT")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        import hashlib
        return {
            "audio_path": str(path),
            "audio_sha256": hashlib.sha256(audio).hexdigest(),
            "provider": self.provider_id,
            "model": self.model_id,
            "model_revision": self.model_revision,
        }
