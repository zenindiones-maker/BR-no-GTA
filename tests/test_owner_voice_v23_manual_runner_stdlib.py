"""Safety regressions for the *new* V23 diagnostic launcher, stdlib only."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.owner_voice_v23_manual_runner import (
    validate_diagnostic_environment, main, WORKFLOW,
)


class V23DiagnosticRunnerContracts(unittest.TestCase):
    def setUp(self):
        self.root_context = tempfile.TemporaryDirectory()
        self.addCleanup(self.root_context.cleanup)
        self.root = Path(self.root_context.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.private.chmod(0o700)
        self.env = {
            "BR_OWNER_V23_ABLATION_ONLY": "1",
            "BR_OWNER_V23_DIAGNOSTIC_AUTHORIZED": "1",
            "TELEGRAM_BOT_TOKEN": "local-non-network-fixture",
            "BR_OWNER_TELEGRAM_REFERENCE_INDEX": '{"references":[]}',
            "BR_OWNER_AUDITION_WORKSPACE": str(self.private),
            "GITHUB_ACTIONS": "true",
            "GITHUB_WORKFLOW": WORKFLOW,
            "RUNNER_TEMP": str(self.root),
        }

    def fail_with(self, marker):
        with self.assertRaisesRegex(RuntimeError, marker):
            validate_diagnostic_environment(self.env, repository_root=self.repo)

    def test_denies_missing_ablation_only_mode(self):
        self.env.pop("BR_OWNER_V23_ABLATION_ONLY")
        self.fail_with("EXPLICIT_AUTHORIZATION_REQUIRED")

    def test_denies_missing_owner_authority(self):
        self.env.pop("BR_OWNER_V23_DIAGNOSTIC_AUTHORIZED")
        self.fail_with("EXPLICIT_AUTHORIZATION_REQUIRED")

    def test_denies_execution_from_any_other_actions_workflow(self):
        self.env["GITHUB_WORKFLOW"] = "BR_OWNER_V1 Single Human Clone"
        self.fail_with("UNTRUSTED_WORKFLOW")

    def test_denies_missing_owner_reference_access(self):
        self.env.pop("TELEGRAM_BOT_TOKEN")
        self.fail_with("OWNER_REFERENCE_ACCESS_MISSING")

    def test_denies_missing_owner_reference_index(self):
        self.env.pop("BR_OWNER_TELEGRAM_REFERENCE_INDEX")
        self.fail_with("OWNER_REFERENCE_INDEX_MISSING")

    def test_denies_insecure_private_directory(self):
        self.private.chmod(0o755)
        self.fail_with("WORKSPACE_PERMISSIONS_INSECURE")

    def test_denies_workspace_inside_repository(self):
        child = self.repo / "private"
        child.mkdir(mode=0o700)
        child.chmod(0o700)
        self.env["BR_OWNER_AUDITION_WORKSPACE"] = str(child)
        self.fail_with("WORKSPACE_INSIDE_REPOSITORY")

    def test_denies_existing_receipt_to_avoid_overwriting_evidence(self):
        (self.private / "v23-private-ablation.json").write_text("preserved")
        self.fail_with("EXISTING_RECEIPT_REFUSE_OVERWRITE")

    def test_denies_workspace_outside_runner_temp(self):
        self.env["RUNNER_TEMP"] = str(self.repo)
        self.fail_with("OUTSIDE_RUNNER_TEMP")

    def test_denies_symlink_workspace(self):
        alias = self.root / "alias"
        alias.symlink_to(self.private)
        self.env["BR_OWNER_AUDITION_WORKSPACE"] = str(alias)
        self.fail_with("PRIVATE_WORKSPACE_INVALID")

    def test_authorized_diagnostic_calls_existing_runtime_once_and_no_delivery(self):
        calls = []
        fake = SimpleNamespace(main=lambda: calls.append("existing") or 0)
        with (
            patch.dict(os.environ, self.env, clear=True),
            patch.dict(sys.modules, {"scripts.owner_voice_single_human_clone": fake}),
            patch("scripts.owner_voice_v23_manual_runner.Path.cwd", return_value=self.repo),
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(calls, ["existing"])

    def test_validated_environment_returns_exact_private_path(self):
        self.assertEqual(
            validate_diagnostic_environment(self.env, repository_root=self.repo),
            self.private.resolve(),
        )


if __name__ == "__main__":
    unittest.main()
