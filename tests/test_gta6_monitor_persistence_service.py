from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services import gta6_monitor_persistence_service as service


@dataclass
class FakePage:
    url: str
    status_code: int
    content: str


class FakeMonitor(service.GTA6ViceMonitor):
    def __init__(
        self,
        content: str,
        *,
        response_url: str = "https://example.com",
        status_code: int = 200,
    ) -> None:
        super().__init__()
        self.content = content
        self.response_url = response_url
        self.response_status_code = status_code

    def fetch(self, url: str) -> FakePage:
        return FakePage(
            url=self.response_url,
            status_code=self.response_status_code,
            content=self.content,
        )


def test_rejects_invalid_monitor() -> None:
    with pytest.raises(ValueError, match="GTA6ViceMonitor"):
        service.monitor_gta6_page_persisted(
            object(),
            "https://example.com",
        )


def test_first_execution_is_baseline(monkeypatch) -> None:
    saved = []

    monkeypatch.setattr(
        service,
        "get_gta6_monitor_state",
        lambda url: None,
    )
    monkeypatch.setattr(
        service,
        "save_gta6_monitor_state",
        lambda url, content_hash: saved.append(
            (url, content_hash)
        ),
    )

    monitor = FakeMonitor("first content")

    result = service.monitor_gta6_page_persisted(
        monitor,
        "https://example.com",
    )

    assert result.baseline is True
    assert result.change.changed is True
    assert result.change.previous_hash is None
    assert len(saved) == 1


def test_unchanged_content_is_not_reported_as_change(
    monkeypatch,
) -> None:
    content = "<html>same content</html>"

    from app.services.gta6_change_detector import (
        hash_monitored_content,
    )

    previous_hash = hash_monitored_content(content)

    monkeypatch.setattr(
        service,
        "get_gta6_monitor_state",
        lambda url: {
            "id": 1,
            "url": url,
            "content_hash": previous_hash,
            "updated_at": "2026-01-01 00:00:00",
        },
    )

    saved = []

    monkeypatch.setattr(
        service,
        "save_gta6_monitor_state",
        lambda url, content_hash: saved.append(
            (url, content_hash)
        ),
    )

    monitor = FakeMonitor(content)

    result = service.monitor_gta6_page_persisted(
        monitor,
        "https://example.com",
    )

    assert result.baseline is False
    assert result.change.changed is False
    assert result.change.previous_hash == previous_hash
    assert result.change.current_hash == previous_hash
    assert saved == [
        ("https://example.com", previous_hash)
    ]


def test_changed_content_is_detected_and_persisted(
    monkeypatch,
) -> None:
    from app.services.gta6_change_detector import (
        hash_monitored_content,
    )

    old_hash = hash_monitored_content(
        "<html>old content</html>"
    )

    monkeypatch.setattr(
        service,
        "get_gta6_monitor_state",
        lambda url: {
            "id": 1,
            "url": url,
            "content_hash": old_hash,
            "updated_at": "2026-01-01 00:00:00",
        },
    )

    saved = []

    monkeypatch.setattr(
        service,
        "save_gta6_monitor_state",
        lambda url, content_hash: saved.append(
            (url, content_hash)
        ),
    )

    monitor = FakeMonitor("<html>new content</html>")

    result = service.monitor_gta6_page_persisted(
        monitor,
        "https://example.com",
    )

    assert result.baseline is False
    assert result.change.changed is True
    assert result.change.previous_hash == old_hash
    assert result.change.current_hash != old_hash
    assert saved == [
        ("https://example.com", result.change.current_hash)
    ]


def test_uses_monitor_response_url_when_persisting(
    monkeypatch,
) -> None:
    saved = []

    monkeypatch.setattr(
        service,
        "get_gta6_monitor_state",
        lambda url: None,
    )
    monkeypatch.setattr(
        service,
        "save_gta6_monitor_state",
        lambda url, content_hash: saved.append(
            (url, content_hash)
        ),
    )

    monitor = FakeMonitor(
        "content",
        response_url="https://example.com/final",
    )

    result = service.monitor_gta6_page_persisted(
        monitor,
        "https://example.com/start",
    )

    assert result.url == "https://example.com/final"
    assert saved[0][0] == "https://example.com/final"
