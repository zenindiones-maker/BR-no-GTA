from __future__ import annotations

from app.services.global_capability_registry_base import *  # noqa: F401,F403
from app.services.global_capability_registry_base import (
    AVAILABLE,
    FUNCTIONAL,
    PARTIAL,
    CapabilityRecord,
    GLOBAL_CAPABILITY_REGISTRY as _REGISTRY,
)


PHONE_CONTROL_RECORD = CapabilityRecord(
    capability_id="phone.control",
    capability_type="EXECUTOR",
    domain="device/mobile-control",
    implementation="Harness-authorized bounded Mobile Harness adapter over Mobilerun Portal HTTP",
    input_contract="allowlisted phone operation + deterministic parameters",
    output_contract="sanitized phone control result + Harness evidence",
    requirements=(
        "persisted Harness EXECUTION authorization",
        "local-android-http backend",
        "Mobilerun Portal on loopback",
        "isolated Mobile Harness Python runtime",
        "runtime-only Portal token",
    ),
    maturity=PARTIAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("phone", "mobile", "android", "device-control", "local", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness routing + persisted capability authorization + exact executor binding; "
        "explicit allowlist only; no autonomous authority, publication, install, permission grant, or arbitrary script"
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DEVICE",
    latency_class="LOCAL_INTERACTIVE",
    quality_class="PROVEN_PRIMITIVES_BOUNDED_ADAPTER",
    evidence_contract="app.services.harness_capability_service.CapabilityEvidence",
    fallback_eligibility=False,
    executor_binding="app.services.phone_control_service.execute_phone_control_capability",
    version="1",
    provider_id="mobilerun-local",
    side_effects=("device UI state change",),
)


PRODUCTION_MEDIA_BINDING_RECORD = CapabilityRecord(
    capability_id="production.media.bind-selected-segments",
    capability_type="CAPABILITY",
    domain="production-media",
    implementation="Harness-governed bounded binding of selected Media segments into ProductionPlan",
    input_contract="persisted ProductionPlan + selected segment ids + authorization lineage",
    output_contract="persisted composed ProductionPlan + CapabilityEvidence/CanonicalExecutionResult",
    requirements=(
        "persisted Harness EXECUTION authorization",
        "Harness Routing/Policy decision",
        "exact Global Capability Registry executor binding",
        "matching production lineage and execution_id",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("production", "media", "selection", "binding", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness authority + persisted authorization + exact routing/Registry capability and executor binding; "
        "caller cannot select executor; bind_selected_segments is reachable only after all gates"
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="DETERMINISTIC_BOUNDARY",
    evidence_contract="app.services.harness_capability_service.CapabilityEvidence",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.production_media_composition_service."
        "execute_production_media_binding_capability"
    ),
    version="1",
    side_effects=("ProductionPlan media binding persistence",),
)


for _record in (PHONE_CONTROL_RECORD, PRODUCTION_MEDIA_BINDING_RECORD):
    if _record.capability_id in _REGISTRY._by_id:
        raise ValueError(f"Duplicate capability_id: {_record.capability_id}")
    _REGISTRY._by_id[_record.capability_id] = _record
    _REGISTRY._records = tuple(
        sorted((*_REGISTRY._records, _record), key=lambda item: item.capability_id)
    )

# Keep one deterministic registry instance. These bounded capabilities extend
# the existing registry; they do not create a second catalog or authority surface.
GLOBAL_CAPABILITY_REGISTRY = _REGISTRY
