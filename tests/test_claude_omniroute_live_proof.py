from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "agent-tooling" / "claude_omniroute_live_proof.py"


def load_module():
    spec = importlib.util.spec_from_file_location("claude_omniroute_live_proof", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def plan():
    return {
        "schema": "HarnessOmniRoutePlan/v1",
        "route_plan_id": "harness-omniroute-test",
        "route_plan_sha256": "a" * 64,
        "logical_claude_model": "combo/harness-claude-0123456789abcdef",
        "omniroute_combo_name": "harness-claude-0123456789abcdef",
        "strategy": "priority",
        "candidate_targets": [
            {
                "candidate_id": "n1",
                "harness_provider": "nvidia_nim",
                "harness_model": "nvidia/nemotron-3-ultra-550b-a55b",
                "omniroute_provider": "nvidia",
                "omniroute_model": "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
                "credential_env": "NVIDIA_API_KEY",
                "authorized_target": True,
                "priority_rank": 0,
            },
            {
                "candidate_id": "n2",
                "harness_provider": "nvidia_nim",
                "harness_model": "nvidia/backup-model",
                "omniroute_provider": "nvidia",
                "omniroute_model": "nvidia/nvidia/backup-model",
                "credential_env": "NVIDIA_API_KEY",
                "authorized_target": True,
                "priority_rank": 1,
            },
        ],
    }


class ClaudeOmniRouteLiveProofTests(unittest.TestCase):
    def test_credential_preflight_records_presence_not_secret(self):
        module = load_module()
        evidence = module.credential_preflight(
            plan(),
            environ={"NVIDIA_API_KEY": "nv-secret-value"},
        )
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["credentials"][0]["env_name"], "NVIDIA_API_KEY")
        self.assertTrue(evidence["credentials"][0]["present"])
        serialized = json.dumps(evidence, sort_keys=True)
        self.assertNotIn("nv-secret-value", serialized)
        self.assertNotIn("credential_value", serialized)

    def test_missing_credential_is_typed_failure(self):
        module = load_module()
        evidence = module.credential_preflight(plan(), environ={})
        self.assertEqual(evidence["status"], "FAIL")
        self.assertEqual(evidence["failure_class"], "CREDENTIAL_NOT_MATERIALIZED")

    def test_failure_classification_is_causal(self):
        module = load_module()
        self.assertEqual(module.classify_http_failure(401), "CREDENTIAL_FAILURE")
        self.assertEqual(module.classify_http_failure(403), "UPSTREAM_DENIED_HTTP_403")
        self.assertEqual(module.classify_http_failure(404), "MODEL_RUNTIME_UNAVAILABLE")
        self.assertEqual(module.classify_http_failure(429), "QUOTA_OR_RATE_LIMIT")
        self.assertEqual(module.classify_http_failure(500), "UPSTREAM_FAILURE")

    def test_combo_admission_requires_direct_and_dedicated_pass(self):
        module = load_module()
        direct = {
            "canaries": [
                {"candidate_id": "n1", "status": "PASS"},
                {"candidate_id": "n2", "status": "PASS"},
            ]
        }
        dedicated = {
            "canaries": [
                {"candidate_id": "n1", "status": "PASS"},
                {"candidate_id": "n2", "status": "FAIL"},
            ]
        }
        rows = module.qualified_targets(plan(), direct, dedicated)
        self.assertEqual([row["candidate_id"] for row in rows], ["n1"])
        self.assertEqual(
            module.combo_models(rows),
            ["nvidia/nvidia/nemotron-3-ultra-550b-a55b"],
        )

    def test_dispatch_target_must_match_exact_authorized_identity(self):
        module = load_module()
        self.assertTrue(
            module.is_authorized_target(
                plan(),
                "nvidia",
                "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
            )
        )
        self.assertTrue(
            module.is_authorized_target(
                plan(),
                "nvidia",
                "nvidia/nemotron-3-ultra-550b-a55b",
            )
        )
        self.assertFalse(module.is_authorized_target(plan(), "openai", "gpt-5"))
        self.assertFalse(
            module.is_authorized_target(
                plan(),
                "nvidia",
                "nvidia/nemotron-3-ultra-550b-a55b-extra",
            )
        )


if __name__ == "__main__":
    unittest.main()
