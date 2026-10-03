"""Install only the locked security dependencies, then execute the real policy suite.

Kept outside the child suite so no recursion guard or skipped child tests can
mask missing dependencies. Run on the policy job's Python 3.12 / Ubuntu 24.04.
"""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
POLICY_TESTS = (
    "tests/test_security_guardian_foundation_v1.py",
    "tests/test_gta6_change_detector.py",
)


def test_clean_security_ci_dependency_closure(tmp_path):
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONNOUSERSITE": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }

    def run(*args):
        result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True,
                                text=True, timeout=240)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    venv = tmp_path / "clean-security-ci"
    run(sys.executable, "-I", "-m", "venv", str(venv))
    python = str(venv / "bin/python")
    assert "include-system-site-packages = false" in (venv / "pyvenv.cfg").read_text()
    run(python, "-I", "-m", "pip", "--isolated", "install", "--require-hashes",
        "--only-binary", ":all:", "-r", str(ROOT / "requirements/security-ci.lock"))
    run(python, "-I", "-m", "pip", "--isolated", "check")
    collected = run(python, "-I", "-m", "pytest", "--collect-only", "-q", *POLICY_TESTS)
    assert all(Path(path).name in collected for path in POLICY_TESTS)
    executed = run(python, "-I", "-m", "pytest", "-q", *POLICY_TESTS)
    assert "passed" in executed
    assert "skipped" not in executed
