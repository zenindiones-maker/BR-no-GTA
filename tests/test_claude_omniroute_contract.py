from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "agent-tooling" / "claude_omniroute_contract.py"
WORKFLOW = ROOT / ".github" / "workflows" / "claude-code-omniroute-proof.yml"
AUTH_WORKFLOW = ROOT / ".github" / "workflows" / "claude-code-auth-validation.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("claude_omniroute_contract", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ClaudeOmniRouteContractTests(unittest.TestCase):
    def test_build_env_pins_loopback_gateway_and_model(self):
        module = load_module()
        env = module.build_gateway_env(provider="opencode", model="oc/big-pickle")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:20128")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "omniroute-no-auth")
        self.assertEqual(env["ANTHROPIC_MODEL"], "oc/big-pickle")
        self.assertEqual(env["ANTHROPIC_CUSTOM_MODEL_OPTION"], "oc/big-pickle")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
        self.assertNotIn("CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", env)

    def test_rejects_autonomous_routing_and_v1_suffix(self):
        module = load_module()
        with self.assertRaises(ValueError):
            module.build_gateway_env(provider="auto", model="oc/big-pickle")
        with self.assertRaises(ValueError):
            module.build_gateway_env(provider="opencode", model="auto")
        with self.assertRaises(ValueError):
            module.build_gateway_env(
                provider="opencode",
                model="oc/big-pickle",
                base_url="http://127.0.0.1:20128/v1",
            )

    def test_zero_cost_proof_allows_only_current_proven_route(self):
        module = load_module()
        self.assertEqual(
            module.validate_zero_cost_proof_selection("opencode", "oc/big-pickle"),
            ("opencode", "oc/big-pickle"),
        )
        with self.assertRaises(ValueError):
            module.validate_zero_cost_proof_selection("nvidia_nim", "z-ai/glm-5.3")

    def test_contract_cli_does_not_print_token(self):
        result = subprocess.run(
            [
                sys.executable,
                str(MODULE),
                "--provider",
                "opencode",
                "--model",
                "oc/big-pickle",
                "--zero-cost-proof",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("CLAUDE_OMNIROUTE_CONTRACT=PASS", result.stdout)
        self.assertNotIn("omniroute-no-auth", result.stdout)

    def test_live_workflow_is_read_only_and_harness_pinned(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ANTHROPIC_BASE_URL: http://127.0.0.1:20128", text)
        self.assertIn("ANTHROPIC_AUTH_TOKEN: omniroute-no-auth", text)
        self.assertIn("ANTHROPIC_MODEL: ${{ inputs.model || 'oc/big-pickle' }}", text)
        self.assertIn("ANTHROPIC_CUSTOM_MODEL_OPTION: ${{ inputs.model || 'oc/big-pickle' }}", text)
        self.assertIn('--tools ""', text)
        self.assertIn("--permission-prompts none", text)
        self.assertIn("--no-session-persistence", text)
        self.assertIn("--restricted", text)
        self.assertNotIn("--dangerously-skip-permissions", text)
        self.assertNotIn("secrets.ANTHROPIC_API_KEY", text)
        self.assertNotIn("secrets.CLAUDE_CODE_OAUTH_TOKEN", text)
        self.assertIn("git status --porcelain", text)
        self.assertIn("Probe OmniRoute OpenAI-compatible baseline", text)
        self.assertIn("/v1/providers/$HARNESS_SELECTED_PROVIDER/chat/completions", text)
        self.assertIn("Probe OmniRoute Anthropic Messages endpoint", text)
        self.assertIn("Classify OmniRoute Claude compatibility", text)
        self.assertIn("Resolve Harness-governed replan", text)
        self.assertIn("claude_omniroute_replan.py", text)
        self.assertIn("secrets.NVIDIA_API_KEY", text)
        self.assertIn("omniroute setup --non-interactive", text)
        self.assertIn("Re-probe OmniRoute Anthropic Messages after Harness replan", text)
        self.assertIn("OMNIROUTE_SELECTED_MODEL", text)
        self.assertIn('--model "$OMNIROUTE_SELECTED_MODEL"', text)
        self.assertIn("SHARED_ROUTE_UNAVAILABLE", text)
        self.assertIn("ANTHROPIC_MESSAGES_INCOMPATIBLE", text)
        self.assertIn("/v1/messages", text)
        self.assertIn('"anthropic-version": "2023-06-01"', text)
        self.assertIn("ClaudeCodeOmniRouteProof/v1", text)
        self.assertIn("if: ${{ always() }}", text)
        self.assertIn("if-no-files-found: warn", text)

    def test_legacy_auth_workflow_no_longer_requires_anthropic_secret(self):
        text = AUTH_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("secrets.ANTHROPIC_API_KEY", text)
        self.assertNotIn("secrets.CLAUDE_CODE_OAUTH_TOKEN", text)
        self.assertIn("claude_omniroute_contract.py", text)


if __name__ == "__main__":
    unittest.main()
