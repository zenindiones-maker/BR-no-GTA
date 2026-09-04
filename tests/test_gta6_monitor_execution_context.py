import pytest

from app.services.gta6_monitor_execution_context import (
    GTA6MonitorExecutionContext,
)


def test_context_requires_execution_id():
    with pytest.raises(
        ValueError,
        match="execution_id must be a non-empty string",
    ):
        GTA6MonitorExecutionContext(
            execution_id="",
            job_id="gta6-monitor",
            run_id=1,
        )


def test_context_requires_job_id():
    with pytest.raises(
        ValueError,
        match="job_id must be a non-empty string",
    ):
        GTA6MonitorExecutionContext(
            execution_id="execution-123",
            job_id="",
            run_id=1,
        )


def test_context_requires_run_id():
    with pytest.raises(
        ValueError,
        match="run_id must be a positive integer",
    ):
        GTA6MonitorExecutionContext(
            execution_id="execution-123",
            job_id="gta6-monitor",
            run_id=0,
        )


def test_context_rejects_boolean_run_id():
    with pytest.raises(
        ValueError,
        match="run_id must be a positive integer",
    ):
        GTA6MonitorExecutionContext(
            execution_id="execution-123",
            job_id="gta6-monitor",
            run_id=True,
        )


def test_context_is_immutable():
    context = GTA6MonitorExecutionContext(
        execution_id="execution-123",
        job_id="gta6-monitor",
        run_id=42,
    )

    with pytest.raises(AttributeError):
        context.execution_id = "another-execution"


def test_context_preserves_execution_identity():
    context = GTA6MonitorExecutionContext(
        execution_id="execution-123",
        job_id="gta6-monitor",
        run_id=42,
    )

    assert context.execution_id == "execution-123"
    assert context.job_id == "gta6-monitor"
    assert context.run_id == 42


def test_context_can_be_created_with_factory():
    context = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )

    assert context.execution_id
    assert context.job_id == "gta6-monitor"
    assert context.run_id == 42


def test_context_factory_generates_unique_execution_ids():
    first = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )
    second = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )

    assert first.execution_id != second.execution_id
