import time
from datetime import datetime, timedelta, timezone

from app.services.gta6_monitor_apscheduler_adapter import (
    APSchedulerGTA6MonitorAdapter,
)
from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)
from app.services.gta6_scheduler_observability import (
    GTA6SchedulerObservability,
)


def test_real_scheduler_missed_event_has_no_execution_identity():
    observed_records = []

    observability = GTA6SchedulerObservability()

    def capturing_listener(event):
        record = observability.handle_event(event)

        if record is not None:
            observed_records.append(record)

    def executor():
        raise AssertionError(
            "executor must not run for a MISSED event"
        )

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(
            interval_seconds=60,
            timeout=1,
            enabled=True,
            job_id="gta6-monitor",
            misfire_grace_time=1,
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
            run_date=datetime.now(timezone.utc) - timedelta(seconds=10),
            id="gta6-monitor-missed-integration",
            misfire_grace_time=1,
        )

        adapter.scheduler.start()

        deadline = time.monotonic() + 5

        while time.monotonic() < deadline:
            if any(
                record.event_type == "MISSED"
                for record in observed_records
            ):
                break

            time.sleep(0.05)

        missed_records = [
            record
            for record in observed_records
            if record.event_type == "MISSED"
        ]

        assert len(missed_records) == 1

        record = missed_records[0]

        assert record.job_id == (
            "gta6-monitor-missed-integration"
        )

        assert record.run_id is None
        assert record.execution_id is None

    finally:
        adapter.stop()
