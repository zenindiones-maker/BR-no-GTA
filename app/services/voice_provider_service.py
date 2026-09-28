from __future__ import annotations

from dataclasses import dataclass
import hashlib
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
    supports_reference_batch: bool = False
    supports_reference_fusion: bool = False
    supports_reusable_clone_prompt: bool = False


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
    supports_reference_batch=True,
    supports_reference_fusion=False,
    supports_reusable_clone_prompt=True,
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
    supports_reference_batch=True,
    supports_reference_fusion=False,
    supports_reusable_clone_prompt=True,
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
    watermark_policy="PERTH_WATERMARK_MANDATORY_PRESERVE",
    supports_reference_batch=False,
    supports_reference_fusion=False,
    supports_reusable_clone_prompt=False,
)


@dataclass(frozen=True)
class VoiceRouteRequest:
    usage: str
    language: str
    voice_identity_id: str
    required_voice_identity_revision: str | None = None


class VoiceProviderUnavailable(RuntimeError):
    pass


OWNER_VOICE_IDENTITY_ID = "BR_OWNER_V1"


@dataclass(frozen=True)
class PrivateVoiceRuntimeResponse:
    audio: bytes
    receipt: dict[str, Any]


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _valid_sha256(value: Any) -> bool:
    digest = str(value or "").strip().lower()
    return len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)


