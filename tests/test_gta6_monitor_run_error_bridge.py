import pytest

from app.services.gta6_monitor_execution_error import (
    GTA6MonitorExecutionError,
)
from app.services.gta6_monitor_run_service import (
    run_gta6_monitor_once,
)


def test_run_monitor_wraps_real_execution_error_with_identity(
    monkeypatch,
):
    def fake_start_gta6_monitor_run(*, url):
        return {"id": 42}

    def fake_monitor(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.services.gta6_monitor_run_service.start_gta6_monitor_run",
        fake_start_gta6_monitor_run,
    )
    monkeypatch.setattr(
        "app.services.gta6_monitor_run_service.GTA6ViceMonitor",
        fake_monitor,
    )
    monkeypatch.setattr(
        "app.services.gta6_monitor_run_service.fail_gta6_monitor_run",
        lambda **kwargs: None,
    )

    with pytest.raises(GTA6MonitorExecutionError) as exc_info:
        run_gta6_monitor_once()

    error = exc_info.value

    assert error.run_id == 42
    assert error.job_id == "gta6-monitor"
    assert error.execution_id
    assert isinstance(error.cause, RuntimeError)
    assert str(error.cause) == "boom"
