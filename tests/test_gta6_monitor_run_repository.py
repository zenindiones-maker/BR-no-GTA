from __future__ import annotations

import pytest

from app.database.gta6_monitor_run_repository import (
    create_gta6_monitor_run,
    get_gta6_monitor_run,
    list_gta6_monitor_runs,
    update_gta6_monitor_run,
)


def test_create_gta6_monitor_run_persists_running_run():
    result = create_gta6_monitor_run(
        status="RUNNING",
        started_at="2026-09-04T20:00:00+00:00",
        url="https://www.rockstargames.com/newswire",
    )

    assert result["id"] > 0
    assert result["status"] == "RUNNING"
    assert result["started_at"] == "2026-09-04T20:00:00+00:00"
    assert result["finished_at"] is None
    assert result["url"] == "https://www.rockstargames.com/newswire"
    assert result["status_code"] is None
    assert result["baseline"] is False
    assert result["items_found"] == 0
    assert result["items_ingested"] == 0
    assert result["items_duplicated"] == 0
    assert result["error"] is None
    assert result["created_at"]


def test_create_gta6_monitor_run_persists_result_fields():
    result = create_gta6_monitor_run(
        status="RUNNING",
        started_at="2026-09-04T20:01:00+00:00",
        url="https://example.com/gta6",
        status_code=200,
        baseline=True,
        items_found=10,
        items_ingested=8,
        items_duplicated=2,
    )

    assert result["status_code"] == 200
    assert result["baseline"] is True
    assert result["items_found"] == 10
    assert result["items_ingested"] == 8
    assert result["items_duplicated"] == 2


def test_update_gta6_monitor_run_to_completed():
    created = create_gta6_monitor_run(
        status="RUNNING",
        started_at="2026-09-04T20:02:00+00:00",
        url="https://example.com/gta6",
    )

    result = update_gta6_monitor_run(
        run_id=created["id"],
        status="COMPLETED",
        finished_at="2026-09-04T20:02:15+00:00",
        status_code=200,
        baseline=False,
        items_found=5,
        items_ingested=4,
        items_duplicated=1,
    )

    assert result["id"] == created["id"]
    assert result["status"] == "COMPLETED"
    assert result["started_at"] == "2026-09-04T20:02:00+00:00"
    assert result["finished_at"] == "2026-09-04T20:02:15+00:00"
    assert result["status_code"] == 200
    assert result["baseline"] is False
    assert result["items_found"] == 5
    assert result["items_ingested"] == 4
    assert result["items_duplicated"] == 1
    assert result["error"] is None


def test_update_gta6_monitor_run_to_error():
    created = create_gta6_monitor_run(
        status="RUNNING",
        started_at="2026-09-04T20:03:00+00:00",
        url="https://example.com/gta6",
    )

    result = update_gta6_monitor_run(
        run_id=created["id"],
        status="ERROR",
        finished_at="2026-09-04T20:03:05+00:00",
        error="HTTP request failed",
    )

    assert result["status"] == "ERROR"
    assert result["finished_at"] == "2026-09-04T20:03:05+00:00"
    assert result["error"] == "HTTP request failed"


def test_get_gta6_monitor_run_returns_persisted_run():
    created = create_gta6_monitor_run(
        status="RUNNING",
        started_at="2026-09-04T20:04:00+00:00",
        url="https://example.com/gta6",
    )

    result = get_gta6_monitor_run(created["id"])

    assert result == created


def test_get_gta6_monitor_run_returns_none_for_unknown_id():
    result = get_gta6_monitor_run(999999999)

    assert result is None


def test_list_gta6_monitor_runs_returns_runs_in_id_order():
    first = create_gta6_monitor_run(
        status="RUNNING",
        started_at="2026-09-04T20:05:00+00:00",
        url="https://example.com/first",
    )

    second = create_gta6_monitor_run(
        status="COMPLETED",
        started_at="2026-09-04T20:06:00+00:00",
        url="https://example.com/second",
    )

    results = list_gta6_monitor_runs()

    ids = [item["id"] for item in results]

    assert first["id"] in ids
    assert second["id"] in ids
    assert ids.index(first["id"]) < ids.index(second["id"])


