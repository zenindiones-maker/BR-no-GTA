from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "agent-tooling" / "claude_omniroute_contract.py"
WORKFLOW = ROOT / ".github" / "workflows" / "claude-code-omniroute-proof.yml"
RUNTIME = ROOT / "scripts" / "agent-tooling" / "claude_omniroute_live_proof.py"
AUTH_WORKFLOW = ROOT / ".github" / "workflows" / "claude-code-auth-validation.yml"

LOGICAL_ROUTE = "combo/harness-claude-0123456789abcdef"


def load_module():
    spec = importlib.util.spec_from_file_location("claude_omniroute_contract", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ClaudeOmniRouteContractTests(unittest.TestCase):
    def test_build_env_pins_loopback_gateway_and_logical_route_alias(self):
        module = load_module()
        env = module.build_gateway_env(
            logical_model=LOGICAL_ROUTE,
            proof_mode=True,
        )
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:20128")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "omniroute-no-auth")
        self.assertEqual(env["ANTHROPIC_MODEL"], LOGICAL_ROUTE)
        self.assertEqual(env["ANTHROPIC_CUSTOM_MODEL_OPTION"], LOGICAL_ROUTE)
        self.assertEqual(env["OMNIROUTE_ENDPOINT_AUTH_MODE"], "PROOF_LOOPBACK_SENTINEL")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
        self.assertNotIn("NVIDIA_API_KEY", env)
        self.assertNotIn("CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", env)

    def test_rejects_physical_or_autonomous_models_and_v1_suffix(self):
        module = load_module()
        for invalid in (
            "auto",
            "auto/coding",
            "oc/big-pickle",
            "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
            "harness-claude-0123456789abcdef",
        ):
            with self.assertRaises(ValueError):
                module.build_gateway_env(logical_model=invalid, proof_mode=True)
        with self.assertRaises(ValueError):
            module.build_gateway_env(
                logical_model=LOGICAL_ROUTE,
                base_url="http://127.0.0.1:20128/v1",
                proof_mode=True,
            )

    def test_production_mode_requires_separate_endpoint_token(self):
        module = load_module()
        with self.assertRaises(ValueError):
            module.build_gateway_env(
                logical_model=LOGICAL_ROUTE,
                proof_mode=False,
            )
        env = module.build_gateway_env(
            logical_model=LOGICAL_ROUTE,
            proof_mode=False,
            auth_token="endpoint-scoped-token",
        )
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "endpoint-scoped-token")
        self.assertEqual(env["OMNIROUTE_ENDPOINT_AUTH_MODE"], "SCOPED_INFERENCE_KEY")

    def test_contract_cli_does_not_print_token(self):
        result = subprocess.run(
            [
                sys.executable,
                str(MODULE),
                "--logical-model",
                LOGICAL_ROUTE,
                "--proof-mode",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("CLAUDE_OMNIROUTE_CONTRACT=PASS", result.stdout)
        self.assertIn("PROOF_LOOPBACK_SENTINEL", result.stdout)
        self.assertNotIn("omniroute-no-auth", result.stdout)

    def test_live_workflow_materializes_bounded_route_and_never_exposes_physical_model_to_claude(self):
        text = WORKFLOW.read_text(encoding="utf-8") + "\n" + RUNTIME.read_text(encoding="utf-8")
        self.assertIn("ANTHROPIC_BASE_URL: http://127.0.0.1:20128", text)
        self.assertIn("REQUIRE_API_KEY: \"false\"", text)
        self.assertIn("OMNIROUTE_ENDPOINT_AUTH_MODE: PROOF_LOOPBACK_SENTINEL", text)
        self.assertIn("omniroute@3.8.50", text)
        self.assertNotIn("omniroute@latest", text)
        self.assertIn("dist.integrity", text)
        self.assertIn("HarnessOmniRoutePlan/v1", text)
        self.assertIn("python3 -m pip install -r requirements.txt", text)
        self.assertIn("Resolve Harness-governed replan", text)
        self.assertIn("HARNESS_OMNIROUTE_ROUTE_PLAN=PASS", text)
        self.assertIn("ProviderDirectCanary/v1", text)
        self.assertIn("CREDENTIAL_NOT_MATERIALIZED", text)
        self.assertIn("NVIDIA_API_KEY_PRESENT=true", text)
        self.assertIn("OmniRouteProviderCanary/v1", text)
        self.assertIn("omniroute providers add", text)
        self.assertIn("--credential-env", text)
        self.assertNotIn('--api-key "$NVIDIA_API_KEY"', text)
        self.assertIn("omniroute providers validate", text)
        self.assertIn("omniroute providers test", text)
        self.assertIn("omniroute combo create", text)
        self.assertIn("--strategy priority", text)
        self.assertNotIn("auto/coding", text)
        self.assertNotIn("ANTHROPIC_MODEL=auto", text)
        self.assertIn("OMNIROUTE_BOUNDED_COMBO=PASS", text)
        self.assertIn("Re-probe OmniRoute Anthropic Messages through bounded route", text)
        self.assertIn("X-OmniRoute-Provider", text)
        self.assertIn("X-OmniRoute-Model", text)
        self.assertIn("X-OmniRoute-Fallback-Attempts", text)
        self.assertIn("OmniRouteDispatchEvidence/v1", text)
        self.assertIn('--model "$HARNESS_MATERIALIZED_OMNIROUTE_ROUTE"', text)
        self.assertNotIn('--model "$OMNIROUTE_SELECTED_MODEL"', text)
        self.assertIn('--tools ""', text)
        self.assertIn("--permission-prompts none", text)
        self.assertIn("--no-session-persistence", text)
        self.assertIn("--restricted", text)
        self.assertNotIn("--dangerously-skip-permissions", text)
        self.assertNotIn("secrets.ANTHROPIC_API_KEY", text)
        self.assertNotIn("secrets.CLAUDE_CODE_OAUTH_TOKEN", text)
        self.assertIn("git status --porcelain", text)
        self.assertIn("UPSTREAM_DENIED_HTTP_403", text)
        self.assertIn("/v1/messages", text)
        self.assertIn('"anthropic-version": "2023-06-01"', text)
        self.assertIn("ClaudeCodeOmniRouteProof/v1", text)
        self.assertIn("if: ${{ always() }}", text)

    def test_gateway_boundary_tracks_new_route_plan_contract(self):
        text = AUTH_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("secrets.ANTHROPIC_API_KEY", text)
        self.assertNotIn("secrets.CLAUDE_CODE_OAUTH_TOKEN", text)
        self.assertIn("claude_omniroute_route_plan.py", text)
        self.assertIn("tests.test_claude_omniroute_route_plan", text)


if __name__ == "__main__":
    unittest.main()
