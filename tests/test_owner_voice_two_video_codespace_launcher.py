"""Safety regression contracts for the existing Codespace-only acoustic launcher."""
import os
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "owner_voice_two_video_codespace_run.py"


class CodespaceLauncherContracts(unittest.TestCase):
    def test_python_syntax(self):
        result = subprocess.run([sys.executable, "-m", "py_compile", str(LAUNCHER)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_non_codespace_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"PATH": os.environ["PATH"], "HOME": directory,
                   "CODESPACES": "false", "CODESPACE_NAME": ""}
            result = subprocess.run([sys.executable, str(LAUNCHER)],
                                    cwd=directory, env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("AUTHORIZATION", result.stderr)
            self.assertFalse((Path(directory) / ".local").exists())

    def test_rejects_other_codespace(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"PATH": os.environ["PATH"], "HOME": directory,
                   "CODESPACES": "true", "CODESPACE_NAME": "other-codespace"}
            result = subprocess.run([sys.executable, str(LAUNCHER)],
                                    cwd=directory, env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("AUTHORIZATION", result.stderr)
            self.assertFalse((Path(directory) / ".local").exists())

    def test_private_codespace_venv_selected_when_ready(self):
        import importlib.util
        from unittest.mock import patch
        target = ROOT / "scripts" / "owner_voice_two_video_codespace_run.py"
        spec = importlib.util.spec_from_file_location("codespace_runner", target)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        expected = str(Path.home() /
                       ".local/share/br-no-gta/owner-voice-acoustic-execution/.asr-venv/bin/python")
        def inspect(args, **_kwargs):
            result = 0 if args[0] == expected else 1
            return subprocess.CompletedProcess(args, result)
        with patch.object(runner.subprocess, "run", side_effect=inspect):
            self.assertEqual(runner.find_existing_python(
                ROOT, {"BR_OWNER_PYTHON": ""}), expected)

    def test_no_download_public_artifacts_or_runtime_activation(self):
        content = LAUNCHER.read_text()
        for forbidden in (
            "yt-dlp", "youtube-dl", "upload-artifact", "gh codespace create",
            "pip install", "docker run", "BR_OWNER_VOICE_ACTIVATE",
        ):
            self.assertNotIn(forbidden, content)
        self.assertIn("hashlib.sha256", content)
        self.assertIn("fcntl.flock", content)
        self.assertIn('"show"', content)
        self.assertIn("owner_voice_two_video_acoustic_probe.py", content)


if __name__ == "__main__":
    unittest.main()
