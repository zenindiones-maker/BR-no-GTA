from datetime import datetime, timezone

from apscheduler.events import EVENT_JOB_EXECUTED, JobExecutionEvent

from app.services.gta6_monitor_execution_context import (
    GTA6MonitorExecutionContext,
)
from app.services.gta6_monitor_execution_result import (
    GTA6MonitorExecutionResult,
)
from app.services.gta6_scheduler_observability import (
    GTA6SchedulerObservability,
)


def test_executed_event_correlates_execution_identity_from_result():
    context = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )
    execution_result = GTA6MonitorExecutionResult(
        context=context,
        result={"status": "ok"},
    )

    scheduled_run_time = datetime(
        2026,
        9,
        4,
        18,
        0,
        tzinfo=timezone.utc,
    )

    event = JobExecutionEvent(
        EVENT_JOB_EXECUTED,
        "gta6-monitor",
        "default",
        scheduled_run_time,
        retval=execution_result,
    )

    observability = GTA6SchedulerObservability()

    record = observability.handle_event(event)

    assert record is not None
    assert record.event_type == "EXECUTED"
    assert record.job_id == "gta6-monitor"
    assert record.run_id == 42
    assert record.execution_id == context.execution_id
    assert record.scheduled_run_time == scheduled_run_time
