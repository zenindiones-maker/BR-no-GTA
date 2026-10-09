"""First-party BR-no-GTA REA provenance and no-cross-project regression."""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = "docs/operations/br-v23-rea-native-provenance.md"


class NativeREAProvenanceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        cls.doc = (ROOT / PROVENANCE).read_text(encoding="utf-8")
        cls.workflow = (
            ROOT / ".github/workflows/br-v23-rea6-frontend-research.yml"
        ).read_text(encoding="utf-8")

    def test_agents_require_existing_br_native_rea(self):
        self.assertIn(PROVENANCE, self.agents)
        self.assertIn("DeepSeek Harness", self.agents)
        self.assertIn("import another project's", self.agents)

    def test_all_three_br_source_branches_are_bound(self):
        for branch in (
            "work/br-extreme-reverse-engineering-v1",
            "work/br-reverse-engineering-evidence-v3",
            "work/br-reverse-engineering-experiment-intelligence-v4",
        ):
            with self.subTest(branch=branch):
                self.assertIn(branch, self.doc)
        self.assertIn("integrations/rea_install_and_doctor.sh", self.doc)
        self.assertIn("scripts/br_reverse_engineering_harness.py", self.doc)

    def test_evidence_does_not_overclaim_on_host_runtime_or_production(self):
        for marker in (
            "V23_CODESPACE_REA_INSTALLED=NOT_VERIFIED",
            "V23_REA_NATIVE_HARNESS_INTEGRATED=NOT_PROVEN",
            "FULL_REVERSE_ENGINEERING_OF_ALL_FUNCTIONALITY=NOT_PROVEN",
            "GITHUB_CANONICAL_PROMOTION=NOT_ATTEMPTED",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.doc)

    def test_v23_probe_is_br_only_and_never_claims_native_ghidra(self):
        self.assertIn("video-engine/frontend", self.workflow)
        self.assertIn("rea-agents@6.0.0", self.workflow)
        self.assertIn("BR_REA6_GHIDRA_NATIVE=NOT_ATTEMPTED", self.workflow)
        self.assertIn("BR_REA6_PRODUCTION=BLOCKED", self.workflow)
        self.assertNotIn("Hazewave", self.workflow)
        self.assertNotIn("HAZEWAVE_", self.workflow)


if __name__ == "__main__":
    unittest.main()
