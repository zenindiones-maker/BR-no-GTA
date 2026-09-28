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

    def test_official_json_envelope_is_recovered_from_diagnostic_stdout(self):
        module = load_module()
        payload = {
            "connection": {
                "id": "conn-nvidia-prefixed",
                "provider": "nvidia",
                "name": "harness-nvidia-prefixed",
            }
        }
        raw = "OmniRoute diagnostic: provider sync scheduled\n" + json.dumps(payload) + "\n"
        parsed = module._parse_json_object(raw)
        self.assertEqual(parsed, payload)

    def test_multiple_json_documents_are_rejected_as_ambiguous(self):
        module = load_module()
        raw = '{"status":"one"}\n{"status":"two"}\n'
        self.assertIsNone(module._parse_json_object(raw))

    def test_unsupported_nvidia_cli_provider_test_defers_to_dedicated_canary(self):
        module = load_module()
        result = CompletedProcess(
            ["omniroute", "providers", "test", "conn-nvidia-123", "--json"],
            1,
            json.dumps({
                "connection": {
                    "id": "conn-nvidia-123",
                    "provider": "nvidia",
                    "name": "harness-nvidia",
                },
                "valid": False,
                "unsupported": True,
                "skipped": True,
                "error": "Provider test not supported",
            }),
            "",
        )
        outcome = module._classify_provider_test_result(result)
        self.assertEqual(outcome["status"], "UNSUPPORTED")
        self.assertFalse(outcome["supported"])
        self.assertIsNone(outcome["failure_class"])
        self.assertEqual(
            outcome["next_validation"],
            "DEDICATED_PROVIDER_CANARY",
        )

    def test_supported_invalid_provider_test_remains_fail_closed(self):
        module = load_module()
        result = CompletedProcess(
            ["omniroute", "providers", "test", "conn-nvidia-123", "--json"],
            1,
            json.dumps({
                "valid": False,
                "skipped": False,
                "error": "Invalid API key",
                "statusCode": 401,
            }),
            "",
        )
        outcome = module._classify_provider_test_result(result)
        self.assertEqual(outcome["status"], "FAIL")
        self.assertEqual(outcome["failure_class"], "OMNIROUTE_PROVIDER_TEST_FAILURE")

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
            materialized = module._materialize_provider(
                target,
                base_url="http://127.0.0.1:20128",
            )

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

    def test_nvidia_cli_provider_test_unsupported_defers_to_dedicated_canary(self):
        module = load_module()
        target = plan()["candidate_targets"][0]
        add_payload = json.dumps({
            "connection": {
                "id": "conn-nvidia-unsupported",
                "provider": "nvidia",
                "name": module._provider_connection_name(target),
            }
        })
        unsupported_payload = json.dumps({
            "connection": {
                "id": "conn-nvidia-unsupported",
                "provider": "nvidia",
            },
            "valid": False,
            "unsupported": True,
            "skipped": True,
            "error": "Provider test not supported",
        })

        def fake_run(command, *, env=None):
            if command[:3] == ["omniroute", "providers", "add"]:
                return CompletedProcess(command, 0, add_payload, "")
            if command[:3] == ["omniroute", "providers", "validate"]:
                return CompletedProcess(command, 0, '{"results":[]}', "")
            if command[:3] == ["omniroute", "providers", "test"]:
                return CompletedProcess(command, 1, unsupported_payload, "")
            return CompletedProcess(command, 0, "{}", "")

        with mock.patch.object(module, "_run", side_effect=fake_run):
            materialized = module._materialize_provider(
                target,
                base_url="http://127.0.0.1:20128",
            )

        self.assertTrue(materialized["ok"])
        self.assertEqual(
            materialized["provider_test_status"],
            "UNSUPPORTED",
        )
        self.assertFalse(materialized["provider_test_supported"])
        self.assertIsNone(materialized["failure_class"])

    def test_provider_materialization_reconciles_unique_connection_from_active_server_api(self):
        module = load_module()
        target = plan()["candidate_targets"][0]
        expected_name = module._provider_connection_name(target)
        commands = []

        def fake_run(command, *, env=None):
            commands.append(command)
            if command[:3] == ["omniroute", "providers", "add"]:
                return CompletedProcess(command, 0, '{"status":"created"}', "")
            return CompletedProcess(command, 0, "{}", "")

        server_payload = {
            "connections": [{
                "id": "conn-nvidia-server",
                "provider": "nvidia",
                "name": expected_name,
            }]
        }
        with (
            mock.patch.object(module, "_run", side_effect=fake_run),
            mock.patch.object(
                module,
                "_http_get_json",
                return_value=(200, server_payload),
            ),
        ):
            materialized = module._materialize_provider(
                target,
                base_url="http://127.0.0.1:20128",
            )

        self.assertTrue(materialized["ok"])
        self.assertEqual(materialized["connection_id"], "conn-nvidia-server")
        self.assertEqual(
            materialized["connection_id_source"],
            "SERVER_MANAGEMENT_API",
        )
        self.assertNotIn(
            ["omniroute", "providers", "list", "--json"],
            commands,
        )
        self.assertIn(
            ["omniroute", "providers", "test", "conn-nvidia-server", "--json"],
            commands,
        )

    def test_provider_materialization_fails_closed_on_ambiguous_server_connection_reconciliation(self):
        module = load_module()
        target = plan()["candidate_targets"][0]
        expected_name = module._provider_connection_name(target)

        def fake_run(command, *, env=None):
            if command[:3] == ["omniroute", "providers", "add"]:
                return CompletedProcess(command, 0, '{"status":"created"}', "")
            return CompletedProcess(command, 0, "{}", "")

        payload = {
            "connections": [
                {"id": "conn-a", "provider": "nvidia", "name": expected_name},
                {"id": "conn-b", "provider": "nvidia", "name": expected_name},
            ]
        }
        with (
            mock.patch.object(module, "_run", side_effect=fake_run),
            mock.patch.object(module, "_http_get_json", return_value=(200, payload)),
        ):
            materialized = module._materialize_provider(
                target,
                base_url="http://127.0.0.1:20128",
            )

        self.assertFalse(materialized["ok"])
        self.assertIsNone(materialized["connection_id"])
        self.assertEqual(
            materialized["failure_class"],
            "OMNIROUTE_PROVIDER_CONNECTION_AMBIGUOUS",
        )

    def test_direct_pass_materializes_provider_before_dedicated_canary_and_catalog(self):
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

        def materialize(target, *, base_url):
            order.append("materialize")
            self.assertEqual(base_url, "http://127.0.0.1:20128")
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
                    side_effect=lambda command, **kwargs: CompletedProcess(
                        command,
                        0,
                        "--models" if command[-1:] == ["--help"] else "{}",
                        "",
                    ),
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

        self.assertEqual(order, ["direct", "materialize", "dedicated", "catalog"])

    def test_dedicated_pass_with_catalog_miss_remains_qualified_and_records_catalog_stale(self):
        module = load_module()
        one = plan()
        one["candidate_targets"] = [one["candidate_targets"][0]]
        target = one["candidate_targets"][0]

        def direct(candidate):
            return {
                "schema": "ProviderDirectCanary/v1",
                "candidate_id": candidate["candidate_id"],
                "status": "PASS",
                "failure_class": None,
                "http_status": 200,
            }

        def materialize(candidate, *, base_url):
            return {
                "ok": True,
                "connection_id": "conn-nvidia-123",
                "connection_identity_redacted": "sha256:deadbeef",
                "connection_id_source": "PROVIDERS_ADD_JSON",
                "provider_test_status": "UNSUPPORTED",
                "provider_test_supported": False,
                "failure_class": None,
            }

        def dedicated(candidate, base_url, *, connection_id):
            return {
                "schema": "OmniRouteProviderCanary/v1",
                "candidate_id": candidate["candidate_id"],
                "status": "PASS",
                "failure_class": None,
                "http_status": 200,
                "reported_provider": candidate["omniroute_provider"],
                "reported_model": candidate["omniroute_model"],
                "connection_identity_redacted": "sha256:deadbeef",
            }

        with TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            env_path = evidence_dir / "github-env"
            plan_path = evidence_dir / "plan.json"
            plan_path.write_text(json.dumps(one), encoding="utf-8")
            with (
                mock.patch.dict(module.os.environ, {"NVIDIA_API_KEY": "secret"}, clear=False),
                mock.patch.object(module, "_direct_canary", side_effect=direct),
                mock.patch.object(module, "_materialize_provider", side_effect=materialize),
                mock.patch.object(module, "_dedicated_canary", side_effect=dedicated),
                mock.patch.object(module, "_catalog_model_ids", return_value=set()),
                mock.patch.object(
                    module,
                    "_run",
                    side_effect=lambda command, **kwargs: CompletedProcess(
                        command,
                        0,
                        "--models" if command[-1:] == ["--help"] else "{}",
                        "",
                    ),
                ),
            ):
                module.qualify(
                    plan_path=plan_path,
                    evidence_dir=evidence_dir,
                    base_url="http://127.0.0.1:20128",
                    github_env=env_path,
                )

            evidence = json.loads(
                (evidence_dir / "provider-qualification.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [item["candidate_id"] for item in evidence["qualified_candidates"]],
                [target["candidate_id"]],
            )
            self.assertEqual(evidence["rejected_candidates"], [])
            catalog = evidence["catalog_observations"][0]
            self.assertFalse(catalog["omniroute_model_available"])
            self.assertEqual(
                catalog["failure_class"],
                "OMNIROUTE_CATALOG_STALE_OR_MAPPING_UNAVAILABLE",
            )
            stale = [
                item
                for item in evidence["failure_episodes"]
                if item.get("failure_class")
                == "OMNIROUTE_CATALOG_STALE_OR_MAPPING_UNAVAILABLE"
            ]
            self.assertEqual(len(stale), 1)
            self.assertFalse(stale[0]["admission_blocking"])

    def test_exact_connection_catalog_sync_proves_canonical_model(self):
        module = load_module()
        target = plan()["candidate_targets"][0]
        calls = []

        def fake_http(url, *, body, headers, timeout=180):
            calls.append(("POST", url, body, headers))
            return (
                200,
                12.5,
                json.dumps({
                    "ok": True,
                    "connectionId": "conn-nvidia-123",
                    "availableModelsCount": 1,
                    "models": [{
                        "id": "nvidia/nemotron-3-ultra-550b-a55b",
                        "name": "Nemotron 3 Ultra",
                    }],
                }),
                {
                    "ok": True,
                    "connectionId": "conn-nvidia-123",
                    "availableModelsCount": 1,
                    "models": [{
                        "id": "nvidia/nemotron-3-ultra-550b-a55b",
                        "name": "Nemotron 3 Ultra",
                    }],
                },
                {},
            )

        def fake_get(url, *, timeout=30):
            calls.append(("GET", url, None, None))
            return (
                200,
                {
                    "provider": "nvidia",
                    "connectionId": "conn-nvidia-123",
                    "models": [{
                        "id": "nvidia/nemotron-3-ultra-550b-a55b",
                        "name": "Nemotron 3 Ultra",
                    }],
                },
            )

        with (
            mock.patch.object(module, "_http_json", side_effect=fake_http),
            mock.patch.object(module, "_http_get_json", side_effect=fake_get),
        ):
            evidence = module._sync_exact_connection_catalog(
                target,
                connection_id="conn-nvidia-123",
                base_url="http://127.0.0.1:20128",
            )

        self.assertTrue(evidence["model_available"])
        self.assertEqual(evidence["status"], "PASS")
        self.assertIsNone(evidence["failure_class"])
        self.assertEqual(
            evidence["model"],
            "nvidia/nemotron-3-ultra-550b-a55b",
        )
        self.assertIn(
            (
                "POST",
                "http://127.0.0.1:20128/api/providers/conn-nvidia-123/sync-models?mode=import&quiet=1",
                {},
                {},
            ),
            calls,
        )
        self.assertIn(
            (
                "GET",
                "http://127.0.0.1:20128/api/providers/conn-nvidia-123/models?excludeCustom=true&chatOnly=true",
                None,
                None,
            ),
            calls,
        )
        self.assertNotIn("NVIDIA_API_KEY", json.dumps(evidence, sort_keys=True))

    def test_exact_connection_catalog_miss_is_typed_omniroute_failure(self):
        module = load_module()
        target = plan()["candidate_targets"][0]
        with (
            mock.patch.object(
                module,
                "_http_json",
                return_value=(200, 4.0, '{"models":[]}', {"models": []}, {}),
            ),
            mock.patch.object(
                module,
                "_http_get_json",
                return_value=(200, {"provider": "nvidia", "models": []}),
            ),
        ):
            evidence = module._sync_exact_connection_catalog(
                target,
                connection_id="conn-nvidia-123",
                base_url="http://127.0.0.1:20128",
            )

        self.assertFalse(evidence["model_available"])
        self.assertEqual(
            evidence["failure_class"],
            "OMNIROUTE_CATALOG_STALE_OR_MAPPING_UNAVAILABLE",
        )
        self.assertTrue(evidence["upstream_model_available"])
        self.assertFalse(evidence["omniroute_model_available"])

    def test_direct_pass_plus_catalog_miss_is_not_credential_or_provider_failure(self):
        module = load_module()
        self.assertEqual(
            module.catalog_mapping_failure_class(direct_upstream_passed=True),
            "OMNIROUTE_CATALOG_STALE_OR_MAPPING_UNAVAILABLE",
        )


if __name__ == "__main__":
    unittest.main()
