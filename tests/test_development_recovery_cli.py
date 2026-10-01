from __future__ import annotations

import subprocess
import sys


def test_development_checkpoint_cli_exposes_required_authorization():
    cp=subprocess.run([sys.executable,"scripts/development_checkpoint.py","--help"],text=True,capture_output=True)
    assert cp.returncode==0
    assert "--authorization-id" in cp.stdout
    assert "--ledger" in cp.stdout
    assert "--request" in cp.stdout


def test_development_resume_cli_is_read_only_interface():
    cp=subprocess.run([sys.executable,"scripts/development_resume.py","--help"],text=True,capture_output=True)
    assert cp.returncode==0
    assert "--recovery-ref" in cp.stdout
    assert "--authorization-id" not in cp.stdout
