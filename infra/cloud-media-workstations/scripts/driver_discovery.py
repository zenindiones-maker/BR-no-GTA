#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import boto3


REGION = "sa-east-1"
BUCKET = "ec2-linux-nvidia-drivers"
VERSION_RE = re.compile(r"(?:GRID[-_/ ]?|grid[-_/ ]?)(\d{2})[._-](\d+)", re.I)


class DriverDiscoveryBlocked(RuntimeError):
    pass


def _version_from_key(key: str) -> tuple[int, int] | None:
    match = VERSION_RE.search(key)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def choose_compatible_grid_driver(
    *,
    objects: list[dict[str, Any]],
    min_version: tuple[int, int],
    max_version: tuple[int, int],
) -> dict[str, Any]:
    candidates: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for obj in objects:
        key = str(obj.get("Key") or "")
        if not key.endswith(".run"):
            continue
        version = _version_from_key(key)
        if version is None:
            continue
        if min_version <= version <= max_version:
            candidates.append((version, obj))
    if not candidates:
        raise DriverDiscoveryBlocked("BLOCKED_DRIVER:NO_PROVABLE_COMPATIBLE_GRID_OBJECT")
    candidates.sort(key=lambda item: (item[0], str(item[1].get("Key"))))
    version, selected = candidates[-1]
    return {
        **selected,
        "grid_version": f"{version[0]}.{version[1]}",
    }


def list_all_objects(s3) -> list[dict[str, Any]]:
    paginator = s3.get_paginator("list_objects_v2")
    rows: list[dict[str, Any]] = []
    for page in paginator.paginate(Bucket=BUCKET):
        rows.extend(page.get("Contents", []))
    return rows


def materialize_and_hash(s3, key: str) -> tuple[str, int]:
    with tempfile.NamedTemporaryFile(prefix="aws-grid-", suffix=".run") as fh:
        s3.download_fileobj(BUCKET, key, fh)
        fh.flush()
        path = Path(fh.name)
        h = hashlib.sha256()
        size = 0
        with path.open("rb") as src:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                size += len(chunk)
                h.update(chunk)
        return h.hexdigest(), size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", choices=["hazewave", "br-no-gta"])
    args = parser.parse_args()

    limits = {
        "hazewave": ((18, 4), (19, 5)),
        "br-no-gta": ((17, 1), (19, 5)),
    }
    min_version, max_version = limits[args.project]

    try:
        session = boto3.Session(region_name=REGION)
        sts = session.client("sts", region_name=REGION)
        sts.get_caller_identity()
        s3 = session.client("s3", region_name=REGION)
        objects = list_all_objects(s3)
        selected = choose_compatible_grid_driver(
            objects=objects,
            min_version=min_version,
            max_version=max_version,
        )
        digest, bytes_size = materialize_and_hash(s3, selected["Key"])
    except Exception as exc:
        status = (
            str(exc).split(":", 1)[0]
            if isinstance(exc, DriverDiscoveryBlocked)
            else "BLOCKED_AWS_AUTH_OR_DRIVER_DISCOVERY"
        )
        print(json.dumps({
            "schema": "NvidiaDriverEvidence/v1",
            "project": args.project,
            "status": status,
            "detail": str(exc) if isinstance(exc, DriverDiscoveryBlocked) else type(exc).__name__,
        }, sort_keys=True))
        return 2

    receipt = {
        "schema": "NvidiaDriverEvidence/v1",
        "project": args.project,
        "status": "PASS",
        "driver_family": "GRID",
        "grid_version": selected["grid_version"],
        "s3_uri": f"s3://{BUCKET}/{selected['Key']}",
        "sha256": digest,
        "bytes": bytes_size,
        "compatibility_range": {
            "min": f"{min_version[0]}.{min_version[1]}",
            "max": f"{max_version[0]}.{max_version[1]}",
        },
    }
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
