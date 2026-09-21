from __future__ import annotations

import re
from pathlib import Path


INSTALLER = Path("scripts/install_telegram_termux_persistence.sh")


def _unquoted_heredoc_body(source: str, marker: str) -> str:
    start = source.index(marker) + len(marker)
    end = source.index("\nEOF", start)
    return source[start:end]


def test_supervisor_template_does_not_expand_parent_positional_parameters():
    source = INSTALLER.read_text(encoding="utf-8")
    body = _unquoted_heredoc_body(source, 'cat >"${SUPERVISOR}" <<EOF')
    unsafe = re.findall(r"(?<!\\)\$[0-9]+", body)
    assert unsafe == []
    assert "awk 'NR==1 {print \\$1}'" in body


def test_installer_keeps_strict_shell_mode():
    source = INSTALLER.read_text(encoding="utf-8")
    assert source.startswith("#!/data/data/com.termux/files/usr/bin/bash\nset -euo pipefail\n")
