from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import gta6_monitor_run_service
from app.services.gta6_monitor_execution_error import (
    GTA6MonitorExecutionError,
)


class FakeMonitor:
    def __init__(self, page):
        self.page = page
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        return self.page


def make_page(content: str, url: str = "https://www.rockstargames.com/newswire"):
    return SimpleNamespace(
        url=url,
        status_code=200,
        content=content,
    )


def test_first_run_ingests_changed_content(monkeypatch):
    content = """
    <html>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "GTA VI News",
            "description": "Official GTA VI update",
            "url": "https://www.rockstargames.com/newswire/article-1",
            "datePublished": "2026-09-03T12:00:00Z"
        }
        </script>
    </html>
    """

    page = make_page(content)
    monitor = FakeMonitor(page)
    saved_states = []
    ingested = []
    events = []

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "GTA6ViceMonitor",
        lambda timeout: monitor,
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "get_gta6_monitor_state",
        lambda url: None,
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "ingest_gta6_source_items",
        lambda items: (
            ingested.extend(items)
            or [
                {
                    "research_item_id": 10,
                    "knowledge_id": 20,
                    "knowledge": {
                        "title": items[0].title,
                    },
                    "duplicate": False,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "save_gta6_monitor_state",
        lambda url, content_hash: saved_states.append(
            (url, content_hash)
        ),
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "record_gta6_monitor_change",
        lambda **kwargs: events.append(kwargs),
    )

    result = gta6_monitor_run_service.run_gta6_monitor_once()

    assert result.baseline is True
    assert result.change.changed is True
    assert result.status_code == 200
    assert result.items_found == 1
    assert result.items_ingested == 1
    assert result.items_duplicated == 0
    assert result.knowledge_ids == [20]

    assert len(ingested) == 1
    assert ingested[0].title == "GTA VI News"

    assert len(saved_states) == 1
    assert saved_states[0][0] == page.url
    assert saved_states[0][1] == result.change.current_hash

    assert events == [
        {
            "url": page.url,
            "previous_hash": None,
            "current_hash": result.change.current_hash,
        }
    ]


def test_unchanged_run_does_not_ingest(monkeypatch):
    content = "<html>GTA VI</html>"

    from app.services.gta6_change_detector import (
        hash_monitored_content,
    )

    previous_hash = hash_monitored_content(content)
    page = make_page(content)
    monitor = FakeMonitor(page)
    saved_states = []

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "GTA6ViceMonitor",
        lambda timeout: monitor,
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "get_gta6_monitor_state",
        lambda url: {
            "url": url,
            "content_hash": previous_hash,
        },
    )

    def fail_if_called(items):
        raise AssertionError(
            "ingest_gta6_source_items should not be called"
        )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "ingest_gta6_source_items",
        fail_if_called,
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "save_gta6_monitor_state",
        lambda url, content_hash: saved_states.append(
            (url, content_hash)
        ),
    )

    result = gta6_monitor_run_service.run_gta6_monitor_once()

    assert result.baseline is False
    assert result.change.changed is False
    assert result.items_found == 0
    assert result.items_ingested == 0
    assert result.items_duplicated == 0
    assert result.knowledge_ids == []
    assert saved_states == [(page.url, previous_hash)]


def test_changed_run_counts_duplicates(monkeypatch):
    content = "<html>GTA VI updated</html>"
    page = make_page(content)
    monitor = FakeMonitor(page)

    from app.services.gta6_change_detector import (
        hash_monitored_content,
    )

    previous_hash = hash_monitored_content(
        "<html>GTA VI old</html>"
    )

    fake_item = SimpleNamespace(
        title="GTA VI",
    )

    saved_states = []

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "GTA6ViceMonitor",
        lambda timeout: monitor,
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "get_gta6_monitor_state",
        lambda url: {
            "url": url,
            "content_hash": previous_hash,
        },
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "parse_rockstar_newswire_html",
        lambda content: [fake_item, fake_item],
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "ingest_gta6_source_items",
        lambda items: [
            {
                "research_item_id": 1,
                "knowledge_id": 11,
                "knowledge": {"title": "new"},
                "duplicate": False,
            },
            {
                "research_item_id": 2,
                "knowledge_id": 22,
                "knowledge": None,
                "duplicate": True,
            },
        ],
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "save_gta6_monitor_state",
        lambda url, content_hash: saved_states.append(
            (url, content_hash)
        ),
    )

    result = gta6_monitor_run_service.run_gta6_monitor_once()

    assert result.baseline is False
    assert result.change.changed is True
    assert result.items_found == 2
    assert result.items_ingested == 1
    assert result.items_duplicated == 1
    assert result.knowledge_ids == [11, 22]
    assert len(saved_states) == 1


def test_ingestion_failure_does_not_update_monitor_state(monkeypatch):
    content = "<html>GTA VI changed</html>"
    page = make_page(content)
    monitor = FakeMonitor(page)

    from app.services.gta6_change_detector import (
        hash_monitored_content,
    )

    previous_hash = hash_monitored_content(
        "<html>GTA VI old</html>"
    )

    saved_states = []

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "GTA6ViceMonitor",
        lambda timeout: monitor,
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "get_gta6_monitor_state",
        lambda url: {
            "url": url,
            "content_hash": previous_hash,
        },
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "parse_rockstar_newswire_html",
        lambda content: [
            SimpleNamespace(title="GTA VI"),
        ],
    )

    def fail_ingestion(items):
        raise RuntimeError("ingestion failed")

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "ingest_gta6_source_items",
        fail_ingestion,
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "save_gta6_monitor_state",
        lambda url, content_hash: saved_states.append(
            (url, content_hash)
        ),
    )

    with pytest.raises(
        GTA6MonitorExecutionError,
        match="ingestion failed",
    ) as exc_info:
        gta6_monitor_run_service.run_gta6_monitor_once()

    assert isinstance(exc_info.value.cause, RuntimeError)
    assert str(exc_info.value.cause) == "ingestion failed"
    assert exc_info.value.run_id > 0
    assert exc_info.value.job_id == "gta6-monitor"
    assert exc_info.value.execution_id

    assert saved_states == []


def test_previous_hash_is_loaded_for_same_url(monkeypatch):
    content = "<html>GTA VI</html>"
    page = make_page(content)
    monitor = FakeMonitor(page)

    captured = {}

    from app.services.gta6_change_detector import (
        hash_monitored_content,
    )

    previous_hash = hash_monitored_content(content)

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "GTA6ViceMonitor",
        lambda timeout: monitor,
    )

    def fake_get_state(url):
        captured["url"] = url
        return {
            "url": url,
            "content_hash": previous_hash,
        }

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "get_gta6_monitor_state",
        fake_get_state,
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "save_gta6_monitor_state",
        lambda url, content_hash: None,
    )

    result = gta6_monitor_run_service.run_gta6_monitor_once()

    assert captured["url"] == result.url
    assert result.change.previous_hash == previous_hash
    assert result.change.changed is False
