"""Static whole-repo inventory negative checks on real filesystem fixtures."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/br_system_static_surface_audit.py"
SPEC = importlib.util.spec_from_file_location("br_surface_audit", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class StaticSurfaceAuditTests(unittest.TestCase):
    def test_real_repository_has_traceable_source_surface(self):
        root = SCRIPT.parent.parent
        result = module.audit(root, module.tracked_sources(root))
        self.assertGreater(result["python_modules_parsed"], 150)
        self.assertGreater(result["workflows"], 0)
        self.assertGreater(result["observed_first_party_imports"], 0)
        self.assertEqual(result["status"], "OBSERVED_STATIC_NOT_RUNTIME_VERIFIED")
        self.assertEqual(len(result["full_candidate_sha256"]), 64)

    def test_insecure_workflow_and_dead_reference_reported_not_hidden(self):
        with tempfile.TemporaryDirectory(prefix="br-surface-negative-") as temp:
            root = Path(temp)
            (root / ".github/workflows").mkdir(parents=True)
            (root / "app/services").mkdir(parents=True)
            (root / "AGENTS.md").write_text("Required: `docs/governance/required.md`\n")
            (root / ".github/workflows/sample.yml").write_text(
                "name: insecure\non: push\njobs:\n  demo:\n"
                "    steps:\n      - uses: actions/checkout@v4\n",
            )
            (root / "app/services/target.py").write_text("import app.services.absent\n")
            paths = [
                "AGENTS.md", ".github/workflows/sample.yml", "app/services/target.py",
            ]
            evidence = module.audit(root, paths)
            kinds = evidence["candidate_counts"]
            self.assertIn("ACTION_NOT_PINNED_TO_FULL_SHA", kinds)
            self.assertIn("WORKFLOW_TOKEN_PERMISSIONS_UNVERIFIED", kinds)
            self.assertIn("POLICY_REFERENCE_MISSING", kinds)
            self.assertIn("FIRST_PARTY_IMPORT_UNRESOLVED_CANDIDATE", kinds)

    def test_works_without_secret_content_leaking(self):
        with tempfile.TemporaryDirectory(prefix="br-surface-sensitive-") as temp:
            root = Path(temp)
            root.joinpath("AGENTS.md").write_text("access_token_should_not_appear\n")
            output = module.audit(root, ["AGENTS.md"])
            self.assertNotIn("access_token_should_not_appear", str(output))
            self.assertEqual(output["candidate_total"], 0)


if __name__ == "__main__":
    unittest.main()
