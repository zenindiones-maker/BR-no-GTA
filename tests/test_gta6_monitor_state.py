import pytest

from app.services.gta6_monitor_state import (
    GTA6MonitorState,
    create_monitor_state,
    get_previous_hash,
)


def test_create_monitor_state():
    state = create_monitor_state(
        " https://example.com/gta6 ",
        " abc123 ",
    )

    assert isinstance(state, GTA6MonitorState)
    assert state.url == "https://example.com/gta6"
    assert state.content_hash == "abc123"


def test_get_previous_hash_for_matching_url():
    state = create_monitor_state(
        "https://example.com/gta6",
        "abc123",
    )

    assert get_previous_hash(
        state,
        "https://example.com/gta6",
    ) == "abc123"


def test_get_previous_hash_for_different_url():
    state = create_monitor_state(
        "https://example.com/gta6",
        "abc123",
    )

    assert get_previous_hash(
        state,
        "https://example.com/playstation",
    ) is None


def test_get_previous_hash_without_state():
    assert get_previous_hash(
        None,
        "https://example.com/gta6",
    ) is None


def test_url_is_normalized():
    state = create_monitor_state(
        "  https://example.com/gta6  ",
        "abc123",
    )

    assert get_previous_hash(
        state,
        "https://example.com/gta6",
    ) == "abc123"


def test_empty_url_is_rejected():
    with pytest.raises(
        ValueError,
        match="url must be a non-empty string",
    ):
        create_monitor_state("", "abc123")


def test_empty_hash_is_rejected():
    with pytest.raises(
        ValueError,
        match="content_hash must be a non-empty string",
    ):
        create_monitor_state(
            "https://example.com/gta6",
            "",
        )


def test_invalid_state_is_rejected():
    with pytest.raises(
        ValueError,
        match="state must be a GTA6MonitorState or None",
    ):
        get_previous_hash(
            object(),
            "https://example.com/gta6",
        )
