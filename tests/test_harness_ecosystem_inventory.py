from __future__ import annotations

import importlib

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


def _resolve(binding: str):
    module_name, _, attr = binding.rpartition(".")
    assert module_name and attr, binding
    module = importlib.import_module(module_name)
    executor = getattr(module, attr)
    assert callable(executor), binding
    return executor


def test_every_available_executable_capability_has_importable_binding_and_routes():
    records = GLOBAL_CAPABILITY_REGISTRY.all()
    assert len(records) >= 50
    for record in records:
        if not record.available or record.capability_type == "PROVIDER":
            continue
        if not record.execution_enabled:
            continue
        assert record.executor_binding, record.capability_id
        assert record.evidence_contract, record.capability_id
        _resolve(record.executor_binding)
        assert record.allowed_actions, record.capability_id
        decision = route_harness_request(
            HarnessRoutingRequest(
                intent=f"{record.capability_id} {record.domain}",
                authorized_action=record.allowed_actions[0],
                required_capability_id=record.capability_id,
                domain=record.domain,
                fallback_allowed=False,
                provider_required=False,
                learning_required=False,
            )
        )
        assert decision.selected_capability_id == record.capability_id
        assert decision.selected_executor_binding == record.executor_binding


def test_registry_ids_are_unique_and_specialists_share_the_global_view():
    records = GLOBAL_CAPABILITY_REGISTRY.all()
    ids = [record.capability_id for record in records]
    assert len(ids) == len(set(ids))
    for capability_id in (
        "agent-office.execute",
        "gta6.fact-check",
        "gta6.research.fresh-cloud",
        "narration.generate.pt-BR",
        "production.render.execute",
        "youtube.department.content-strategy",
        "youtube.department.production-management",
        "youtube.department.optimization",
        "youtube.monetization.observe",
        "system.improvement.propose",
    ):
        assert GLOBAL_CAPABILITY_REGISTRY.get(capability_id) is not None
