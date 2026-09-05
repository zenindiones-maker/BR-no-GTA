import pytest

from app.services.gta6_monitor_execution_context import (
    GTA6MonitorExecutionContext,
)
from app.services.gta6_monitor_execution_error import (
    GTA6MonitorExecutionError,
)


def create_context():
    return GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )


def test_execution_error_requires_context():
    with pytest.raises(
        ValueError,
        match="context must be provided",
    ):
        GTA6MonitorExecutionError(
            context=None,
            cause=RuntimeError("boom"),
        )


def test_execution_error_requires_cause():
    context = create_context()

    with pytest.raises(
        ValueError,
        match="cause must be provided",
    ):
        GTA6MonitorExecutionError(
            context=context,
            cause=None,
        )


def test_execution_error_preserves_context_and_cause():
    context = create_context()
    cause = RuntimeError("boom")

    error = GTA6MonitorExecutionError(
        context=context,
        cause=cause,
    )

    assert error.context is context
    assert error.cause is cause


def test_execution_error_exposes_execution_id():
    context = create_context()
    error = GTA6MonitorExecutionError(
        context=context,
        cause=RuntimeError("boom"),
    )

    assert error.execution_id == context.execution_id


def test_execution_error_exposes_run_id():
    context = create_context()
    error = GTA6MonitorExecutionError(
        context=context,
        cause=RuntimeError("boom"),
    )

    assert error.run_id == 42


def test_execution_error_exposes_job_id():
    context = create_context()
    error = GTA6MonitorExecutionError(
        context=context,
        cause=RuntimeError("boom"),
    )

    assert error.job_id == "gta6-monitor"


def test_execution_error_is_an_exception():
    context = create_context()

    error = GTA6MonitorExecutionError(
        context=context,
        cause=RuntimeError("boom"),
    )

    assert isinstance(error, Exception)


def test_execution_error_is_immutable():
    context = create_context()

    error = GTA6MonitorExecutionError(
        context=context,
        cause=RuntimeError("boom"),
    )

    with pytest.raises(AttributeError):
        error.context = None
