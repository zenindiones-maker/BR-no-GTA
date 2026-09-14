from __future__ import annotations

from app.services.global_capability_registry_base import *  # noqa: F401,F403
from app.services.global_capability_registry_base import (
    AVAILABLE,
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


if PHONE_CONTROL_RECORD.capability_id in _REGISTRY._by_id:
    raise ValueError(f"Duplicate capability_id: {PHONE_CONTROL_RECORD.capability_id}")
_REGISTRY._by_id[PHONE_CONTROL_RECORD.capability_id] = PHONE_CONTROL_RECORD
_REGISTRY._records = tuple(
    sorted((*_REGISTRY._records, PHONE_CONTROL_RECORD), key=lambda item: item.capability_id)
)

# Keep one deterministic registry instance. The phone capability extends the
# existing registry; it does not create a second catalog or authority surface.
GLOBAL_CAPABILITY_REGISTRY = _REGISTRY
