from app.services import capability_health_service
from app.services.capability_health_service import (
    BLOCKED,
    HEALTHY,
    UNKNOWN,
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



def test_codex_health_is_blocked_before_planning_when_github_federation_is_missing(
    monkeypatch,
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("BR_CODEX_FEDERATION_CONFIGURED", "false")

    observed = capability_health("agent-office.codex.bounded-development")

    assert observed.state == BLOCKED
    assert observed.retry_allowed is False
    assert observed.source == "GITHUB_ACTIONS_CODEX_FEDERATION_CONFIG"
    assert "deterministic registry alternative resolution" in observed.reason.casefold()
    assert "semantic replan" not in observed.reason.casefold()


def test_codex_health_remains_preflight_unknown_when_federation_is_configured(
    monkeypatch,
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("BR_CODEX_FEDERATION_CONFIGURED", "true")

    observed = capability_health("agent-office.codex.bounded-development")

    assert observed.state == UNKNOWN
    assert observed.source == "CODEX_AUTH_PREFLIGHT_REQUIRED"

def test_provenance_provider_id_does_not_create_fake_external_blocker(monkeypatch):
    def unexpected_provider_lookup(provider_id: str):
        raise AssertionError(
            f"provenance provider_id must not enter provider health: {provider_id}"
        )

    monkeypatch.setattr(
        capability_health_service,
        "provider_health",
        unexpected_provider_lookup,
    )

    observed = capability_health("human.presentation.action-first")

    assert observed.state == UNKNOWN
    assert observed.source == "REGISTRY_PLUS_LEARNING"
    assert "sufficient recent execution evidence" in observed.reason

