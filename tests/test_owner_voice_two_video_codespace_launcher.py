"""Safety regression contracts for the existing Codespace-only acoustic launcher."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "owner_voice_two_video_codespace_run.sh"


class CodespaceLauncherContracts(unittest.TestCase):
    def test_bash_syntax(self):
        result = subprocess.run(["bash", "-n", str(LAUNCHER)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_non_codespace_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"PATH": os.environ["PATH"], "HOME": directory,
                   "CODESPACES": "false", "CODESPACE_NAME": ""}
            result = subprocess.run(["bash", str(LAUNCHER)],
                                    cwd=directory, env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("AUTHORIZATION", result.stderr)
            self.assertFalse((Path(directory) / ".local").exists())

    def test_rejects_other_codespace(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"PATH": os.environ["PATH"], "HOME": directory,
                   "CODESPACES": "true", "CODESPACE_NAME": "other-codespace"}
            result = subprocess.run(["bash", str(LAUNCHER)],
                                    cwd=directory, env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("AUTHORIZATION", result.stderr)
            self.assertFalse((Path(directory) / ".local").exists())

    def test_no_download_public_artifacts_or_runtime_activation(self):
        content = LAUNCHER.read_text()
        for forbidden in (
            "yt-dlp", "youtube-dl", "upload-artifact", "gh codespace create",
            "pip install", "docker run", "BR_OWNER_VOICE_ACTIVATE",
        ):
            self.assertNotIn(forbidden, content)
        self.assertIn("sha256sum", content)
        self.assertIn("flock", content)
        self.assertIn("git show", content)
        self.assertIn("owner_voice_two_video_acoustic_probe.py", content)


if __name__ == "__main__":
    unittest.main()
