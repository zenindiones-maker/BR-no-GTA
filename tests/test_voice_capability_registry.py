from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def test_voice_capabilities_are_subordinate_and_fail_closed():
    for capability_id in (
        "voice.turn.telegram",
        "voice.turn.realtime",
        "narration.generate.pt-BR",
        "voice.synthesis.pt-BR",
    ):
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None
        assert record.authority == "NONE"
        assert record.routing_authority == "NONE"
        assert record.publication_authority == "NONE"
        assert record.memory_write == "FORBIDDEN"
        assert "DeepSeek Harness" in record.security_boundary

    narration = GLOBAL_CAPABILITY_REGISTRY.get("narration.generate.pt-BR")
    assert narration.fallback_eligibility is False
    assert narration.cost_class == "FREE_NO_BILLING"
    assert narration.provider_id == "edge-tts"

    synthesis = GLOBAL_CAPABILITY_REGISTRY.get("voice.synthesis.pt-BR")
    assert synthesis.health_policy == "VOICE_RUNTIME_AND_IDENTITY_REQUIRED"
    assert synthesis.fallback_eligibility is False
    assert synthesis.cost_class == "SELF_HOSTED_COMPUTE"

    telegram = GLOBAL_CAPABILITY_REGISTRY.get("voice.turn.telegram")
    assert telegram.side_effect_class == "HUMAN_MESSAGE_DELIVERY"
    assert telegram.allowed_actions == ("EXECUTION",)

    realtime = GLOBAL_CAPABILITY_REGISTRY.get("voice.turn.realtime")
    assert realtime.side_effect_class == "HUMAN_MESSAGE_DELIVERY"
