from __future__ import annotations

import importlib

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from scripts.audit_harness_ecosystem import (
    _masteragent_direct_entrypoint_safe,
    _runtime_identity_inventory,
    _worker_runner_identity,
    canonical_worker_engine_ids,
)
from app.services.agent_office.munder_adapter import registered_worker_runners


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


def test_worker_engine_classification_counts_physical_engines_not_runner_aliases():
    assert _worker_runner_identity("deterministic-analysis") == (
        "WORKER_ENGINE",
        "deterministic-analysis",
    )
    assert _worker_runner_identity("codex-readonly") == (
        "WORKER_ENGINE",
        "codex-readonly",
    )
    assert _worker_runner_identity("codex-development") == (
        "WORKER_ENGINE",
        "codex",
    )
    assert _worker_runner_identity("addy-specialist") == (
        "AGENT",
        "addy-agent-skills",
    )
    registered_runner_ids = set(registered_worker_runners())
    assert registered_runner_ids == {
        "deterministic-analysis",
        "codex-readonly",
        "codex-development",
        "codex-independent-reviewer",
        "addy-specialist",
    }
    assert canonical_worker_engine_ids() == (
        "codex",
        "codex-independent-reviewer",
        "codex-readonly",
        "deterministic-analysis",
    )


def test_execution_plane_runtime_identities_have_one_control_plane():
    rows = _runtime_identity_inventory()
    by_id = {row["RUNTIME_ID"]: row for row in rows}

    assert len(by_id) == len(rows)
    assert set(by_id) == {
        "deepseek-harness",
        "gta6-master",
        "gta6-master-agent",
        "gta6-brain",
        "hermes-runtime",
        "agent-office-coordinator",
    }
    control_planes = [
        row for row in rows if row["CONTROL_PLANE"] is True
    ]
    assert [row["RUNTIME_ID"] for row in control_planes] == [
        "deepseek-harness"
    ]
    assert by_id["gta6-master"]["AUTHORITY_ROLE"] == (
        "SUBORDINATE_DOMAIN_OPERATOR"
    )
    assert by_id["gta6-master-agent"]["CONTROL_PLANE"] is False
    assert by_id["gta6-master-agent"]["EXTERNAL_EXPOSURE"] == (
        "INDIRECT_HARNESS_MCP_WRAPPER_ONLY"
    )
    assert by_id["gta6-brain"]["AUTHORITY_ROLE"] == "RECOMMENDATION_ONLY"
    assert by_id["hermes-runtime"]["AUTHORITY_ROLE"] == "COORDINATION_ONLY"
    assert by_id["agent-office-coordinator"]["AUTHORITY_ROLE"] == (
        "BOUNDED_EXECUTION_ONLY"
    )
    assert all(
        row["EXPECTED_SOURCE_BRANCH"] == "work/gate6f-analytics-learning"
        for row in rows
    )
    assert len({row["EXECUTED_COMMIT_SHA"] for row in rows}) == 1
    assert _masteragent_direct_entrypoint_safe() is True


def test_native_gta6_agent_wording_does_not_claim_parallel_control_plane():
    from pathlib import Path

    text = Path(".dsh/cordis.patch.yml").read_text(encoding="utf-8")
    assert "DeepSeek Harness é a única autoridade/control plane" in text
    assert "Você é o orquestrador de uma máquina editorial GTA6." not in text
    assert "O BR é a fonte de verdade operacional; você é o orquestrador." not in text
