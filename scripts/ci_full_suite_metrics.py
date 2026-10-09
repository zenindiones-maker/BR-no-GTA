"""Deterministic pytest summary parser for CI telemetry.

Never invent a zero-failure outcome from an unrecognized pytest summary.
JUnit XML remains authoritative for failure/error counts in CI.
"""
from __future__ import annotations

import re


def parse_pytest_summary(log: str) -> dict[str, int | float] | None:
    """Parse success- and failure-first pytest summaries, regardless of order."""
    for line in reversed(log.splitlines()):
        elapsed = re.search(r"\bin (\d+(?:\.\d+)?)s\b", line)
        if not elapsed:
            continue
        values = {
            name: int(value)
            for value, name in re.findall(
                r"(\d+)\s+(subtests passed|passed|failed|skipped|errors)\b",
                line,
            )
        }
        if not any(name in values for name in ("passed", "failed", "errors")):
            continue
        return {
            "passed": values.get("passed", 0),
            "failed": values.get("failed", 0),
            "skipped": values.get("skipped", 0),
            "errors": values.get("errors", 0),
            "subtests_passed": values.get("subtests passed", 0),
            "pytest_wall_clock_seconds": float(elapsed.group(1)),
        }
    return None
