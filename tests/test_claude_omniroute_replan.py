from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "agent-tooling" / "claude_omniroute_replan.py"


def load_module():
    spec = importlib.util.spec_from_file_location("claude_omniroute_replan", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RequestFixture:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ClaudeOmniRouteReplanTests(unittest.TestCase):
    def test_replan_request_excludes_failed_opencode_pair_and_uses_mapped_providers(self):
        module = load_module()
        values = module.replan_request_values()
        self.assertEqual(values["recovery_phase"], "PROVIDER_LEVEL_REPLAN")
        self.assertTrue(values["provider_level_replan_authorized"])
        self.assertEqual(values["from_provider"], "opencode")
        self.assertEqual(values["unavailable_provider_ids"], ("opencode",))
        self.assertEqual(
            values["exhausted_provider_model_pairs"],
            (("opencode", "oc/big-pickle"),),
        )
        self.assertEqual(
            values["allowed_providers"],
            module.mapped_harness_provider_ids(),
        )
        self.assertEqual(values["preferred_providers"], ())
        self.assertEqual(
            set(values["required_model_capabilities"]),
            {"reasoning", "coding", "structured_output"},
        )
        self.assertFalse(values["fallback_allowed"])
        self.assertTrue(values["zero_cost_operation"])

    def test_compat_identity_wrapper_uses_generic_mapping_layer(self):
        module = load_module()
        mapped = module.omniroute_identity(
            "nvidia_nim", "nvidia/nemotron-3-ultra-550b-a55b"
        )
        self.assertEqual(mapped["provider"], "nvidia")
        self.assertEqual(
            mapped["model"],
            "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
        )
        self.assertEqual(mapped["credential_env"], "NVIDIA_API_KEY")

    def test_unknown_provider_mapping_fails_closed(self):
        module = load_module()
        with self.assertRaises(ValueError):
            module.omniroute_identity("tuxevil", "gemini-3-flash")

    def test_select_replan_materializes_content_addressed_route_plan(self):
        module = load_module()
        decision = SimpleNamespace(
            routing_id="route-replan-1",
            selected_capability_id="ai.reasoning.text",
            selected_provider="nvidia_nim",
            selected_model="nvidia/nemotron-3-ultra-550b-a55b",
            fallback_occurred=False,
            policy_metadata={
                "provider_eligibility_snapshot": {
                    "snapshot_ref": "objects/provider-eligibility/sha256/abc.json",
                    "content_sha256": "abc",
                    "effective_candidates": [
                        {
                            "candidate_id": "ai.provider.nvidia-nim.nemotron-3-ultra",
                            "provider_id": "nvidia_nim",
                            "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
                            "status": "ACCEPTED",
                            "reasons": [],
                        }
                    ],
                }
            },
        )
        _decision, evidence = module.select_harness_replan(
            route_fn=lambda request: decision,
            request_cls=RequestFixture,
        )
        plan = evidence["route_plan"]
        self.assertEqual(plan["schema"], "HarnessOmniRoutePlan/v1")
        self.assertEqual(plan["authority"], "DEEPSEEK_HARNESS")
        self.assertTrue(plan["route_plan_id"].startswith("harness-omniroute-"))
        self.assertEqual(len(plan["route_plan_sha256"]), 64)
        self.assertTrue(
            plan["logical_claude_model"].startswith("combo/harness-claude-")
        )
        self.assertEqual(
            evidence["logical_claude_model"],
            plan["logical_claude_model"],
        )
        self.assertEqual(evidence["status"], "ROUTE_PLAN_MATERIALIZED")
        self.assertFalse(evidence["fallback_occurred"])


if __name__ == "__main__":
    unittest.main()
