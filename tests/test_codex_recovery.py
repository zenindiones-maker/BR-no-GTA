import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("recovery", Path(__file__).resolve().parents[1] / ".github/scripts/codex_recovery.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def test_exports_modified_and_new_code_excludes_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)
            git("init")
            (root / "tests").mkdir()
            code = root / "tests/test_example.py"
            code.write_text("value = 1\n")
            git("add", ".")
            git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "base")
            code.write_text("value = 2\n")
            (root / "tests/test_new.py").write_text("new = True\n")
            (root / ".codex-device-auth").mkdir()
            (root / ".codex-device-auth/device.txt").write_text("DO_NOT_EXPORT")
            recovery.export(root, root / "recovery", "HEAD")
            patch = (root / "recovery/partial.patch").read_text()
            self.assertIn("value = 2", patch)
            self.assertIn("new = True", patch)
            self.assertNotIn("DO_NOT_EXPORT", patch)
            git("checkout", "--", "tests/test_example.py")
            (root / "tests/test_new.py").unlink()
            git("apply", "--check", "recovery/partial.patch")
