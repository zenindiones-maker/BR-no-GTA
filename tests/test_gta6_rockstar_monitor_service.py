from app.integrations.gta6.rockstar_news import ROCKSTAR_NEWSWIRE_URL
from app.services import gta6_rockstar_monitor_service as service


def test_monitor_rockstar_newswire_uses_official_url(monkeypatch):
    calls = []

    class FakeMonitor:
        def __init__(self, *, timeout):
            self.timeout = timeout

    def fake_persisted_monitor(monitor, url):
        calls.append((monitor, url))
        return "result"

    monkeypatch.setattr(
        service,
        "GTA6ViceMonitor",
        FakeMonitor,
    )
    monkeypatch.setattr(
        service,
        "monitor_gta6_page_persisted",
        fake_persisted_monitor,
    )

    result = service.monitor_rockstar_newswire(timeout=9)

    assert result == "result"
    assert len(calls) == 1
    assert isinstance(calls[0][0], FakeMonitor)
    assert calls[0][0].timeout == 9
    assert calls[0][1] == ROCKSTAR_NEWSWIRE_URL
