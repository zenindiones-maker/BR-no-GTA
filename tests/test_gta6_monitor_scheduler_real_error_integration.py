import time

from app.services.gta6_monitor_apscheduler_adapter import (
    APSchedulerGTA6MonitorAdapter,
)
from app.services.gta6_monitor_execution_error import (
    GTA6MonitorExecutionError,
)
from app.services.gta6_monitor_run_service import (
    run_gta6_monitor_once,
)
from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)
from app.services.gta6_scheduler_observability import (
    GTA6SchedulerObservability,
    create_scheduler_event_listener,
)


def test_real_scheduler_propagates_monitor_execution_identity(
    monkeypatch,
):
    started_run = {"id": 42}
    captured_error = {}
    observed_records = []

    def fake_start_gta6_monitor_run(*, url):
        return started_run

    def fake_monitor(*args, **kwargs):
        raise RuntimeError("Newswire unavailable")

    def fake_fail_gta6_monitor_run(**kwargs):
        return None

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
        fake_fail_gta6_monitor_run,
    )

    observability = GTA6SchedulerObservability()

    real_listener = create_scheduler_event_listener(
        observability,
    )

    def capturing_listener(event):
        record = observability.handle_event(event)

        if record is not None:
            observed_records.append(record)

    def executor():
        try:
            return run_gta6_monitor_once()
        except GTA6MonitorExecutionError as exc:
            captured_error["error"] = exc
            raise

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(
            interval_seconds=1,
            timeout=1,
            enabled=True,
            job_id="gta6-monitor",
        ),
        executor=executor,
        observability=observability,
    )

    adapter.configure()

    try:
        adapter.scheduler.remove_all_jobs()

        adapter.scheduler.add_listener(
            capturing_listener,
        )

        adapter.scheduler.add_job(
            executor,
            trigger="date",
            id="gta6-monitor-integration",
        )

        adapter.scheduler.start()

        deadline = time.monotonic() + 5

        while time.monotonic() < deadline:
            if any(
                record.event_type == "ERROR"
                for record in observed_records
            ):
                break

            time.sleep(0.05)

        error = captured_error.get("error")

        assert error is not None
        assert isinstance(error, GTA6MonitorExecutionError)

        error_records = [
            record
            for record in observed_records
            if record.event_type == "ERROR"
        ]

        assert len(error_records) == 1

        record = error_records[0]

        assert record.run_id == error.run_id
        assert record.execution_id == error.execution_id

        assert record.run_id == 42
        assert record.execution_id

        assert record.job_id == "gta6-monitor-integration"

    finally:
        adapter.stop()
