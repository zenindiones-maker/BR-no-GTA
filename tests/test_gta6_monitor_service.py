from app.integrations.gta6.vice_monitor import (
    GTA6ViceMonitor,
    MonitoredPage,
)
from app.services.gta6_change_detector import (
    hash_monitored_content,
)
from app.services.gta6_monitor_service import (
    GTA6MonitorResult,
    monitor_gta6_page,
)


class FakeMonitor(GTA6ViceMonitor):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.requested_url = None

    def fetch(self, url):
        self.requested_url = url
        return self.page


def test_monitor_service_detects_change():
    page = MonitoredPage(
        url="https://example.com/gta6",
        status_code=200,
        content="GTA VI release date: 2026",
    )

    monitor = FakeMonitor(page)

    previous_hash = hash_monitored_content(
        "GTA VI release date: 2025"
    )

    result = monitor_gta6_page(
        monitor,
        page.url,
        previous_hash,
    )

    assert isinstance(result, GTA6MonitorResult)
    assert result.url == page.url
    assert result.status_code == 200
    assert result.change.changed is True
    assert monitor.requested_url == page.url


def test_monitor_service_detects_no_change():
    page = MonitoredPage(
        url="https://example.com/gta6",
        status_code=200,
        content="GTA VI release date: 2026",
    )

    monitor = FakeMonitor(page)

    previous_hash = hash_monitored_content(
        page.content
    )

    result = monitor_gta6_page(
        monitor,
        page.url,
        previous_hash,
    )

    assert result.change.changed is False
    assert result.change.current_hash == previous_hash


def test_first_observation_is_change():
    page = MonitoredPage(
        url="https://example.com/gta6",
        status_code=200,
        content="GTA VI",
    )

    monitor = FakeMonitor(page)

    result = monitor_gta6_page(
        monitor,
        page.url,
        None,
    )

    assert result.change.changed is True
    assert result.change.previous_hash is None


def test_monitor_service_preserves_status_code():
    page = MonitoredPage(
        url="https://example.com/gta6",
        status_code=204,
        content="",
    )

    monitor = FakeMonitor(page)

    result = monitor_gta6_page(
        monitor,
        page.url,
        None,
    )

    assert result.status_code == 204


def test_invalid_monitor_is_rejected():
    page = MonitoredPage(
        url="https://example.com/gta6",
        status_code=200,
        content="GTA VI",
    )

    try:
        monitor_gta6_page(
            object(),
            page.url,
            None,
        )
    except ValueError as exc:
        assert str(exc) == (
            "monitor must be a GTA6ViceMonitor"
        )
    else:
        raise AssertionError("ValueError was expected")
