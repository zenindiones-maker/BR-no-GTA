from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import gta6_monitor_run_service
from app.services.gta6_monitor_execution_error import (
    GTA6MonitorExecutionError,
)
from app.services.gta6_monitor_run_lifecycle_service import (
    GTA6_MONITOR_RUN_COMPLETED,
    GTA6_MONITOR_RUN_ERROR,
    GTA6_MONITOR_RUN_RUNNING,
)


def make_page(
    content: str = "<html>GTA VI</html>",
    url: str = "https://www.rockstargames.com/newswire",
):
    return SimpleNamespace(
        url=url,
        status_code=200,
        content=content,
    )


class FakeMonitor:
    def __init__(self, page):
        self.page = page

    def fetch(self, url):
        return self.page


def test_run_once_creates_running_and_completes_successfully(
    monkeypatch,
):
    page = make_page()

    started = []
    completed = []

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "GTA6ViceMonitor",
        lambda timeout: FakeMonitor(page),
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "get_gta6_monitor_state",
        lambda url: {
            "url": url,
            "content_hash": "same-hash",
        },
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "detect_content_change",
        lambda content, previous_hash: SimpleNamespace(
            changed=False,
            previous_hash=previous_hash,
            current_hash="same-hash",
        ),
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "start_gta6_monitor_run",
        lambda url: started.append(url) or {
            "id": 123,
            "status": GTA6_MONITOR_RUN_RUNNING,
            "url": url,
        },
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "complete_gta6_monitor_run",
        lambda **kwargs: completed.append(kwargs) or {
            "id": kwargs["run_id"],
            "status": GTA6_MONITOR_RUN_COMPLETED,
        },
    )

    result = gta6_monitor_run_service.run_gta6_monitor_once()

    assert result.change.changed is False

    assert started == [page.url]

    assert completed == [
        {
            "run_id": 123,
            "status_code": 200,
            "baseline": False,
            "items_found": 0,
            "items_ingested": 0,
            "items_duplicated": 0,
        }
    ]


def test_run_once_marks_error_when_execution_fails(
    monkeypatch,
):
    page = make_page()

    started = []
    failed = []

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "GTA6ViceMonitor",
        lambda timeout: FakeMonitor(page),
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "get_gta6_monitor_state",
        lambda url: {
            "url": url,
            "content_hash": "old-hash",
        },
    )

    def fail_detect(content, previous_hash):
        raise RuntimeError("change detection failed")

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "detect_content_change",
        fail_detect,
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "start_gta6_monitor_run",
        lambda url: started.append(url) or {
            "id": 456,
            "status": GTA6_MONITOR_RUN_RUNNING,
            "url": url,
        },
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "fail_gta6_monitor_run",
        lambda **kwargs: failed.append(kwargs) or {
            "id": kwargs["run_id"],
            "status": GTA6_MONITOR_RUN_ERROR,
            "error": kwargs["error"],
        },
    )

    with pytest.raises(
        GTA6MonitorExecutionError,
        match="change detection failed",
    ) as exc_info:
        gta6_monitor_run_service.run_gta6_monitor_once()

    assert isinstance(exc_info.value.cause, RuntimeError)
    assert str(exc_info.value.cause) == "change detection failed"
    assert exc_info.value.run_id == 456
    assert exc_info.value.job_id == "gta6-monitor"
    assert exc_info.value.execution_id

    assert started == [page.url]

    assert failed == [
        {
            "run_id": 456,
            "error": "change detection failed",
            "status_code": 200,
        }
    ]


def test_run_once_does_not_mark_error_after_success(
    monkeypatch,
):
    page = make_page()

    failed = []

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "GTA6ViceMonitor",
        lambda timeout: FakeMonitor(page),
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "get_gta6_monitor_state",
        lambda url: {
            "url": url,
            "content_hash": "same-hash",
        },
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "detect_content_change",
        lambda content, previous_hash: SimpleNamespace(
            changed=False,
            previous_hash=previous_hash,
            current_hash="same-hash",
        ),
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "start_gta6_monitor_run",
        lambda url: {
            "id": 789,
            "status": GTA6_MONITOR_RUN_RUNNING,
            "url": url,
        },
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "complete_gta6_monitor_run",
        lambda **kwargs: {
            "id": kwargs["run_id"],
            "status": GTA6_MONITOR_RUN_COMPLETED,
        },
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "fail_gta6_monitor_run",
        lambda **kwargs: failed.append(kwargs),
    )

    gta6_monitor_run_service.run_gta6_monitor_once()

    assert failed == []
