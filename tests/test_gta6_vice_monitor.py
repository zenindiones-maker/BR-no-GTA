from types import SimpleNamespace

import pytest

from app.integrations.gta6.vice_monitor import (
    DEFAULT_USER_AGENT,
    GTA6ViceMonitor,
)


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"<html>GTA VI</html>"


def test_fetch_returns_monitored_page(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["user_agent"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    monitor = GTA6ViceMonitor(timeout=12.0)

    result = monitor.fetch(
        "https://www.rockstargames.com/VI"
    )

    assert result.url == "https://www.rockstargames.com/VI"
    assert result.status_code == 200
    assert result.content == "<html>GTA VI</html>"

    assert captured["url"] == (
        "https://www.rockstargames.com/VI"
    )
    assert captured["user_agent"] == DEFAULT_USER_AGENT
    assert captured["timeout"] == 12.0


def test_custom_user_agent_is_used(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["user_agent"] = request.get_header(
            "User-agent"
        )
        return FakeResponse()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    monitor = GTA6ViceMonitor(
        user_agent="BR-test/2.0"
    )

    monitor.fetch("https://example.com")

    assert captured["user_agent"] == "BR-test/2.0"


def test_network_error_becomes_runtime_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise OSError("connection failed")

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    monitor = GTA6ViceMonitor()

    with pytest.raises(
        RuntimeError,
        match="GTA6 monitored page request failed",
    ):
        monitor.fetch("https://example.com")


def test_invalid_url_is_rejected():
    monitor = GTA6ViceMonitor()

    with pytest.raises(
        ValueError,
        match="url must be a non-empty string",
    ):
        monitor.fetch("")


def test_invalid_scheme_is_rejected():
    monitor = GTA6ViceMonitor()

    with pytest.raises(
        ValueError,
        match="url must use http or https",
    ):
        monitor.fetch("ftp://example.com")


def test_missing_host_is_rejected():
    monitor = GTA6ViceMonitor()

    with pytest.raises(
        ValueError,
        match="url must include a host",
    ):
        monitor.fetch("https://")


def test_invalid_timeout_is_rejected():
    with pytest.raises(
        ValueError,
        match="timeout must be greater than zero",
    ):
        GTA6ViceMonitor(timeout=0)


def test_invalid_user_agent_is_rejected():
    with pytest.raises(
        ValueError,
        match="user_agent must be a non-empty string",
    ):
        GTA6ViceMonitor(user_agent="   ")
