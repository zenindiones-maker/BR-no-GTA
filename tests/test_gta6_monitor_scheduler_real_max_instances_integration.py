import threading
import time

from app.services.gta6_monitor_apscheduler_adapter import (
    APSchedulerGTA6MonitorAdapter,
)
from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)
from app.services.gta6_scheduler_observability import (
    GTA6SchedulerObservability,
)


def test_real_scheduler_max_instances_event_has_no_execution_identity():
    observed_records = []
    execution_started = threading.Event()
    release_execution = threading.Event()

    execution_count = {"value": 0}

    observability = GTA6SchedulerObservability()

    def capturing_listener(event):
        record = observability.handle_event(event)

        if record is not None:
            observed_records.append(record)

    def executor():
        execution_count["value"] += 1
        execution_started.set()

        if not release_execution.wait(timeout=5):
            raise AssertionError(
                "first execution was not released"
            )

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(
            interval_seconds=60,
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
            trigger="interval",
            seconds=0.1,
            id="gta6-monitor-max-instances-integration",
            max_instances=1,
            coalesce=False,
        )

        adapter.scheduler.start()

        assert execution_started.wait(timeout=5)

        deadline = time.monotonic() + 5

        while time.monotonic() < deadline:
            if any(
                record.event_type == "MAX_INSTANCES"
                for record in observed_records
            ):
                break

            time.sleep(0.05)

        max_instance_records = [
            record
            for record in observed_records
            if record.event_type == "MAX_INSTANCES"
        ]

        assert len(max_instance_records) >= 1

        record = max_instance_records[0]

        assert record.job_id == (
            "gta6-monitor-max-instances-integration"
        )

        assert record.run_id is None
        assert record.execution_id is None

        assert execution_count["value"] == 1

    finally:
        release_execution.set()
        adapter.stop()