def test_list_gta6_monitor_runs_filters_by_status():
    running = create_gta6_monitor_run(
        status="RUNNING",
        started_at="2026-09-04T20:07:00+00:00",
        url="https://example.com/running",
    )

    create_gta6_monitor_run(
        status="COMPLETED",
        started_at="2026-09-04T20:08:00+00:00",
        url="https://example.com/completed",
    )

    results = list_gta6_monitor_runs(status="RUNNING")

    assert any(item["id"] == running["id"] for item in results)
    assert all(item["status"] == "RUNNING" for item in results)


def test_list_gta6_monitor_runs_filters_by_url():
    target_url = "https://example.com/target"

    target = create_gta6_monitor_run(
        status="RUNNING",
        started_at="2026-09-04T20:09:00+00:00",
        url=target_url,
    )

    create_gta6_monitor_run(
        status="RUNNING",
        started_at="2026-09-04T20:10:00+00:00",
        url="https://example.com/other",
    )

    results = list_gta6_monitor_runs(url=target_url)

    assert len(results) == 1
    assert results[0]["id"] == target["id"]
    assert results[0]["url"] == target_url


@pytest.mark.parametrize("status", ["INVALID", "", "running", "Completed"])
def test_create_gta6_monitor_run_rejects_invalid_status(status):
    with pytest.raises(ValueError, match="status must be one"):
        create_gta6_monitor_run(
            status=status,
            started_at="2026-09-04T20:11:00+00:00",
            url="https://example.com/gta6",
        )


def test_create_gta6_monitor_run_rejects_invalid_started_at():
    with pytest.raises(
        ValueError,
        match="started_at must be a non-empty string",
    ):
        create_gta6_monitor_run(
            status="RUNNING",
            started_at="",
            url="https://example.com/gta6",
        )


def test_create_gta6_monitor_run_rejects_invalid_url():
    with pytest.raises(
        ValueError,
        match="url must be a non-empty string",
    ):
        create_gta6_monitor_run(
            status="RUNNING",
            started_at="2026-09-04T20:12:00+00:00",
            url="",
        )


def test_create_gta6_monitor_run_rejects_negative_counters():
    with pytest.raises(
        ValueError,
        match="items_found must be greater than or equal to zero",
    ):
        create_gta6_monitor_run(
            status="RUNNING",
            started_at="2026-09-04T20:13:00+00:00",
            url="https://example.com/gta6",
            items_found=-1,
        )


def test_create_gta6_monitor_run_rejects_non_boolean_baseline():
    with pytest.raises(
        ValueError,
        match="baseline must be a boolean",
    ):
        create_gta6_monitor_run(
            status="RUNNING",
            started_at="2026-09-04T20:14:00+00:00",
            url="https://example.com/gta6",
            baseline=1,
        )


def test_update_gta6_monitor_run_rejects_unknown_id():
    with pytest.raises(
        ValueError,
        match="GTA6 monitor run 999999999 was not found",
    ):
        update_gta6_monitor_run(
            run_id=999999999,
            status="COMPLETED",
        )


def test_update_gta6_monitor_run_rejects_invalid_run_id():
    with pytest.raises(
        ValueError,
        match="run_id must be greater than zero",
    ):
        update_gta6_monitor_run(
            run_id=0,
            status="COMPLETED",
        )


def test_get_gta6_monitor_run_rejects_invalid_run_id():
    with pytest.raises(
        ValueError,
        match="run_id must be greater than zero",
    ):
        get_gta6_monitor_run(0)


def test_list_gta6_monitor_runs_rejects_invalid_status():
    with pytest.raises(
        ValueError,
        match="status must be one",
    ):
        list_gta6_monitor_runs(status="INVALID")


def test_list_gta6_monitor_runs_rejects_empty_url():
    with pytest.raises(
        ValueError,
        match="url must be a non-empty string",
    ):
        list_gta6_monitor_runs(url="")
