from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
    JobSubmissionEvent,
)

from app.services.gta6_monitor_execution_result import (
    GTA6MonitorExecutionResult,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerEventRecord:
    job_id: str
    event_type: str
    scheduled_run_time: datetime | None = None
    scheduled_run_times: tuple[datetime, ...] = ()
    observed_at: datetime | None = None
    exception: str | None = None
    traceback_text: str | None = None
    run_id: int | None = None
    execution_id: str | None = None


class GTA6SchedulerObservability:
    """
    Interpreta os eventos relevantes do APScheduler 3.x.

    Responsabilidade:
    - traduzir eventos APScheduler para registros internos;
    - preservar informações importantes para diagnóstico;
    - registrar os acontecimentos no logger.

    Não é responsabilidade deste componente:
    - executar jobs;
    - controlar o scheduler;
    - persistir dados no banco;
    - decidir retry.
    """

    EVENT_NAMES = {
        EVENT_JOB_EXECUTED: "EXECUTED",
        EVENT_JOB_ERROR: "ERROR",
        EVENT_JOB_MISSED: "MISSED",
        EVENT_JOB_MAX_INSTANCES: "MAX_INSTANCES",
    }

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or LOGGER

    def handle_event(
        self,
        event: JobExecutionEvent | JobSubmissionEvent,
    ) -> SchedulerEventRecord | None:
        event_type = self._resolve_event_type(event.code)

        if event_type is None:
            return None

        observed_at = self._observed_at(event)

        if isinstance(event, JobSubmissionEvent):
            return self._handle_submission_event(
                event=event,
                event_type=event_type,
                observed_at=observed_at,
            )

        return self._handle_execution_event(
            event=event,
            event_type=event_type,
            observed_at=observed_at,
        )

    def _handle_execution_event(
        self,
        event: JobExecutionEvent,
        event_type: str,
        observed_at: datetime,
    ) -> SchedulerEventRecord:
        exception = None
        traceback_text = None
        run_id = None
        execution_id = None

        if event_type == "ERROR":
            exception = self._format_exception(event.exception)
            traceback_text = event.traceback

        if (
            event_type == "EXECUTED"
            and isinstance(
                event.retval,
                GTA6MonitorExecutionResult,
            )
        ):
            run_id = event.retval.run_id
            execution_id = event.retval.execution_id

        record = SchedulerEventRecord(
            job_id=event.job_id,
            event_type=event_type,
            scheduled_run_time=event.scheduled_run_time,
            observed_at=observed_at,
            exception=exception,
            traceback_text=traceback_text,
            run_id=run_id,
            execution_id=execution_id,
        )

        self._log_record(record)

        return record

    def _handle_submission_event(
        self,
        event: JobSubmissionEvent,
        event_type: str,
        observed_at: datetime,
    ) -> SchedulerEventRecord:
        record = SchedulerEventRecord(
            job_id=event.job_id,
            event_type=event_type,
            scheduled_run_times=tuple(event.scheduled_run_times),
            observed_at=observed_at,
        )

        self._log_record(record)

        return record

    def _resolve_event_type(self, event_code: int) -> str | None:
        return self.EVENT_NAMES.get(event_code)

    @staticmethod
    def _observed_at(
        event: JobExecutionEvent | JobSubmissionEvent,
    ) -> datetime:
        timezone = None

        if isinstance(event, JobExecutionEvent):
            timezone = event.scheduled_run_time.tzinfo

        elif event.scheduled_run_times:
            timezone = event.scheduled_run_times[0].tzinfo

        return datetime.now(tz=timezone)

    @staticmethod
    def _format_exception(
        exception: BaseException | None,
    ) -> str | None:
        if exception is None:
            return None

        return f"{type(exception).__name__}: {exception}"

    def _log_record(
        self,
        record: SchedulerEventRecord,
    ) -> None:
        if record.event_type == "ERROR":
            self._logger.error(
                "GTA6 scheduler job error: "
                "job_id=%s scheduled_run_time=%s exception=%s",
                record.job_id,
                record.scheduled_run_time.isoformat()
                if record.scheduled_run_time
                else None,
                record.exception,
            )

        elif record.event_type == "MISSED":
            self._logger.warning(
                "GTA6 scheduler job missed: "
                "job_id=%s scheduled_run_time=%s",
                record.job_id,
                record.scheduled_run_time.isoformat()
                if record.scheduled_run_time
                else None,
            )

        elif record.event_type == "MAX_INSTANCES":
            self._logger.warning(
                "GTA6 scheduler job blocked by max_instances: "
                "job_id=%s scheduled_run_times=%s",
                record.job_id,
                [
                    scheduled_run_time.isoformat()
                    for scheduled_run_time in record.scheduled_run_times
                ],
            )

        elif record.event_type == "EXECUTED":
            self._logger.info(
                "GTA6 scheduler job executed: "
                "job_id=%s scheduled_run_time=%s",
                record.job_id,
                record.scheduled_run_time.isoformat()
                if record.scheduled_run_time
                else None,
            )


def create_scheduler_event_listener(
    observability: GTA6SchedulerObservability,
):
    """
    Cria o listener compatível com scheduler.add_listener().
    """

    def listener(
        event: JobExecutionEvent | JobSubmissionEvent,
    ) -> None:
        observability.handle_event(event)

    return listener
