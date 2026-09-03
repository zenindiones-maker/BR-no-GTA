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

    runtime.start()
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


def test_start_cannot_be_called_twice_without_stop():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    runtime.start()
    runtime.start()

    assert scheduler.configure.call_count == 1
    assert scheduler.start.call_count == 1


def test_stop_after_start_is_forwarded_once():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    runtime.start()
    runtime.stop()

    scheduler.stop.assert_called_once_with()


def test_runtime_can_start_again_after_stop():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    runtime.start()
    runtime.stop()
    runtime.start()

    assert scheduler.configure.call_count == 2
    assert scheduler.start.call_count == 2


def test_stop_before_start_is_idempotent():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    runtime.stop()

    scheduler.start.assert_not_called()
    scheduler.stop.assert_not_called()
    assert runtime.running is False


def test_runtime_running_state_changes_with_lifecycle():
    scheduler = Mock()

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    assert runtime.running is False

    runtime.start()

    assert runtime.running is True

    runtime.stop()

    assert runtime.running is False


def test_start_failure_does_not_mark_runtime_as_running():
    scheduler = Mock()
    scheduler.start.side_effect = RuntimeError("scheduler start failed")

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    with pytest.raises(RuntimeError, match="scheduler start failed"):
        runtime.start()

    assert runtime.running is False


def test_configure_failure_does_not_mark_runtime_as_running():
    scheduler = Mock()
    scheduler.configure.side_effect = RuntimeError("configuration failed")

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    with pytest.raises(RuntimeError, match="configuration failed"):
        runtime.start()

    assert runtime.running is False
    scheduler.start.assert_not_called()


def test_start_failure_does_not_allow_stop_to_stop_scheduler():
    scheduler = Mock()
    scheduler.start.side_effect = RuntimeError("scheduler start failed")

    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    with pytest.raises(RuntimeError, match="scheduler start failed"):
        runtime.start()

    runtime.stop()

    scheduler.stop.assert_not_called()
    assert runtime.running is False


def test_install_signal_handlers_registers_sigint_and_sigterm(monkeypatch):
    scheduler = Mock()
    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    registered = {}

    def fake_signal(signum, handler):
        registered[signum] = handler
        return f"previous-{signum}"

    monkeypatch.setattr(
        "signal.signal",
        fake_signal,
    )

    runtime.install_signal_handlers()

    import signal

    assert registered[signal.SIGINT] == runtime._handle_shutdown_signal
    assert registered[signal.SIGTERM] == runtime._handle_shutdown_signal


def test_install_signal_handlers_preserves_previous_handlers(monkeypatch):
    scheduler = Mock()
    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    previous = {}

    def fake_signal(signum, handler):
        previous[signum] = f"previous-{signum.name}"
        return previous[signum]

    monkeypatch.setattr(
        "signal.signal",
        fake_signal,
    )

    runtime.install_signal_handlers()

    import signal

    assert runtime._previous_signal_handlers == {
        signal.SIGINT: "previous-SIGINT",
        signal.SIGTERM: "previous-SIGTERM",
    }


def test_shutdown_signal_requests_runtime_stop(monkeypatch):
    scheduler = Mock()
    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    runtime.start()

    runtime._handle_shutdown_signal(
        2,
        None,
    )

    scheduler.stop.assert_called_once_with()
    assert runtime.running is False


def test_shutdown_signal_is_safe_when_runtime_is_already_stopped():
    scheduler = Mock()
    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    runtime._handle_shutdown_signal(
        2,
        None,
    )

    scheduler.stop.assert_not_called()
    assert runtime.running is False


def test_restore_signal_handlers_restores_previous_handlers(monkeypatch):
    scheduler = Mock()
    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    calls = []

    def fake_signal(signum, handler):
        calls.append((signum, handler))
        return None

    monkeypatch.setattr(
        "signal.signal",
        fake_signal,
    )

    import signal

    runtime._previous_signal_handlers = {
        signal.SIGINT: "old-int",
        signal.SIGTERM: "old-term",
    }
    runtime._signals_installed = True

    runtime.restore_signal_handlers()

    assert calls == [
        (signal.SIGINT, "old-int"),
        (signal.SIGTERM, "old-term"),
    ]


def test_restore_signal_handlers_is_idempotent(monkeypatch):
    scheduler = Mock()
    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    calls = []

    monkeypatch.setattr(
        "signal.signal",
        lambda signum, handler: calls.append(
            (signum, handler)
        ),
    )

    runtime.restore_signal_handlers()
    runtime.restore_signal_handlers()

    assert calls == []


def test_unrelated_signal_is_not_registered(monkeypatch):
    scheduler = Mock()
    runtime = GTA6MonitorRuntime(
        scheduler=scheduler,
    )

    registered = []

    monkeypatch.setattr(
        "signal.signal",
        lambda signum, handler: registered.append(
            signum
        ),
    )

    runtime.install_signal_handlers()

    import signal

    assert signal.SIGUSR1 not in registered
