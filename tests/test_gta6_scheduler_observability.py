from datetime import datetime, timezone

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
    JobSubmissionEvent,
)

from app.services.gta6_scheduler_observability import (
    GTA6SchedulerObservability,
    create_scheduler_event_listener,
)


SCHEDULED_RUN_TIME = datetime(
    2026,
    9,
    3,
    20,
    0,
    tzinfo=timezone.utc,
)

JOBSTORE = "default"


def make_execution_event(
    code: int,
    *,
    exception=None,
    traceback_text=None,
):
    return JobExecutionEvent(
        code,
        job_id="gta6-monitor",
        jobstore=JOBSTORE,
        scheduled_run_time=SCHEDULED_RUN_TIME,
        exception=exception,
        traceback=traceback_text,
        retval=None,
    )


def make_submission_event(
    code: int,
    *,
    scheduled_run_times=None,
):
    if scheduled_run_times is None:
        scheduled_run_times = [SCHEDULED_RUN_TIME]

    return JobSubmissionEvent(
        code,
        job_id="gta6-monitor",
        jobstore=JOBSTORE,
        scheduled_run_times=scheduled_run_times,
    )


def test_executed_event_is_recorded():
    observability = GTA6SchedulerObservability()

    event = make_execution_event(EVENT_JOB_EXECUTED)

    record = observability.handle_event(event)

    assert record is not None
    assert record.job_id == "gta6-monitor"
    assert record.event_type == "EXECUTED"
    assert record.scheduled_run_time == SCHEDULED_RUN_TIME
    assert record.exception is None


def test_error_event_preserves_exception_and_traceback():
    observability = GTA6SchedulerObservability()

    error = RuntimeError("Newswire unavailable")

    event = make_execution_event(
        EVENT_JOB_ERROR,
        exception=error,
        traceback_text="Traceback (most recent call last): ...",
    )

    record = observability.handle_event(event)

    assert record is not None
    assert record.event_type == "ERROR"
    assert record.exception == "RuntimeError: Newswire unavailable"
    assert record.traceback_text == (
        "Traceback (most recent call last): ..."
    )


def test_missed_event_is_recorded():
    observability = GTA6SchedulerObservability()

    event = make_execution_event(EVENT_JOB_MISSED)

    record = observability.handle_event(event)

    assert record is not None
    assert record.job_id == "gta6-monitor"
    assert record.event_type == "MISSED"
    assert record.scheduled_run_time == SCHEDULED_RUN_TIME


def test_max_instances_event_is_recorded_as_submission_event():
    observability = GTA6SchedulerObservability()

    event = make_submission_event(EVENT_JOB_MAX_INSTANCES)

    record = observability.handle_event(event)

    assert record is not None
    assert record.job_id == "gta6-monitor"
    assert record.event_type == "MAX_INSTANCES"
    assert record.scheduled_run_times == (SCHEDULED_RUN_TIME,)


def test_max_instances_preserves_multiple_scheduled_runs():
    observability = GTA6SchedulerObservability()

    second_run = datetime(
        2026,
        9,
        3,
        20,
        5,
        tzinfo=timezone.utc,
    )

    event = make_submission_event(
        EVENT_JOB_MAX_INSTANCES,
        scheduled_run_times=[
            SCHEDULED_RUN_TIME,
            second_run,
        ],
    )

    record = observability.handle_event(event)

    assert record is not None
    assert record.event_type == "MAX_INSTANCES"
    assert record.scheduled_run_times == (
        SCHEDULED_RUN_TIME,
        second_run,
    )


def test_unknown_event_is_ignored():
    observability = GTA6SchedulerObservability()

    event = make_execution_event(999999)

    record = observability.handle_event(event)

    assert record is None


def test_listener_can_receive_execution_event():
    observability = GTA6SchedulerObservability()

    listener = create_scheduler_event_listener(observability)

    event = make_execution_event(EVENT_JOB_EXECUTED)

    result = listener(event)

    assert result is None


def test_listener_can_receive_max_instances_event():
    observability = GTA6SchedulerObservability()

    listener = create_scheduler_event_listener(observability)

    event = make_submission_event(EVENT_JOB_MAX_INSTANCES)

    result = listener(event)

    assert result is None
