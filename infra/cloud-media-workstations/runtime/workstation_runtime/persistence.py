from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def create_marker(
    path: Path,
    *,
    project: str,
    reaper_version: str,
    project_sha256: str,
) -> None:
    payload = {
        "schema": "WorkstationPersistenceMarker/v1",
        "project": project,
        "reaper_version": reaper_version,
        "project_sha256": project_sha256,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def verify_marker(path: Path, *, expected: dict[str, Any]) -> bool:
    try:
        observed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return observed == expected
