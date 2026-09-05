from datetime import datetime, timezone

from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent

from app.services.gta6_monitor_execution_context import (
    GTA6MonitorExecutionContext,
)
from app.services.gta6_monitor_execution_error import (
    GTA6MonitorExecutionError,
)
from app.services.gta6_scheduler_observability import (
    GTA6SchedulerObservability,
)


def test_error_event_correlates_execution_identity_from_exception():
    context = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )

    cause = RuntimeError("boom")

    execution_error = GTA6MonitorExecutionError(
        context=context,
        cause=cause,
    )

    scheduled_run_time = datetime(
        2026,
        9,
        4,
        18,
        0,
        tzinfo=timezone.utc,
    )

    traceback_text = "Traceback: boom"

    event = JobExecutionEvent(
        EVENT_JOB_ERROR,
        "gta6-monitor",
        "default",
        scheduled_run_time,
        exception=execution_error,
        traceback=traceback_text,
    )

    observability = GTA6SchedulerObservability()

    record = observability.handle_event(event)

    assert record is not None
    assert record.event_type == "ERROR"
    assert record.job_id == "gta6-monitor"
    assert record.run_id == 42
    assert record.execution_id == context.execution_id
    assert record.scheduled_run_time == scheduled_run_time
    assert record.exception == "GTA6MonitorExecutionError: boom"
    assert record.traceback_text == traceback_text
