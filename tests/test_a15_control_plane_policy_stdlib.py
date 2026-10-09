"""Regression contracts for the A15 remote-control-only owner directive.

Static governance checks do not claim all runtime workloads are inspected.
The V23 bootstrap's live identity gate is covered separately.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = "docs/governance/a15-control-plane-only.md"


class A15ControlPlanePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        cls.policy = (ROOT / POLICY).read_text(encoding="utf-8")
        cls.operations = (
            ROOT / "docs/operations/br-v23-codespace-free-quota.md"
        ).read_text(encoding="utf-8")

    def test_agent_map_references_canonical_policy(self):
        self.assertIn(POLICY, self.agents)
        self.assertIn("control plane only", self.agents.lower())

    def test_policy_denies_a15_as_compute_or_fallback(self):
        for text in (
            "NÃO",
            "Qwen3-TTS",
            "FFmpeg",
            "datasets",
            "checkpoints",
            "fallback",
            "Termux",
        ):
            with self.subTest(text=text):
                self.assertIn(text, self.policy)

    def test_preserves_remote_workstation_and_spending_boundaries(self):
        for text in ("Codespaces", "GitHub Actions", "franquia", "Harness"):
            with self.subTest(text=text):
                self.assertIn(text, self.policy)
        self.assertIn("CODESPACES", self.operations)

    def test_a15_is_not_required_for_qwen_runtime(self):
        from scripts.workstations.br_v23_codespace_bootstrap import (
            EXPECTED_BRANCH, EXPECTED_CODESPACE, validate_identity,
        )
        # A correct repository/branch cannot override Android boundary.
        with self.assertRaisesRegex(RuntimeError, "NO_A15_EXECUTION"):
            validate_identity(
                {"CODESPACES": "false", "CODESPACE_NAME": EXPECTED_CODESPACE},
                branch=EXPECTED_BRANCH,
                remote="https://github.com/zenindiones-maker/BR-no-GTA",
            )


if __name__ == "__main__":
    unittest.main()
