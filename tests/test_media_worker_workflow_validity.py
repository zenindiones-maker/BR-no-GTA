"""Parse the historically invalid media-worker YAML before accepting it.

The hosted GitHub Actions Ubuntu runner includes Ruby/Psych. A lightweight
static contract also runs on hosts without Ruby.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / ".github/workflows/media-worker.yml"


def test_media_worker_no_misnested_step_fields():
    content = MEDIA.read_text(encoding="utf-8")
    assert content.count("      - name: ") >= 10
    for line in content.splitlines():
        assert not line.startswith(("          id:", "          if:", "          shell:"))


@pytest.mark.skipif(shutil.which("ruby") is None, reason="Ruby YAML parser unavailable")
def test_media_worker_real_yaml_parse():
    result = subprocess.run(
        ["ruby", "-e", "require 'yaml'; YAML.load_file(ARGV.fetch(0))", str(MEDIA)],
        capture_output=True, text=True, timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
