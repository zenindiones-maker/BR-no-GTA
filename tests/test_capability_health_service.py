from app.services import capability_health_service
from app.services.capability_health_service import (
    BLOCKED,
    HEALTHY,
    capability_health,
)
from app.services.provider_health_service import ProviderHealth


def _provider_health(provider_id: str, *, nvidia_available: bool):
    normalized = str(provider_id).strip().lower().replace("-", "_")
    if normalized == "nvidia_nim" and nvidia_available:
        return ProviderHealth(
            provider_id=normalized,
            state="AVAILABLE",
            reason="deterministic NVIDIA semantic fixture",
            evidence_refs=("test:nvidia:semantic-health",),
            retry_allowed=True,
            zero_cost_eligible=True,
        )
    return ProviderHealth(
        provider_id=normalized,
        state="BLOCKED",
        reason=f"{normalized} unavailable in deterministic fixture",
        evidence_refs=(f"test:{normalized}:blocked",),
        retry_allowed=False,
        zero_cost_eligible=True,
    )


def test_addy_health_accepts_any_harness_governed_semantic_provider(monkeypatch):
    import app.services.provider_health_service as provider_health_service

    monkeypatch.setattr(
        provider_health_service,
        "provider_health",
        lambda provider_id, **kwargs: _provider_health(
            provider_id,
            nvidia_available=True,
        ),
    )
    monkeypatch.setattr(
        capability_health_service,
        "semantic_provider_health",
        provider_health_service.semantic_provider_health,
    )

    observed = capability_health("addy:performance-optimization")
    assert observed.state == HEALTHY
    assert observed.source == "SEMANTIC_PROVIDER_HEALTH"
    assert "nvidia_nim" in observed.reason


def test_addy_health_fails_closed_when_semantic_provider_pool_is_empty(monkeypatch):
    import app.services.provider_health_service as provider_health_service

    monkeypatch.setattr(
        provider_health_service,
        "provider_health",
        lambda provider_id, **kwargs: _provider_health(
            provider_id,
            nvidia_available=False,
        ),
    )
    monkeypatch.setattr(
        capability_health_service,
        "semantic_provider_health",
        provider_health_service.semantic_provider_health,
    )

    observed = capability_health("addy:performance-optimization")
    assert observed.state == BLOCKED
    assert observed.source == "SEMANTIC_PROVIDER_HEALTH"
