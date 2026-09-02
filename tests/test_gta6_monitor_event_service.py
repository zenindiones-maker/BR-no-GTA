from app.services.gta6_monitor_event_service import (
    record_gta6_monitor_change,
)


def test_record_gta6_monitor_change_persists_event():
    result = record_gta6_monitor_change(
        url=" https://example.com/news ",
        previous_hash=" old-hash ",
        current_hash=" new-hash ",
        detected_at=" 2026-09-02T12:00:00Z ",
    )

    assert result["id"] > 0
    assert result["url"] == "https://example.com/news"
    assert result["previous_hash"] == "old-hash"
    assert result["current_hash"] == "new-hash"
    assert result["detected_at"] == "2026-09-02T12:00:00Z"
    assert "created_at" in result
