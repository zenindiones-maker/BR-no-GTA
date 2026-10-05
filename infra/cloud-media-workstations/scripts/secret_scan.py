#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "TAILSCALE_AUTH_KEY": re.compile(r"tskey" r"-auth-[A-Za-z0-9_-]+"),
    "AWS_ACCESS_KEY": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
EXCLUDED_DIRS = {".git", ".terraform", ".pytest_cache", "__pycache__"}
EXCLUDED_FILES = {"test_security_operability.py", "secret_scan.py"}

hits: list[tuple[str, str]] = []
for path in ROOT.rglob("*"):
    if not path.is_file():
        continue
    if any(part in EXCLUDED_DIRS for part in path.parts):
        continue
    if path.name in EXCLUDED_FILES:
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    for name, pattern in PATTERNS.items():
        if pattern.search(text):
            hits.append((name, str(path.relative_to(ROOT))))

if hits:
    for name, path in hits:
        print(f"SECRET_SCAN_HIT={name}:{path}")
    print("SECRET_SCAN=FAIL")
    raise SystemExit(1)

print("SECRET_SCAN=PASS")
