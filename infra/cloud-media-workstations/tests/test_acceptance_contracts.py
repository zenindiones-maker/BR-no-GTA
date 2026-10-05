from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from driver_discovery import (
    DriverDiscoveryBlocked,
    choose_compatible_grid_driver,
)


def test_g6f_rejects_grid_older_than_18_4() -> None:
    objects = [
        {"Key": "GRID-18.3/NVIDIA-Linux-x86_64.run", "Size": 10},
        {"Key": "GRID-18.4/NVIDIA-Linux-x86_64.run", "Size": 11},
        {"Key": "GRID-19.5/NVIDIA-Linux-x86_64.run", "Size": 12},
    ]
    selected = choose_compatible_grid_driver(
        objects=objects,
        min_version=(18, 4),
        max_version=(19, 5),
    )
    assert selected["Key"].startswith("GRID-19.5/")


def test_driver_discovery_fails_closed_when_version_cannot_be_proven() -> None:
    with pytest.raises(DriverDiscoveryBlocked, match="BLOCKED_DRIVER"):
        choose_compatible_grid_driver(
            objects=[{"Key": "latest/NVIDIA-Linux-x86_64.run", "Size": 1}],
            min_version=(18, 4),
            max_version=(19, 5),
        )


def test_acceptance_runner_contains_human_checkpoint_and_final_stop() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "acceptance.sh").read_text(encoding="utf-8")
    assert "HUMAN_MOONLIGHT_REAPER_CHECKPOINT_REQUIRED" in text
    assert "cross_isolation_probe.py" in text
    assert "workstation-gpu-proof" in text
    assert "reaper-render" in text
    assert "PERSISTENCE_AFTER_RESTART=PASS" in text
    assert "FINAL_STATE=STOPPED" in text
    assert "trap stop_both EXIT INT TERM" in text
