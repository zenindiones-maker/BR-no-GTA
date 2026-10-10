"""Offline safety contracts for isolated existing-Codespace ASR environment repair."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "scripts" / "owner_voice_two_video_codespace_env.py"
spec = importlib.util.spec_from_file_location("acoustic_env", PATH)
envtool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(envtool)


class CodespaceEnvironmentContracts(unittest.TestCase):
    def test_rejects_a15_before_mutating_or_installing(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"CODESPACES": "false",
                                         "CODESPACE_NAME": ""}, clear=True):
                with self.assertRaisesRegex(envtool.EnvironmentBlocked, "AUTHORIZATION"):
                    envtool.main()
            self.assertEqual(list(Path(d).glob("*")), [])

    def test_deterministic_binary_only_pins(self):
        self.assertIn("faster-whisper==1.2.1", envtool.PINNED_DEPENDENCIES)
        self.assertIn("ctranslate2==4.8.2", envtool.PINNED_DEPENDENCIES)
        self.assertIn("av==18.0.0", envtool.PINNED_DEPENDENCIES)
        self.assertIn("numpy==2.2.6", envtool.PINNED_DEPENDENCIES)
        self.assertEqual(len(set(envtool.PINNED_DEPENDENCIES)),
                         len(envtool.PINNED_DEPENDENCIES))

    def test_existing_interpreter_is_selected_without_bootstrap(self):
        with tempfile.TemporaryDirectory() as d:
            site = Path(d) / "venv/bin/python"
            site.parent.mkdir(parents=True)
            site.write_text("placeholder")
            with patch.object(envtool, "candidate_python_paths", return_value=[str(site)]):
                with patch.object(envtool, "probe_python",
                                  return_value={"status": "PASS", "python": str(site)}):
                    with patch.object(envtool, "bootstrap_private_venv") as bootstrap:
                        selected = envtool.ensure_python(Path(d), {})
            self.assertEqual(selected, str(site))
            bootstrap.assert_not_called()

    def test_missing_interpreters_bootstrap_only_private_codespace_venv(self):
        with tempfile.TemporaryDirectory() as d:
            def run_bootstrap(root):
                expected = Path(d) / "owner-voice-acoustic-execution" / ".asr-venv"
                self.assertEqual(root.resolve(), expected.resolve())
                return str(expected / "bin/python")
            with patch.object(envtool, "candidate_python_paths", return_value=[]):
                with patch.object(envtool, "bootstrap_private_venv",
                                  side_effect=run_bootstrap) as boot:
                    selected = envtool.ensure_python(Path(d), {})
            self.assertIn(".asr-venv/bin/python", selected)
            boot.assert_called_once()

    def test_missing_binary_wheel_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / ".asr-venv"
            with patch.object(envtool, "select_base_python", return_value="python3.12"):
                def fake_run(args, **kwargs):
                    if args[1:3] == ["-m", "venv"]:
                        (root / "bin").mkdir(parents=True)
                        (root / "bin/python").write_text("fake")
                        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
                    if "pip" in args:
                        self.assertIn("--only-binary=:all:", args)
                        return subprocess.CompletedProcess(args, 1, stdout="",
                                                           stderr="no matching distribution")
                    raise AssertionError(repr(args))
                with patch.object(envtool.subprocess, "run", side_effect=fake_run):
                    with self.assertRaisesRegex(envtool.EnvironmentBlocked, "WHEEL"):
                        envtool.bootstrap_private_venv(root)
            self.assertTrue((root / "bin/python").exists())

    def test_diagnose_missing_module_without_raw_traceback(self):
        with patch.object(envtool.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["python"], 3, stdout="MISSING:faster_whisper", stderr="SECRET")):
            result = envtool.probe_python("python")
        self.assertEqual(result["status"], "MISSING:faster_whisper")
        self.assertNotIn("SECRET", str(result))


if __name__ == "__main__":
    unittest.main()
