"""V23 Codespace bootstrap identity and fail-closed, offline unit contracts."""
from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.workstations.br_v23_codespace_bootstrap import (
    EXPECTED_BRANCH, EXPECTED_CODESPACE, MIN_FREE_BYTES, TEST_PATTERNS,
    validate_identity, main,
)


class CodespaceBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "CODESPACES": "true",
            "CODESPACE_NAME": EXPECTED_CODESPACE,
        }
        self.remote = "https://github.com/zenindiones-maker/BR-no-GTA"
        self.branch = EXPECTED_BRANCH

    def test_correct_codespace_and_https_repo(self):
        validate_identity(self.environment, branch=self.branch, remote=self.remote)

    def test_accepts_github_ssh_remote(self):
        validate_identity(
            self.environment,
            branch=self.branch,
            remote="git@github.com:zenindiones-maker/BR-no-GTA.git",
        )

    def test_denies_termux_even_with_identical_git_checkout(self):
        self.environment["CODESPACES"] = "false"
        with self.assertRaisesRegex(RuntimeError, "NO_A15_EXECUTION"):
            validate_identity(self.environment, branch=self.branch, remote=self.remote)

    def test_denies_missing_codespaces_marker(self):
        self.environment.pop("CODESPACES")
        with self.assertRaisesRegex(RuntimeError, "CODESPACE_REQUIRED"):
            validate_identity(self.environment, branch=self.branch, remote=self.remote)

    def test_denies_other_codespace_including_hazewave(self):
        self.environment["CODESPACE_NAME"] = "hazewave-zero-cost"
        with self.assertRaisesRegex(RuntimeError, "IDENTITY_MISMATCH"):
            validate_identity(self.environment, branch=self.branch, remote=self.remote)

    def test_denies_old_original_git_branch(self):
        with self.assertRaisesRegex(RuntimeError, "BRANCH_MISMATCH"):
            validate_identity(
                self.environment,
                branch="work/gate6f-analytics-learning",
                remote=self.remote,
            )

    def test_denies_other_git_repo(self):
        with self.assertRaisesRegex(RuntimeError, "REMOTE_REPOSITORY_MISMATCH"):
            validate_identity(
                self.environment,
                branch=self.branch,
                remote="https://github.com/zenindiones-maker/Hazewave-",
            )

    def test_denies_lookalike_hostname(self):
        with self.assertRaisesRegex(RuntimeError, "REMOTE_REPOSITORY_MISMATCH"):
            validate_identity(
                self.environment,
                branch=self.branch,
                remote="https://github.com.evil.test/zenindiones-maker/BR-no-GTA",
            )

    def test_denies_wrong_case_or_suffix(self):
        with self.assertRaisesRegex(RuntimeError, "REMOTE_REPOSITORY_MISMATCH"):
            validate_identity(
                self.environment,
                branch=self.branch,
                remote="https://github.com/zenindiones-maker/BR-no-GTA-other",
            )

    def test_has_substantial_storage_reserve(self):
        self.assertGreaterEqual(MIN_FREE_BYTES, 2 * 1024 ** 3)

    def test_named_test_patterns_are_explicit_and_local(self):
        self.assertEqual(3, len(TEST_PATTERNS))
        self.assertTrue(all(not str(pattern).startswith("/") for pattern in TEST_PATTERNS))

    def test_main_doctor_refuses_missing_codespace_before_any_setup(self):
        with patch.dict(os.environ, {}, clear=True):
            # The module entry point translates this fail-closed exception
            # into a nonzero shell exit. Unit code must assert the exception.
            with self.assertRaisesRegex(RuntimeError, "CODESPACE_REQUIRED"):
                main(["--doctor"])


if __name__ == "__main__":
    unittest.main()
