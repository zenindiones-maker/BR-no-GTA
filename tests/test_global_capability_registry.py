from __future__ import annotations

import pytest

from app.services.global_capability_registry import (
    AVAILABLE,
    BLOCKED,
    UNKNOWN,
    CapabilityRecord,
    GlobalCapabilityRegistry,
    GLOBAL_CAPABILITY_REGISTRY,
)


def _record(capability_id: str) -> CapabilityRecord:
    return CapabilityRecord(
        capability_id=capability_id,
        capability_type="CAPABILITY",
        domain="test",
        implementation="fake",
        input_contract="input",
        output_contract="output",
        requirements=(),
        maturity="PROVEN",
        availability=AVAILABLE,
        allowed_actions=("DEVELOPMENT",),
        policy_tags=("test",),
        security_boundary="test-only",
        cost_class="NONE",
        quota_class="NONE",
        latency_class="LOCAL",
        quality_class="TEST",
        evidence_contract="fake evidence",
        fallback_eligibility=False,
        executor_binding="tests.fake_executor",
        version="1",
    )


def test_capability_ids_are_stable_unique_and_sorted():
    first = [item.capability_id for item in GLOBAL_CAPABILITY_REGISTRY.all()]
    second = [item.capability_id for item in GLOBAL_CAPABILITY_REGISTRY.all()]

    assert first == second
    assert first == sorted(first)
    assert len(first) == len(set(first))


def test_duplicate_capability_id_fails_deterministically():
    record = _record("duplicate")

    with pytest.raises(ValueError, match="Duplicate capability_id: duplicate"):
        GlobalCapabilityRegistry((record, record))


def test_registry_has_no_authorization_or_execution_api():
    assert not hasattr(GLOBAL_CAPABILITY_REGISTRY, "authorize")
    assert not hasattr(GLOBAL_CAPABILITY_REGISTRY, "execute")
    assert not hasattr(GLOBAL_CAPABILITY_REGISTRY, "publish")
    assert not hasattr(GLOBAL_CAPABILITY_REGISTRY, "schedule")


def test_discovery_filters_authorized_action():
    results = GLOBAL_CAPABILITY_REGISTRY.discover(
        intent="youtube public publish",
        authorized_action="PUBLICATION",
        limit=20,
    )

    assert results
    assert all("PUBLICATION" in item["allowed_actions"] for item in results)
    assert "youtube.publish-public" in {
        item["capability_id"] for item in results
    }


def test_discovery_filters_unavailable_capabilities():
    results = GLOBAL_CAPABILITY_REGISTRY.discover(
        intent="higgsfield visual generation gemini tubegent analytics",
        authorized_action=None,
        limit=50,
    )
    ids = {item["capability_id"] for item in results}

    assert not any(item.startswith("higgsfield-") for item in ids)
    assert "ai.provider.gemini" not in ids
    assert "tubegent" not in ids
    assert "analytics.learning" not in ids


def test_higgsfield_remains_blocked():
    records = [
        item
        for item in GLOBAL_CAPABILITY_REGISTRY.all()
        if item.provider_id == "higgsfield"
    ]

    assert len(records) == 4
    assert all(item.availability == BLOCKED for item in records)
    assert all(item.execution_enabled is False for item in records)
    assert all("ephemeral-runner auth" in item.security_boundary for item in records)


def test_unknown_does_not_become_available():
    for capability_id in (
        "ai.provider.gemini",
        "analytics.learning",
        "tubegent",
    ):
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None
        assert record.availability == UNKNOWN
        assert record.available is False
        assert record.execution_enabled is False


def test_fact_check_is_explicitly_executable_after_bounded_runtime_promotion():
    record = GLOBAL_CAPABILITY_REGISTRY.get("gta6.fact-check")
    assert record is not None
    assert record.availability == AVAILABLE
    assert record.available is True
    assert record.execution_enabled is True
    assert record.executor_binding == (
        "app.services.gta6_fact_check_service.execute_gta6_fact_check_capability"
    )
    assert record.evidence_contract == "app.services.gta6_fact_check_service.FactCheckResult"


def test_every_available_capability_has_executor_binding():
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.available:
            assert record.executor_binding


def test_every_executable_capability_has_evidence_contract():
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.execution_enabled:
            assert record.evidence_contract


def test_provider_model_and_capability_are_distinct_metadata():
    nvidia = GLOBAL_CAPABILITY_REGISTRY.get("ai.provider.nvidia-nim")

    assert nvidia is not None
    assert nvidia.capability_id == "ai.provider.nvidia-nim"
    assert nvidia.provider_id == "nvidia_nim"
    assert nvidia.model_id == "nvidia/nemotron-3-super-120b-a12b"
    assert nvidia.capability_id != nvidia.provider_id
    assert nvidia.capability_id != nvidia.model_id

    generic = GLOBAL_CAPABILITY_REGISTRY.get("ai.reasoning.text")
    assert generic is not None
    assert generic.provider_id is None
    assert generic.model_id is None


