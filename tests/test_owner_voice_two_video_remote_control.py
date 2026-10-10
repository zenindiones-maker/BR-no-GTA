"""Fail-closed A15/Termux control-plane tests. Never run model locally."""
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "owner_voice_two_video_remote_control.py"
spec = importlib.util.spec_from_file_location("voice_remote_control", SCRIPT)
ctrl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctrl)


class RemoteControlContracts(unittest.TestCase):
    def test_exact_existing_codespace_is_admitted_only_from_correct_repository(self):
        payload = [{"name": ctrl.CODESPACE, "repository": ctrl.REPO, "state": "Available"}]
        self.assertEqual(ctrl.find_authorized_target(payload), ctrl.CODESPACE)
        with self.assertRaisesRegex(ctrl.ControlBlocked, "TARGET"):
            ctrl.find_authorized_target([{"name": ctrl.CODESPACE,
                                          "repository": "other/other",
                                          "state": "Available"}])

    def test_inactive_codespace_fails_closed_instead_of_auto_starting(self):
        with self.assertRaisesRegex(ctrl.ControlBlocked, "NOT_RUNNING"):
            ctrl.find_authorized_target([{"name": ctrl.CODESPACE,
                                          "repository": ctrl.REPO,
                                          "state": "Shutdown"}])

    def test_not_found_does_not_create_a_codespace(self):
        with self.assertRaisesRegex(ctrl.ControlBlocked, "TARGET"):
            ctrl.find_authorized_target([])

    def test_remote_shell_pins_repository_and_does_not_process_on_phone(self):
        text = ctrl.remote_script()
        self.assertIn("git fetch", text)
        self.assertIn("git show", text)
        self.assertIn("owner_voice_two_video_codespace_run.py", text)
        self.assertIn("CODESPACES", text)
        self.assertIn("GITHUB_REPOSITORY", text)
        self.assertIn("set -euo pipefail", text)
        self.assertNotIn(chr(92) + "${", text, "shell env variables must expand remotely")
        check = subprocess.run(["bash", "-n"], input=text, text=True,
                               capture_output=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertNotIn("yt-dlp", text)
        self.assertNotIn("pip install", text)

    def test_single_gh_ssh_command_and_no_local_asr(self):
        calls = []
        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[:3] == ["gh", "codespace", "list"]:
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps([
                    {"name": ctrl.CODESPACE, "repository": ctrl.REPO,
                     "state": "Available"}
                ]), stderr="")
            if argv[:3] == ["gh", "codespace", "ssh"]:
                return subprocess.CompletedProcess(argv, 0)
            self.fail("unexpected local subprocess: " + repr(argv))
        with patch.object(ctrl.shutil, "which", return_value="/usr/bin/gh"):
            with patch.object(ctrl.subprocess, "run", side_effect=fake_run):
                self.assertEqual(ctrl.main({"CODESPACES": "false"}), 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][0][:5],
                         ["gh", "codespace", "ssh", "-c", ctrl.CODESPACE])
        self.assertTrue(any("bash -lc" in part for part in calls[1][0]))

    def test_local_codespace_invocation_denied_before_any_gh(self):
        with patch.object(ctrl.subprocess, "run") as runner:
            with self.assertRaisesRegex(ctrl.ControlBlocked, "CONTROL_PLANE"):
                ctrl.main({"CODESPACES": "true"})
            runner.assert_not_called()

    def test_ssh_error_propagates_without_retry(self):
        calls = []
        def fake_run(argv, **kwargs):
            calls.append(argv)
            if argv[2] == "list":
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps([
                    {"name": ctrl.CODESPACE, "repository": ctrl.REPO, "state": "Available"}
                ]), stderr="")
            return subprocess.CompletedProcess(argv, 42)
        with patch.object(ctrl.shutil, "which", return_value="/usr/bin/gh"):
            with patch.object(ctrl.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(ctrl.ControlBlocked, "SSH_FAILED"):
                    ctrl.main({"CODESPACES": "false"})
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
