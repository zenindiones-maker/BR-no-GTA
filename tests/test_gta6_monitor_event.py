from __future__ import annotations

import pytest

from app.services.gta6_monitor_event import (
    GTA6MonitorEvent,
    create_gta6_monitor_event,
)


def test_creates_event() -> None:
    event = create_gta6_monitor_event(
        " https://example.com ",
        " old-hash ",
        " new-hash ",
        " 2026-09-02T00:00:00 ",
    )

    assert isinstance(event, GTA6MonitorEvent)
    assert event.url == "https://example.com"
    assert event.previous_hash == "old-hash"
    assert event.current_hash == "new-hash"
    assert event.detected_at == "2026-09-02T00:00:00"


def test_allows_missing_previous_hash() -> None:
    event = create_gta6_monitor_event(
        "https://example.com",
        None,
        "new-hash",
    )

    assert event.previous_hash is None


def test_allows_missing_detected_at() -> None:
    event = create_gta6_monitor_event(
        "https://example.com",
        None,
        "new-hash",
    )

    assert event.detected_at is None


def test_rejects_invalid_url() -> None:
    with pytest.raises(
        ValueError,
        match="url must be a non-empty string",
    ):
        create_gta6_monitor_event(
            "",
            None,
            "hash",
        )


def test_rejects_invalid_previous_hash() -> None:
    with pytest.raises(
        ValueError,
        match="previous_hash must be a non-empty string or None",
    ):
        create_gta6_monitor_event(
            "https://example.com",
            " ",
            "hash",
        )


def test_rejects_invalid_current_hash() -> None:
    with pytest.raises(
        ValueError,
        match="current_hash must be a non-empty string",
    ):
        create_gta6_monitor_event(
            "https://example.com",
            None,
            "",
        )


def test_rejects_invalid_detected_at() -> None:
    with pytest.raises(
        ValueError,
        match="detected_at must be a non-empty string or None",
    ):
        create_gta6_monitor_event(
            "https://example.com",
            None,
            "hash",
            " ",
        )


def test_event_is_immutable() -> None:
    event = create_gta6_monitor_event(
        "https://example.com",
        None,
        "hash",
    )

    with pytest.raises(AttributeError):
        event.url = "https://other.example.com"