def test_addy_skills_remain_bounded_and_metadata_only():
    addy = [
        item
        for item in GLOBAL_CAPABILITY_REGISTRY.all()
        if item.capability_id.startswith("addy:")
    ]

    assert len(addy) == 24
    assert all(item.allowed_actions == ("DEVELOPMENT",) for item in addy)
    assert all(item.skill_id for item in addy)
    assert all(item.instruction_path for item in addy)
    assert all("HarnessAuthorization" in item.security_boundary for item in addy)
    assert all("zero-cost semantic provider" in item.security_boundary for item in addy)
    assert all("no autonomous routing" in item.security_boundary for item in addy)
    assert all(
        item.executor_binding
        == "app.services.addy_harness_service.execute_authorized_addy_skill"
        for item in addy
    )

    metadata = GLOBAL_CAPABILITY_REGISTRY.discover(
        intent="code review quality",
        authorized_action="DEVELOPMENT",
    )
    addy_metadata = [
        item for item in metadata
        if str(item.get("capability_id") or "").startswith("addy:")
    ]
    serialized = repr(addy_metadata).lower()
    assert addy_metadata
    assert "use only @" not in serialized
    assert "skill body" not in serialized
    assert "pinned skill instruction start" not in serialized


def test_nvidia_state_is_proven_and_harness_governed():
    record = GLOBAL_CAPABILITY_REGISTRY.get("ai.provider.nvidia-nim")

    assert record is not None
    assert record.status == "PROVEN"
    assert record.available is True
    assert record.execution_enabled is True
    assert "HarnessAuthorization" in record.security_boundary


def test_registry_is_deterministic_for_same_query():
    kwargs = {
        "intent": "code review quality",
        "authorized_action": "DEVELOPMENT",
        "limit": 5,
    }
    assert GLOBAL_CAPABILITY_REGISTRY.discover(**kwargs) == (
        GLOBAL_CAPABILITY_REGISTRY.discover(**kwargs)
    )


def test_registry_does_not_offer_silent_fallback():
    assert all(
        record.fallback_eligibility is False
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
    )


def test_native_skills_are_mapped_to_real_capabilities():
    expected = {
        "gta6-research": "gta6.research",
        "gta6-editorial": "editorial.process",
        "gta6-production": "production.plan",
        "gta6-youtube": "youtube.upload-private",
        "gta6-fact-check": "gta6.fact-check",
    }
    for skill_id, capability_id in expected.items():
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None
        assert record.skill_id == skill_id
        assert record.instruction_path == f".dsh/skills/{skill_id}/SKILL.md"


def test_production_plan_is_allowed_from_editorial_and_execution():
    record = GLOBAL_CAPABILITY_REGISTRY.get("production.plan")
    assert record is not None
    assert set(record.allowed_actions) == {"EDITORIAL", "EXECUTION"}
    editorial = GLOBAL_CAPABILITY_REGISTRY.discover(
        intent="production plan", authorized_action="EDITORIAL", limit=20
    )
    assert "production.plan" in {item["capability_id"] for item in editorial}


def test_production_plan_rejects_unrelated_actions():
    record = GLOBAL_CAPABILITY_REGISTRY.get("production.plan")
    assert record is not None
    assert "RESEARCH" not in record.allowed_actions
    assert "YOUTUBE" not in record.allowed_actions
    assert "PUBLICATION" not in record.allowed_actions


def test_human_presentation_skill_is_bounded_and_pinned():
    record = GLOBAL_CAPABILITY_REGISTRY.get("human.presentation.action-first")
    assert record is not None
    assert record.capability_type == "PRESENTATION"
    assert record.domain == "human-presentation"
    assert record.allowed_actions == ("DECISION",)
    assert record.skill_id == "human.presentation.action-first"
    assert record.instruction_path == ".dsh/skills/human-presentation-action-first/SKILL.md"
    assert record.side_effects == ()
    assert record.authority == "NONE"
    assert record.memory_write == "FORBIDDEN"
    assert record.routing_authority == "NONE"
    assert record.editorial_authority == "NONE"
    assert record.publication_authority == "NONE"
    assert record.fallback_eligibility is False
    assert record.version == "0.3.0-br1"
    assert "b15d0be58f55b33972ba3e39709e0e5208ef30cb" in record.implementation
    assert "write memory" in record.security_boundary
    assert "publication authority" in record.security_boundary
