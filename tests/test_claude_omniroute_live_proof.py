from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock
from tempfile import TemporaryDirectory
from subprocess import CompletedProcess

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
                "upstream_provider": "nvidia",
                "upstream_model": "nvidia/nemotron-3-ultra-550b-a55b",
                "omniroute_model": "nvidia/nemotron-3-ultra-550b-a55b",
                "credential_env": "NVIDIA_API_KEY",
                "authorized_target": True,
                "priority_rank": 0,
            },
            {
                "candidate_id": "n2",
                "harness_provider": "nvidia_nim",
                "harness_model": "nvidia/backup-model",
                "omniroute_provider": "nvidia",
                "upstream_provider": "nvidia",
                "upstream_model": "nvidia/backup-model",
                "omniroute_model": "nvidia/backup-model",
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
            ["nvidia/nemotron-3-ultra-550b-a55b"],
        )

    def test_dispatch_target_must_match_exact_authorized_identity(self):
        module = load_module()
        self.assertTrue(
            module.is_authorized_target(
                plan(),
                "nvidia",
                "nvidia/nemotron-3-ultra-550b-a55b",
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

    def test_direct_canary_uses_upstream_model_identity(self):
        module = load_module()
        target = plan()["candidate_targets"][0]
        captured = {}

        def fake_http(url, *, body, headers, timeout=180):
            captured["url"] = url
            captured["model"] = body["model"]
            return (
                200,
                10.0,
                '{"choices":[{"message":{"content":"ROUTE_CANARY_OK"}}]}',
                {"choices": [{"message": {"content": "ROUTE_CANARY_OK"}}]},
                {},
            )

        with mock.patch.object(module, "_http_json", side_effect=fake_http):
            evidence = module._direct_canary(target)

        self.assertEqual(captured["model"], target["upstream_model"])
        self.assertEqual(evidence["candidate_id"], target["candidate_id"])
        self.assertEqual(evidence["upstream_provider"], "nvidia")
        self.assertEqual(
            evidence["upstream_model"],
            "nvidia/nemotron-3-ultra-550b-a55b",
        )

    def test_provider_materialization_captures_exact_connection_id_and_tests_it(self):
        module = load_module()
        target = plan()["candidate_targets"][0]
        commands = []
        add_payload = '{"connection":{"id":"conn-nvidia-123","provider":"nvidia","name":"harness-nvidia"}}'

        def fake_run(command, *, env=None):
            commands.append(command)
            if command[:3] == ["omniroute", "providers", "add"]:
                return CompletedProcess(command, 0, add_payload, "")
            return CompletedProcess(command, 0, "{}", "")

        with mock.patch.object(module, "_run", side_effect=fake_run):
            materialized = module._materialize_provider(target)

        self.assertTrue(materialized["ok"])
        self.assertEqual(materialized["connection_id"], "conn-nvidia-123")
        self.assertIn(
            ["omniroute", "providers", "test", "conn-nvidia-123", "--json"],
            commands,
        )
        self.assertNotIn(
            ["omniroute", "providers", "test", "harness-nvidia", "--json"],
            commands,
        )

    def test_direct_pass_materializes_provider_before_catalog_and_dedicated_canary(self):
        module = load_module()
        one = plan()
        one["candidate_targets"] = [one["candidate_targets"][0]]
        order = []
        candidate = one["candidate_targets"][0]

        def direct(target):
            order.append("direct")
            return {
                "schema": "ProviderDirectCanary/v1",
                "candidate_id": target["candidate_id"],
                "status": "PASS",
                "failure_class": None,
                "http_status": 200,
            }

        def materialize(target):
            order.append("materialize")
            return {
                "ok": True,
                "connection_id": "conn-nvidia-123",
                "connection_identity_redacted": "sha256:deadbeef",
                "failure_class": None,
            }

        def catalog(provider):
            order.append("catalog")
            return {candidate["omniroute_model"]}

        def dedicated(target, base_url, *, connection_id):
            order.append("dedicated")
            self.assertEqual(connection_id, "conn-nvidia-123")
            return {
                "schema": "OmniRouteProviderCanary/v1",
                "candidate_id": target["candidate_id"],
                "status": "PASS",
                "failure_class": None,
                "http_status": 200,
                "connection_identity_redacted": "sha256:deadbeef",
            }

        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "github-env"
            with (
                mock.patch.dict(module.os.environ, {"NVIDIA_API_KEY": "secret"}, clear=False),
                mock.patch.object(module, "_direct_canary", side_effect=direct),
                mock.patch.object(module, "_materialize_provider", side_effect=materialize),
                mock.patch.object(module, "_catalog_model_ids", side_effect=catalog),
                mock.patch.object(module, "_dedicated_canary", side_effect=dedicated),
                mock.patch.object(
                    module,
                    "_run",
                    return_value=CompletedProcess(["omniroute"], 0, "{}", ""),
                ),
            ):
                plan_path = Path(tmp) / "plan.json"
                plan_path.write_text(json.dumps(one), encoding="utf-8")
                module.qualify(
                    plan_path=plan_path,
                    evidence_dir=Path(tmp),
                    base_url="http://127.0.0.1:20128",
                    github_env=env_path,
                )

        self.assertEqual(order, ["direct", "materialize", "catalog", "dedicated"])

    def test_direct_pass_plus_catalog_miss_is_not_credential_or_provider_failure(self):
        module = load_module()
        self.assertEqual(
            module.catalog_mapping_failure_class(direct_upstream_passed=True),
            "OMNIROUTE_CATALOG_STALE_OR_MAPPING_UNAVAILABLE",
        )


if __name__ == "__main__":
    unittest.main()