def _default_owner_identity_resolver(voice_identity_id: str) -> dict[str, Any] | None:
    if voice_identity_id != OWNER_VOICE_IDENTITY_ID:
        return None
    enrollment_path = Path(
        os.environ.get("BR_OWNER_ENROLLMENT_STATE_PATH")
        or Path(__file__).resolve().parents[2] / "config" / "voice_owner_enrollment_v1.json"
    )
    try:
        enrollment = json.loads(enrollment_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(enrollment, dict):
        return None
    if int(enrollment.get("materialized_reference_count") or 0) <= 0:
        return None
    if enrollment.get("reference_materialization_status") != "PASS":
        return None
    if enrollment.get("runtime_activation_status") != "READY":
        return None
    if enrollment.get("owner_voice_status") != "READY":
        return None
    store_root = str(os.environ.get("BR_PRIVATE_VOICE_STORE") or "").strip()
    if not store_root:
        return None
    profile_path = Path(store_root).expanduser() / f"{voice_identity_id}.json"
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return profile if isinstance(profile, dict) else None


def _materialized_owner_binding(
    voice_identity_id: str,
    resolver: Callable[[str], dict[str, Any] | None],
) -> tuple[dict[str, Any], dict[str, str]]:
    if voice_identity_id != OWNER_VOICE_IDENTITY_ID:
        raise VoiceProviderUnavailable("OWNER_VOICE_ONLY")
    profile = resolver(voice_identity_id)
    if not isinstance(profile, dict):
        raise VoiceProviderUnavailable("OWNER_VOICE_NOT_MATERIALIZED")
    if profile.get("voice_identity_id") != OWNER_VOICE_IDENTITY_ID:
        raise VoiceProviderUnavailable("OWNER_VOICE_NOT_MATERIALIZED")
    if str(profile.get("consent_status") or "") != "APPROVED":
        raise VoiceProviderUnavailable("OWNER_VOICE_NOT_MATERIALIZED")
    if str(profile.get("quality_status") or "") != "READY":
        raise VoiceProviderUnavailable("OWNER_VOICE_NOT_MATERIALIZED")

    source_refs = tuple(str(v) for v in (profile.get("source_audio_refs") or ()))
    source_hashes = tuple(str(v).lower() for v in (profile.get("source_audio_sha256s") or ()))
    transcript_hashes = tuple(str(v).lower() for v in (profile.get("source_transcript_sha256s") or ()))
    if (
        not source_refs
        or len(source_refs) != len(source_hashes)
        or not transcript_hashes
        or any(not ref.startswith("private://") for ref in source_refs)
        or any(not _valid_sha256(value) for value in source_hashes)
        or any(not _valid_sha256(value) for value in transcript_hashes)
    ):
        raise VoiceProviderUnavailable("OWNER_VOICE_NOT_MATERIALIZED")

    prompt_ref = str(profile.get("voice_prompt_ref") or "").strip()
    prompt_sha = str(profile.get("voice_prompt_sha256") or "").strip().lower()
    if not prompt_ref.startswith("private://") or not _valid_sha256(prompt_sha):
        raise VoiceProviderUnavailable("OWNER_VOICE_PROMPT_UNAVAILABLE")

    profile_sha = _sha256_json(profile)
    reference_set_sha = _sha256_json({
        "source_audio_sha256s": list(source_hashes),
        "source_transcript_sha256s": list(transcript_hashes),
    })
    return profile, {
        "voice_identity_id": OWNER_VOICE_IDENTITY_ID,
        "profile_sha256": profile_sha,
        "voice_prompt_ref": prompt_ref,
        "voice_prompt_sha256": prompt_sha,
        "reference_set_sha256": reference_set_sha,
    }


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
        identity_resolver: Callable[[str], dict[str, Any] | None] | None = None,
        transport: Callable[
            [str, dict[str, Any], dict[str, str]],
            PrivateVoiceRuntimeResponse | bytes,
        ] | None = None,
    ) -> None:
        self.profile = profile
        self.provider_id = profile.provider_id
        self.model_id = profile.model_id
        self.model_revision = profile.model_revision
        self.base_url = str(base_url).rstrip("/")
        if not self.base_url.startswith(("http://127.0.0.1:", "https://")):
            raise ValueError("voice runtime must be loopback or HTTPS")
        self.auth_token_env = auth_token_env
        self._identity_resolver = identity_resolver or _default_owner_identity_resolver
        self._transport = transport or self._http_transport

    def _http_transport(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> PrivateVoiceRuntimeResponse:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            audio = response.read()
            headers = response.headers
            receipt = {
                "schema": str(headers.get("X-BR-Voice-Receipt-Schema") or ""),
                "voice_identity_id": str(headers.get("X-BR-Voice-Identity-Id") or ""),
                "profile_sha256": str(headers.get("X-BR-Voice-Profile-SHA256") or ""),
                "voice_prompt_sha256": str(headers.get("X-BR-Voice-Prompt-SHA256") or ""),
                "reference_set_sha256": str(headers.get("X-BR-Voice-Reference-Set-SHA256") or ""),
                "provider": str(headers.get("X-BR-Voice-Provider") or ""),
                "model": str(headers.get("X-BR-Voice-Model") or ""),
                "model_revision": str(headers.get("X-BR-Voice-Model-Revision") or ""),
                "request_id": str(headers.get("X-BR-Voice-Request-Id") or ""),
                "audio_sha256": str(headers.get("X-BR-Voice-Audio-SHA256") or ""),
                "usage": str(headers.get("X-BR-Voice-Usage") or ""),
            }
            return PrivateVoiceRuntimeResponse(audio=audio, receipt=receipt)

    def synthesize(
        self,
        request: VoiceSynthesisRequest,
        output_path: str | Path,
    ) -> dict[str, Any]:
        token = str(os.environ.get(self.auth_token_env) or "").strip()
        if not token:
            raise VoiceProviderUnavailable("VOICE_RUNTIME_AUTH_UNAVAILABLE")

        _profile, binding = _materialized_owner_binding(
            request.voice_identity_id,
            self._identity_resolver,
        )
        payload = {
            **request.to_dict(),
            "provider": self.provider_id,
            "model": self.model_id,
            "model_revision": self.model_revision,
            "voice_identity_binding": binding,
        }
        raw_response = self._transport(
            self.base_url + "/v1/speech",
            payload,
            {"authorization": "Bearer " + token},
        )
        if isinstance(raw_response, bytes):
            raise VoiceProviderUnavailable("VOICE_RUNTIME_RECEIPT_MISSING")
        if not isinstance(raw_response, PrivateVoiceRuntimeResponse):
            raise VoiceProviderUnavailable("VOICE_RUNTIME_RECEIPT_MISSING")
        audio = raw_response.audio
        if not audio:
            raise VoiceProviderUnavailable("TTS_EMPTY_OUTPUT")

        receipt = dict(raw_response.receipt or {})
        expected = {
            "schema": "OwnerVoiceSynthesisReceipt/v1",
            "voice_identity_id": OWNER_VOICE_IDENTITY_ID,
            "profile_sha256": binding["profile_sha256"],
            "voice_prompt_sha256": binding["voice_prompt_sha256"],
            "reference_set_sha256": binding["reference_set_sha256"],
            "provider": self.provider_id,
            "model": self.model_id,
            "model_revision": self.model_revision,
            "usage": request.usage,
        }
        for key, value in expected.items():
            if str(receipt.get(key) or "") != str(value):
                raise VoiceProviderUnavailable("OWNER_VOICE_RECEIPT_MISMATCH")
        if not str(receipt.get("request_id") or "").strip():
            raise VoiceProviderUnavailable("OWNER_VOICE_RECEIPT_MISMATCH")

        audio_sha = hashlib.sha256(audio).hexdigest()
        runtime_audio_sha = str(receipt.get("audio_sha256") or "").strip().lower()
        if runtime_audio_sha and runtime_audio_sha != audio_sha:
            raise VoiceProviderUnavailable("OWNER_VOICE_RECEIPT_MISMATCH")
        receipt["audio_sha256"] = audio_sha

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return {
            "audio_path": str(path),
            "audio_sha256": audio_sha,
            "provider": self.provider_id,
            "model": self.model_id,
            "model_revision": self.model_revision,
            "voice_identity_id": OWNER_VOICE_IDENTITY_ID,
            "receipt": receipt,
        }
