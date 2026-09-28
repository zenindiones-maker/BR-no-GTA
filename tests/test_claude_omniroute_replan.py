from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "agent-tooling" / "claude_omniroute_replan.py"


def load_module():
    spec = importlib.util.spec_from_file_location("claude_omniroute_replan", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ClaudeOmniRouteReplanTests(unittest.TestCase):
    def test_replan_request_excludes_failed_opencode_pair_and_requires_coding_route(self):
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
        self.assertEqual(values["allowed_providers"], ("nvidia_nim",))
        self.assertEqual(
            set(values["required_model_capabilities"]),
            {"reasoning", "coding", "structured_output"},
        )
        self.assertFalse(values["fallback_allowed"])
        self.assertTrue(values["zero_cost_operation"])

    def test_nvidia_harness_identity_maps_to_explicit_omniroute_identity(self):
        module = load_module()
        mapped = module.omniroute_identity(
            "nvidia_nim", "nvidia/nemotron-3-ultra-550b-a55b"
        )
        self.assertEqual(mapped["provider"], "nvidia")
        self.assertEqual(
            mapped["model"],
            "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
        )

    def test_unknown_provider_mapping_fails_closed(self):
        module = load_module()
        with self.assertRaises(ValueError):
            module.omniroute_identity("tuxevil", "gemini-3-flash")


if __name__ == "__main__":
    unittest.main()
