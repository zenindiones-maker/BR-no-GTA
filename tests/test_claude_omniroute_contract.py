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


def test_build_env_pins_loopback_gateway_and_model():
    module = load_module()
    env = module.build_gateway_env(provider="opencode", model="oc/big-pickle")
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:20128"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "omniroute-no-auth"
    assert env["ANTHROPIC_MODEL"] == "oc/big-pickle"
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY" not in env


def test_rejects_autonomous_routing_and_v1_suffix():
    module = load_module()
    with unittest.TestCase().assertRaises(ValueError):
        module.build_gateway_env(provider="auto", model="oc/big-pickle")
    with unittest.TestCase().assertRaises(ValueError):
        module.build_gateway_env(provider="opencode", model="auto")
    with unittest.TestCase().assertRaises(ValueError):
        module.build_gateway_env(
            provider="opencode",
            model="oc/big-pickle",
            base_url="http://127.0.0.1:20128/v1",
        )


def test_zero_cost_proof_allows_only_current_proven_route():
    module = load_module()
    assert module.validate_zero_cost_proof_selection(
        "opencode", "oc/big-pickle"
    ) == ("opencode", "oc/big-pickle")
    with unittest.TestCase().assertRaises(ValueError):
        module.validate_zero_cost_proof_selection("nvidia_nim", "z-ai/glm-5.3")


def test_contract_cli_does_not_print_token():
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
    assert result.returncode == 0
    assert "CLAUDE_OMNIROUTE_CONTRACT=PASS" in result.stdout
    assert "omniroute-no-auth" not in result.stdout


def test_live_workflow_is_read_only_and_harness_pinned():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ANTHROPIC_BASE_URL: http://127.0.0.1:20128" in text
    assert "ANTHROPIC_AUTH_TOKEN: omniroute-no-auth" in text
    assert "ANTHROPIC_MODEL: ${{ inputs.model || 'oc/big-pickle' }}" in text
    assert '--tools ""' in text
    assert "--permission-prompts none" in text
    assert "--no-session-persistence" in text
    assert "--restricted" in text
    assert "--dangerously-skip-permissions" not in text
    assert "secrets.ANTHROPIC_API_KEY" not in text
    assert "secrets.CLAUDE_CODE_OAUTH_TOKEN" not in text
    assert "git status --porcelain" in text


def test_legacy_auth_workflow_no_longer_requires_anthropic_secret():
    text = AUTH_WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.ANTHROPIC_API_KEY" not in text
    assert "secrets.CLAUDE_CODE_OAUTH_TOKEN" not in text
    assert "claude_omniroute_contract.py" in text
