#!/usr/bin/env python3
"""Produce local, evidence-backed media measurements for the BR-no-GTA harness."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.services.reverse_engineering_media_service import (
    ObservationError,
    analyze_reference,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only BR-no-GTA reference observation")
    parser.add_argument("--input", required=True, help="Local authorized video/audio file")
    parser.add_argument("--rights", required=True, choices=["owned", "licensed", "observation_only"])
    parser.add_argument("--transcript", help="Optional locally available TXT/SRT script")
    parser.add_argument("--detect-scenes", action="store_true", help="Opt-in full-video cut detection")
    parser.add_argument("--output", required=True, help="New JSON evidence receipt path")
    args = parser.parse_args(argv)

    result_path = Path(args.output).expanduser()
    if result_path.is_symlink() or result_path.exists():
        print("REFUSE_TO_OVERWRITE_EVIDENCE", file=sys.stderr)
        return 3
    if not result_path.parent.is_dir():
        print("EVIDENCE_PARENT_NOT_FOUND", file=sys.stderr)
        return 3
    source = Path(args.input).expanduser()
    if result_path.resolve() == source.resolve():
        print("EVIDENCE_OVERLAPS_REFERENCE", file=sys.stderr)
        return 3
    try:
        evidence = analyze_reference(
            source, rights=args.rights, transcript=args.transcript,
            scene_detection=args.detect_scenes,
        )
    except ObservationError as exc:
        print(f"OBSERVATION_BLOCKED={exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(evidence, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(str(result_path), flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
    except FileExistsError:
        print("REFUSE_TO_OVERWRITE_EVIDENCE", file=sys.stderr)
        return 3
    print(f"OBSERVATION_EVIDENCE_SHA256={evidence['evidence_sha256']}")
    print(f"OBSERVATION_MEDIA_SHA256={evidence['source']['sha256']}")
    print("OBSERVATION_STATUS=MEASURED_REFERENCE_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
