from __future__ import annotations

from typing import Any

from app.services.global_capability_registry_base import (
    AVAILABLE,
    FUNCTIONAL,
    CapabilityRecord,
)


def _record(
    *,
    capability_id: str,
    implementation: str,
    input_contract: str,
    output_contract: str,
    evidence_contract: str,
    executor_binding: str,
    cost_class: str = "BOUNDED_BY_ROUTE",
    health_policy: str = "DEFAULT",
    side_effect_class: str = "READ_ONLY",
    policy_tags: tuple[str, ...] = (),
) -> CapabilityRecord:
    return CapabilityRecord(
        capability_id=capability_id,
        capability_type="CAPABILITY",
        domain="voice",
        implementation=implementation,
        input_contract=input_contract,
        output_contract=output_contract,
        requirements=(
            "persisted DeepSeek Harness EXECUTION authorization",
            "exact Global Capability Registry binding",
            "authorized human/surface where applicable",
        ),
        maturity=FUNCTIONAL,
        availability=AVAILABLE,
        allowed_actions=("EXECUTION",),
        policy_tags=("voice", "pt-br", "harness-subordinate", *policy_tags),
        security_boundary=(
            "DeepSeek Harness is sole authority; voice transport/providers perform only "
            "the exact authorized turn/synthesis operation and have no routing, mission, "
            "publication, policy, secret, or canonical-memory authority."
        ),
        cost_class=cost_class,
        quota_class="VOICE_RUNTIME_BOUNDED",
        latency_class="INTERACTIVE_OR_SECTION_LOCAL",
        quality_class="VOICE_QA_AND_TYPED_EVIDENCE_REQUIRED",
        evidence_contract=evidence_contract,
        fallback_eligibility=False,
        executor_binding=executor_binding,
        version="1",
        provider_id="internal-voice-plane",
        side_effects=(),
        authority="NONE",
        memory_write="FORBIDDEN",
        routing_authority="NONE",
        editorial_authority="NONE",
        publication_authority="NONE",
        supports_parallelism=True,
        supports_retry=False,
        supports_resume=True,
        supports_review=True,
        side_effect_class=side_effect_class,
        default_read_scope=(),
        default_write_scope=(),
        allowed_tools=(),
        health_policy=health_policy,
        execution_kind="TOOL",
        functional_roles=("VOICE_INTERFACE",),
    )


def voice_capability_records() -> tuple[CapabilityRecord, ...]:
    return (
        _record(
            capability_id="voice.turn.telegram",
            implementation="Harness-governed Telegram voice ingress/STT/voice-egress adapter",
            input_contract="authorized Telegram voice attachment + SpeechProvider + Harness voice turn",
            output_contract="VoiceTurnEnvelope/v1 + canonical Harness result + Telegram sendVoice receipt",
            evidence_contract="VoiceTurnEnvelope/v1 + TelegramVoiceTurnResult/v1",
            executor_binding="app.services.voice_capability_bridge.execute_telegram_voice_capability",
            side_effect_class="HUMAN_MESSAGE_DELIVERY",
            policy_tags=("telegram", "stt", "tts", "sendvoice"),
        ),
        _record(
            capability_id="voice.turn.realtime",
            implementation="Harness-governed realtime voice session boundary for Cloudflare Agents Voice transport",
            input_contract="authenticated realtime session + transcript + correlation lineage",
            output_contract="canonical Harness voice result + realtime audio interruption evidence",
            evidence_contract="VoiceTurnResult/v1 + RealtimeAudioInterruption/v1",
            executor_binding="app.services.voice_capability_bridge.execute_realtime_voice_capability",
            side_effect_class="HUMAN_MESSAGE_DELIVERY",
            policy_tags=("realtime", "cloudflare", "barge-in"),
        ),
        _record(
            capability_id="voice.synthesis.pt-BR",
            implementation="Provider-neutral private voice runtime synthesis boundary for pt-BR narration",
            input_contract="VoiceSynthesisRequest/v1 + private VoiceIdentityProfile/v1",
            output_contract="content-addressed narration audio + VoiceProviderEvidence/v1",
            evidence_contract="VoiceProviderEvidence/v1",
            executor_binding="app.services.voice_capability_bridge.execute_narration_voice_capability",
            cost_class="SELF_HOSTED_COMPUTE",
            health_policy="VOICE_RUNTIME_AND_IDENTITY_REQUIRED",
            policy_tags=("narration", "qwen3-tts", "chatterbox", "voice-clone", "long-form"),
        ),
        _record(
            capability_id="voice.clone.pt-BR",
            implementation="Telegram-bound BR_OWNER_V1 voice-clone synthesis boundary for Brazilian Portuguese",
            input_contract="pt-BR VoiceSynthesisRequest/v1 + private Telegram-bound BR_OWNER_V1 VoiceIdentityProfile/v1",
            output_contract="content-addressed owner-cloned pt-BR audio + VoiceProviderEvidence/v1",
            evidence_contract="VoiceProviderEvidence/v1 + Telegram owner-reference lineage",
            executor_binding="app.services.voice_capability_bridge.execute_owner_voice_clone_capability",
            cost_class="SELF_HOSTED_COMPUTE",
            health_policy="VOICE_RUNTIME_AND_IDENTITY_REQUIRED",
            policy_tags=("voice-clone", "owner-reference", "telegram", "pt-br", "chatterbox"),
        ),
    )


def _require_harness_context(payload: dict[str, Any]) -> None:
    if str(payload.get("authority") or "").lower() != "deepseek_harness":
        raise PermissionError("DeepSeek Harness authorization is required")


def execute_telegram_voice_capability(payload: dict[str, Any]) -> dict[str, Any]:
    _require_harness_context(payload)
    executor = payload.get("executor")
    if not callable(executor):
        raise RuntimeError("TELEGRAM_VOICE_RUNTIME_UNAVAILABLE")
    return executor()


def execute_realtime_voice_capability(payload: dict[str, Any]) -> dict[str, Any]:
    _require_harness_context(payload)
    gateway = payload.get("gateway")
    request = payload.get("request")
    if gateway is None or not isinstance(request, dict):
        raise RuntimeError("REALTIME_VOICE_RUNTIME_UNAVAILABLE")
    return gateway.on_turn(**request)


def execute_narration_voice_capability(payload: dict[str, Any]) -> dict[str, Any]:
    _require_harness_context(payload)
    provider = payload.get("provider")
    request = payload.get("request")
    output_path = payload.get("output_path")
    if provider is None or request is None or not output_path:
        raise RuntimeError("VOICE_RUNTIME_OR_IDENTITY_UNAVAILABLE")
    return provider.synthesize(request, output_path)


def execute_owner_voice_clone_capability(payload: dict[str, Any]) -> dict[str, Any]:
    _require_harness_context(payload)
    provider = payload.get("provider")
    request = payload.get("request")
    output_path = payload.get("output_path")
    if provider is None or request is None or not output_path:
        raise RuntimeError("OWNER_VOICE_CLONE_RUNTIME_OR_REFERENCE_UNAVAILABLE")
    if str(getattr(request, "voice_identity_id", "") or "") != "BR_OWNER_V1":
        raise RuntimeError("OWNER_VOICE_IDENTITY_REQUIRED")
    if str(getattr(request, "language", "") or "").lower().replace("_", "-") != "pt-br":
        raise RuntimeError("OWNER_VOICE_PTBR_REQUIRED")
    return provider.synthesize(request, output_path)
