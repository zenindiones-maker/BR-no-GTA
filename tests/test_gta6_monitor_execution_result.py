from datetime import datetime, timezone

import pytest

from app.services.gta6_monitor_execution_result import (
    GTA6MonitorExecutionResult,
)
from app.services.gta6_monitor_execution_context import (
    GTA6MonitorExecutionContext,
)


def test_execution_result_requires_context():
    with pytest.raises(ValueError, match="context must be provided"):
        GTA6MonitorExecutionResult(
            context=None,
            result={"status": "ok"},
        )


def test_execution_result_requires_result():
    context = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )

    with pytest.raises(ValueError, match="result must be provided"):
        GTA6MonitorExecutionResult(
            context=context,
            result=None,
        )


def test_execution_result_preserves_context_and_result():
    context = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )
    result = {
        "status": "ok",
        "items_found": 3,
    }

    execution_result = GTA6MonitorExecutionResult(
        context=context,
        result=result,
    )

    assert execution_result.context is context
    assert execution_result.result is result


def test_execution_result_exposes_execution_id():
    context = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )

    execution_result = GTA6MonitorExecutionResult(
        context=context,
        result={"status": "ok"},
    )

    assert execution_result.execution_id == context.execution_id


def test_execution_result_exposes_run_id():
    context = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )

    execution_result = GTA6MonitorExecutionResult(
        context=context,
        result={"status": "ok"},
    )

    assert execution_result.run_id == 42


def test_execution_result_is_immutable():
    context = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=42,
    )

    execution_result = GTA6MonitorExecutionResult(
        context=context,
        result={"status": "ok"},
    )

    with pytest.raises(AttributeError):
        execution_result.context = None
