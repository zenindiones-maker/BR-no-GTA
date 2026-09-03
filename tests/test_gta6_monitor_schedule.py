import pytest

from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)


def test_schedule_has_operational_defaults():
    schedule = GTA6MonitorSchedule()

    assert schedule.interval_seconds == 300.0
    assert schedule.timeout == 15.0
    assert schedule.enabled is True
    assert schedule.job_id == "gta6-monitor"


def test_schedule_accepts_custom_configuration():
    schedule = GTA6MonitorSchedule(
        interval_seconds=60,
        timeout=10,
        enabled=False,
        job_id="gta6-monitor-production",
    )

    assert schedule.interval_seconds == 60
    assert schedule.timeout == 10
    assert schedule.enabled is False
    assert schedule.job_id == "gta6-monitor-production"


def test_schedule_is_immutable():
    schedule = GTA6MonitorSchedule()

    with pytest.raises(AttributeError):
        schedule.interval_seconds = 60


@pytest.mark.parametrize(
    "value",
    [0, -1, -0.1, None, "300", True, False],
)
def test_schedule_rejects_invalid_interval(value):
    with pytest.raises(ValueError, match="interval_seconds"):
        GTA6MonitorSchedule(interval_seconds=value)


@pytest.mark.parametrize(
    "value",
    [0, -1, -0.1, None, "15", True, False],
)
def test_schedule_rejects_invalid_timeout(value):
    with pytest.raises(ValueError, match="timeout"):
        GTA6MonitorSchedule(timeout=value)


@pytest.mark.parametrize(
    "value",
    [None, 1, 0, "true", "false"],
)
def test_schedule_rejects_invalid_enabled(value):
    with pytest.raises(ValueError, match="enabled"):
        GTA6MonitorSchedule(enabled=value)


@pytest.mark.parametrize(
    "value",
    ["", "   ", None, 123, True],
)
def test_schedule_rejects_invalid_job_id(value):
    with pytest.raises(ValueError, match="job_id"):
        GTA6MonitorSchedule(job_id=value)
