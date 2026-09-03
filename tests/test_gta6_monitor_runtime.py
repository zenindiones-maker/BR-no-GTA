from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.services.gta6_monitor_runtime import (
    GTA6MonitorRuntime,
)


def test_runtime_requires_scheduler():
    with pytest.raises(ValueError, match="scheduler must be provided"):
        GTA6MonitorRuntime(scheduler=None)


def test_runtime_accepts_scheduler():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    assert runtime.scheduler is scheduler


def test_start_configures_and_starts_scheduler():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    runtime.start()

    scheduler.configure.assert_called_once_with()
    scheduler.start.assert_called_once_with()


def test_stop_stops_scheduler():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    runtime.stop()

    scheduler.stop.assert_called_once_with()


def test_run_forever_starts_runtime_and_waits_until_stopped():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    calls = []

    def fake_wait():
        calls.append("wait")

    runtime._wait_forever = fake_wait

    runtime.run_forever()

    scheduler.configure.assert_called_once_with()
    scheduler.start.assert_called_once_with()
    assert calls == ["wait"]


def test_run_forever_stops_scheduler_when_wait_finishes():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    runtime._wait_forever = Mock()

    runtime.run_forever()

    scheduler.stop.assert_called_once_with()


def test_run_forever_stops_scheduler_when_wait_raises():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    error = RuntimeError("runtime failure")
    runtime._wait_forever = Mock(side_effect=error)

    with pytest.raises(RuntimeError, match="runtime failure"):
        runtime.run_forever()

    scheduler.stop.assert_called_once_with()


def test_runtime_does_not_execute_monitor_directly():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    assert not hasattr(runtime, "execute_monitor")


def test_scheduler_property_is_read_only():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    assert runtime.scheduler is scheduler

    with pytest.raises(AttributeError):
        runtime.scheduler = Mock()
