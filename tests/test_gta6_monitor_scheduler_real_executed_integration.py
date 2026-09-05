import time

from app.services.gta6_monitor_apscheduler_adapter import (
    APSchedulerGTA6MonitorAdapter,
)
from app.services.gta6_monitor_execution_result import (
    GTA6MonitorExecutionResult,
)
from app.services.gta6_monitor_run_service import (
    GTA6MonitorRunResult,
)
from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)
from app.services.gta6_scheduler_observability import (
    GTA6SchedulerObservability,
)


def test_real_scheduler_propagates_monitor_execution_identity_on_success(
    monkeypatch,
):
    started_run = {"id": 42}
    captured_result = {}
    observed_records = []

    def fake_start_gta6_monitor_run(*, url):
        return started_run

    expected_result = GTA6MonitorRunResult(
        url="https://example.com/newswire",
        status_code=200,
        change=object(),
        baseline=True,
        items_found=0,
        items_ingested=0,
        items_duplicated=0,
        knowledge_ids=[],
    )

    def fake_run_gta6_monitor_once(*, timeout=15.0):
        return expected_result

    monkeypatch.setattr(
        "app.services.gta6_monitor_run_service.start_gta6_monitor_run",
        fake_start_gta6_monitor_run,
    )

    monkeypatch.setattr(
        "app.services.gta6_monitor_run_service.run_gta6_monitor_once",
        fake_run_gta6_monitor_once,
    )

    observability = GTA6SchedulerObservability()

    def capturing_listener(event):
        record = observability.handle_event(event)

        if record is not None:
            observed_records.append(record)

    def executor():
        result = fake_run_gta6_monitor_once()

        execution_result = GTA6MonitorExecutionResult(
            context=__import__(
                "app.services.gta6_monitor_execution_context",
                fromlist=["GTA6MonitorExecutionContext"],
            ).GTA6MonitorExecutionContext.create(
                job_id="gta6-monitor",
                run_id=started_run["id"],
            ),
            result=result,
        )

        captured_result["result"] = execution_result

        return execution_result

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
                record.event_type == "EXECUTED"
                for record in observed_records
            ):
                break

            time.sleep(0.05)

        result = captured_result.get("result")

        assert result is not None
        assert isinstance(
            result,
            GTA6MonitorExecutionResult,
        )

        executed_records = [
            record
            for record in observed_records
            if record.event_type == "EXECUTED"
        ]

        assert len(executed_records) == 1

        record = executed_records[0]

        assert record.run_id == result.run_id
        assert record.execution_id == result.execution_id

        assert record.run_id == 42
        assert record.execution_id

        assert record.job_id == "gta6-monitor-integration"

    finally:
        adapter.stop()
