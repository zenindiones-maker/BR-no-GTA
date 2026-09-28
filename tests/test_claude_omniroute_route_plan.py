from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "agent-tooling" / "claude_omniroute_route_plan.py"


def load_module():
    spec = importlib.util.spec_from_file_location("claude_omniroute_route_plan", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def fake_decision(effective_candidates):
    return SimpleNamespace(
        routing_id="route-test-123",
        selected_capability_id="ai.reasoning.text",
        selected_provider="nvidia_nim",
        selected_model="nvidia/nemotron-3-ultra-550b-a55b",
        fallback_occurred=False,
        policy_metadata={
            "provider_eligibility_snapshot": {
                "snapshot_ref": "objects/provider-eligibility/sha256/abc.json",
                "content_sha256": "abc",
                "effective_candidates": effective_candidates,
            }
        },
    )


class ClaudeOmniRouteRoutePlanTests(unittest.TestCase):
    def test_provider_mapping_is_exact_typed_and_extensible(self):
        module = load_module()
        source = module.HarnessProviderIdentity(
            provider_id="nvidia_nim",
            model_id="nvidia/nemotron-3-ultra-550b-a55b",
        )
        provider, model = module.map_harness_target(source)
        self.assertEqual(provider.provider_id, "nvidia")
        self.assertEqual(provider.credential_env, "NVIDIA_API_KEY")
        self.assertEqual(
            model.model_id,
            "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
        )
        self.assertEqual(model.provider_id, "nvidia")
        self.assertIn("nvidia_nim", module.PROVIDER_IDENTITY_MAPPINGS)

    def test_unknown_provider_mapping_fails_closed_without_fuzzy_match(self):
        module = load_module()
        with self.assertRaises(module.ModelMappingUnavailable):
            module.map_harness_target(
                module.HarnessProviderIdentity(
                    provider_id="nvidia",
                    model_id="nvidia/nemotron-3-ultra-550b-a55b",
                )
            )
        with self.assertRaises(module.ModelMappingUnavailable):
            module.map_harness_target(
                module.HarnessProviderIdentity(
                    provider_id="nvidia_nim_extra",
                    model_id="nvidia/nemotron-3-ultra-550b-a55b",
                )
            )

    def test_route_plan_is_content_addressed_bounded_and_uses_logical_alias(self):
        module = load_module()
        candidates = [
            {
                "candidate_id": "ai.provider.nvidia-nim.nemotron-3-ultra",
                "provider_id": "nvidia_nim",
                "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
                "status": "ACCEPTED",
                "reasons": [],
            },
            {
                "candidate_id": "ai.provider.nvidia-nim.backup",
                "provider_id": "nvidia_nim",
                "model_id": "nvidia/backup-model",
                "status": "ACCEPTED",
                "reasons": [],
            },
        ]
        decision = fake_decision(candidates)
        kwargs = {
            "required_capabilities": ("coding", "reasoning", "structured_output"),
            "strategy": "priority",
            "zero_cost": True,
            "excluded_targets": (
                {
                    "provider": "opencode",
                    "model": "oc/big-pickle",
                    "failure_class": "UPSTREAM_DENIED_HTTP_403",
                },
            ),
            "created_from_execution_need": "SHARED_ROUTE_UNAVAILABLE",
        }
        first = module.build_route_plan(decision, **kwargs)
        second = module.build_route_plan(
            fake_decision(list(reversed(candidates))),
            **kwargs,
        )
        self.assertEqual(first["schema"], "HarnessOmniRoutePlan/v1")
        self.assertEqual(first["authority"], "DEEPSEEK_HARNESS")
        self.assertEqual(first["route_plan_sha256"], second["route_plan_sha256"])
        self.assertEqual(first["route_plan_id"], second["route_plan_id"])
        self.assertEqual(first["logical_claude_model"], second["logical_claude_model"])
        self.assertTrue(first["logical_claude_model"].startswith("combo/harness-claude-"))
        self.assertNotIn("nvidia", first["logical_claude_model"])
        self.assertNotIn("opencode", first["logical_claude_model"])
        self.assertEqual(first["strategy"], "priority")
        self.assertTrue(first["zero_cost"])
        self.assertEqual(len(first["candidate_targets"]), 2)
        self.assertEqual(
            first["candidate_targets"][0]["harness_model"],
            "nvidia/nemotron-3-ultra-550b-a55b",
        )
        self.assertTrue(all(item["authorized_target"] for item in first["candidate_targets"]))
        self.assertNotIn("auto", json.dumps(first).lower())

    def test_exhausted_or_unavailable_target_never_enters_plan(self):
        module = load_module()
        decision = fake_decision([
            {
                "candidate_id": "bad",
                "provider_id": "opencode",
                "model_id": "oc/big-pickle",
                "status": "REJECTED",
                "reasons": ["provider_model_pair_exhausted"],
            },
            {
                "candidate_id": "good",
                "provider_id": "nvidia_nim",
                "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
                "status": "ACCEPTED",
                "reasons": [],
            },
        ])
        plan = module.build_route_plan(
            decision,
            required_capabilities=("coding", "reasoning", "structured_output"),
            strategy="priority",
            zero_cost=True,
            excluded_targets=(
                {
                    "provider": "opencode",
                    "model": "oc/big-pickle",
                    "failure_class": "UPSTREAM_DENIED_HTTP_403",
                },
            ),
            created_from_execution_need="SHARED_ROUTE_UNAVAILABLE",
        )
        physical = {
            (item["harness_provider"], item["harness_model"])
            for item in plan["candidate_targets"]
        }
        self.assertNotIn(("opencode", "oc/big-pickle"), physical)
        self.assertEqual(
            physical,
            {("nvidia_nim", "nvidia/nemotron-3-ultra-550b-a55b")},
        )

    def test_dispatch_evidence_fails_closed_for_unauthorized_physical_target(self):
        module = load_module()
        plan = module.build_route_plan(
            fake_decision([
                {
                    "candidate_id": "good",
                    "provider_id": "nvidia_nim",
                    "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
                    "status": "ACCEPTED",
                    "reasons": [],
                }
            ]),
            required_capabilities=("coding", "reasoning", "structured_output"),
            strategy="priority",
            zero_cost=True,
            excluded_targets=(),
            created_from_execution_need="SHARED_ROUTE_UNAVAILABLE",
        )
        evidence = module.build_dispatch_evidence(
            plan,
            selected_provider="nvidia",
            selected_model="nvidia/nvidia/nemotron-3-ultra-550b-a55b",
            attempt_index=0,
            http_status=200,
            latency_ms=12.5,
            response_sha256="f" * 64,
            fallback_from=None,
            fallback_reason=None,
        )
        self.assertEqual(evidence["schema"], "OmniRouteDispatchEvidence/v1")
        self.assertTrue(evidence["authorized_target"])
        with self.assertRaises(module.UnauthorizedDispatch):
            module.build_dispatch_evidence(
                plan,
                selected_provider="openai",
                selected_model="gpt-5",
                attempt_index=0,
                http_status=200,
                latency_ms=10.0,
                response_sha256="a" * 64,
                fallback_from=None,
                fallback_reason=None,
            )

    def test_all_targets_exhausted_requires_provider_replan_not_blind_retry(self):
        module = load_module()
        plan = module.build_route_plan(
            fake_decision([
                {
                    "candidate_id": "good",
                    "provider_id": "nvidia_nim",
                    "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
                    "status": "ACCEPTED",
                    "reasons": [],
                }
            ]),
            required_capabilities=("coding", "reasoning", "structured_output"),
            strategy="priority",
            zero_cost=True,
            excluded_targets=(),
            created_from_execution_need="SHARED_ROUTE_UNAVAILABLE",
        )
        exhausted = {
            ("nvidia", "nvidia/nvidia/nemotron-3-ultra-550b-a55b")
        }
        with self.assertRaises(module.ProviderPoolExhausted):
            module.remaining_authorized_targets(plan, exhausted)


if __name__ == "__main__":
    unittest.main()
