from dataclasses import dataclass

import app.services.gta6_monitor_persistence_service as module
from app.integrations.gta6.vice_monitor import GTA6ViceMonitor


@dataclass
class FakePage:
    url: str
    status_code: int
    content: str


def test_monitor_persists_baseline_and_returns_content(monkeypatch):
    page = FakePage(
        url="https://example.com",
        status_code=200,
        content="<html>baseline</html>",
    )

    monitor = GTA6ViceMonitor()
    monkeypatch.setattr(
        monitor,
        "fetch",
        lambda url: page,
    )

    monkeypatch.setattr(
        module,
        "get_gta6_monitor_state",
        lambda url: None,
    )

    saved = {}

    def save_state(url, content_hash):
        saved["url"] = url
        saved["content_hash"] = content_hash

    monkeypatch.setattr(
        module,
        "save_gta6_monitor_state",
        save_state,
    )

    result = module.monitor_gta6_page_persisted(
        monitor,
        page.url,
    )

    assert result.url == page.url
    assert result.status_code == 200
    assert result.content == page.content
    assert result.baseline is True
    assert result.change.changed is True
    assert saved["url"] == page.url


def test_monitor_returns_changed_content(monkeypatch):
    page = FakePage(
        url="https://example.com",
        status_code=200,
        content="<html>new content</html>",
    )

    monitor = GTA6ViceMonitor()
    monkeypatch.setattr(
        monitor,
        "fetch",
        lambda url: page,
    )

    monkeypatch.setattr(
        module,
        "get_gta6_monitor_state",
        lambda url: {
            "content_hash": "old-hash",
        },
    )

    monkeypatch.setattr(
        module,
        "save_gta6_monitor_state",
        lambda url, content_hash: None,
    )

    recorded = {}

    def record_change(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(
        module,
        "record_gta6_monitor_change",
        record_change,
    )

    result = module.monitor_gta6_page_persisted(
        monitor,
        page.url,
    )

    assert result.content == page.content
    assert result.baseline is False
    assert result.change.changed is True
    assert recorded["url"] == page.url
    assert recorded["previous_hash"] == "old-hash"
    assert recorded["current_hash"] == result.change.current_hash
