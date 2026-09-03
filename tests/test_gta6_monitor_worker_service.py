from unittest.mock import Mock

import pytest

from app.services.gta6_monitor_worker_service import (
    execute_gta6_monitor,
)


def test_execute_gta6_monitor_delegates_to_monitor_run_service(
    monkeypatch,
):
    expected = Mock()

    orchestration = Mock(return_value=expected)

    monkeypatch.setattr(
        "app.services.gta6_monitor_worker_service.run_gta6_monitor_once",
        orchestration,
    )

    result = execute_gta6_monitor(
        timeout=30.0,
    )

    assert result is expected

    orchestration.assert_called_once_with(
        timeout=30.0,
    )


def test_execute_gta6_monitor_uses_default_timeout(
    monkeypatch,
):
    orchestration = Mock()

    monkeypatch.setattr(
        "app.services.gta6_monitor_worker_service.run_gta6_monitor_once",
        orchestration,
    )

    execute_gta6_monitor()

    orchestration.assert_called_once_with(
        timeout=15.0,
    )


def test_execute_gta6_monitor_normalizes_integer_timeout(
    monkeypatch,
):
    orchestration = Mock()

    monkeypatch.setattr(
        "app.services.gta6_monitor_worker_service.run_gta6_monitor_once",
        orchestration,
    )

    execute_gta6_monitor(
        timeout=20,
    )

    orchestration.assert_called_once_with(
        timeout=20.0,
    )


@pytest.mark.parametrize(
    "timeout",
    [
        0,
        -1,
        -10.5,
    ],
)
def test_execute_gta6_monitor_rejects_non_positive_timeout(
    timeout,
):
    with pytest.raises(
        ValueError,
        match="timeout",
    ):
        execute_gta6_monitor(
            timeout=timeout,
        )


@pytest.mark.parametrize(
    "timeout",
    [
        None,
        "15",
        True,
        False,
    ],
)
def test_execute_gta6_monitor_rejects_invalid_timeout(
    timeout,
):
    with pytest.raises(
        ValueError,
        match="timeout",
    ):
        execute_gta6_monitor(
            timeout=timeout,
        )
