import pytest

from app.database.gta6_monitor_run_repository import (
    get_gta6_monitor_run,
)
from app.services.gta6_monitor_run_lifecycle_service import (
    GTA6_MONITOR_RUN_COMPLETED,
    GTA6_MONITOR_RUN_ERROR,
    GTA6_MONITOR_RUN_RUNNING,
    complete_gta6_monitor_run,
    fail_gta6_monitor_run,
    start_gta6_monitor_run,
)


def test_start_creates_running_run():
    result = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    assert result["id"] > 0
    assert result["status"] == GTA6_MONITOR_RUN_RUNNING
    assert result["url"] == "https://example.com/news"
    assert result["started_at"]
    assert result["finished_at"] is None
    assert result["error"] is None


def test_start_strips_url():
    result = start_gta6_monitor_run(
        url="  https://example.com/news  ",
    )

    assert result["url"] == "https://example.com/news"


def test_start_rejects_empty_url():
    with pytest.raises(
        ValueError,
        match="url must be a non-empty string",
    ):
        start_gta6_monitor_run(url="")


def test_start_rejects_non_string_url():
    with pytest.raises(
        ValueError,
        match="url must be a non-empty string",
    ):
        start_gta6_monitor_run(url=123)


def test_complete_transitions_running_to_completed():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    result = complete_gta6_monitor_run(
        run_id=started["id"],
        status_code=200,
        baseline=False,
        items_found=10,
        items_ingested=8,
        items_duplicated=2,
    )

    assert result["id"] == started["id"]
    assert result["status"] == GTA6_MONITOR_RUN_COMPLETED
    assert result["finished_at"]
    assert result["status_code"] == 200
    assert result["baseline"] is False
    assert result["items_found"] == 10
    assert result["items_ingested"] == 8
    assert result["items_duplicated"] == 2
    assert result["error"] is None


def test_complete_persists_completed_state():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    complete_gta6_monitor_run(
        run_id=started["id"],
        status_code=200,
        baseline=True,
        items_found=5,
        items_ingested=5,
        items_duplicated=0,
    )

    stored = get_gta6_monitor_run(started["id"])

    assert stored is not None
    assert stored["status"] == GTA6_MONITOR_RUN_COMPLETED
    assert stored["baseline"] is True
    assert stored["items_found"] == 5
    assert stored["items_ingested"] == 5
    assert stored["items_duplicated"] == 0


def test_fail_transitions_running_to_error():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    result = fail_gta6_monitor_run(
        run_id=started["id"],
        error="Connection timeout",
    )

    assert result["id"] == started["id"]
    assert result["status"] == GTA6_MONITOR_RUN_ERROR
    assert result["finished_at"]
    assert result["error"] == "Connection timeout"
    assert result["status_code"] is None


def test_fail_persists_error_state():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    fail_gta6_monitor_run(
        run_id=started["id"],
        error="HTTP failure",
        status_code=503,
    )

    stored = get_gta6_monitor_run(started["id"])

    assert stored is not None
    assert stored["status"] == GTA6_MONITOR_RUN_ERROR
    assert stored["status_code"] == 503
    assert stored["error"] == "HTTP failure"


def test_complete_rejects_already_completed_run():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    complete_gta6_monitor_run(
        run_id=started["id"],
        status_code=200,
        baseline=False,
        items_found=0,
        items_ingested=0,
        items_duplicated=0,
    )

    with pytest.raises(
        ValueError,
        match="Only RUNNING GTA6 monitor runs can be finalized",
    ):
        complete_gta6_monitor_run(
            run_id=started["id"],
            status_code=200,
            baseline=False,
            items_found=0,
            items_ingested=0,
            items_duplicated=0,
        )


def test_fail_rejects_already_completed_run():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    complete_gta6_monitor_run(
        run_id=started["id"],
        status_code=200,
        baseline=False,
        items_found=0,
        items_ingested=0,
        items_duplicated=0,
    )

    with pytest.raises(
        ValueError,
        match="Only RUNNING GTA6 monitor runs can be finalized",
    ):
        fail_gta6_monitor_run(
            run_id=started["id"],
            error="late failure",
        )


def test_complete_rejects_already_failed_run():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    fail_gta6_monitor_run(
        run_id=started["id"],
        error="first failure",
    )

    with pytest.raises(
        ValueError,
        match="Only RUNNING GTA6 monitor runs can be finalized",
    ):
        complete_gta6_monitor_run(
            run_id=started["id"],
            status_code=200,
            baseline=False,
            items_found=0,
            items_ingested=0,
            items_duplicated=0,
        )


def test_fail_rejects_already_failed_run():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    fail_gta6_monitor_run(
        run_id=started["id"],
        error="first failure",
    )

    with pytest.raises(
        ValueError,
        match="Only RUNNING GTA6 monitor runs can be finalized",
    ):
        fail_gta6_monitor_run(
            run_id=started["id"],
            error="second failure",
        )


def test_complete_rejects_unknown_run():
    with pytest.raises(
        ValueError,
        match="GTA6 monitor run 999999 was not found",
    ):
        complete_gta6_monitor_run(
            run_id=999999,
            status_code=200,
            baseline=False,
            items_found=0,
            items_ingested=0,
            items_duplicated=0,
        )


def test_fail_rejects_unknown_run():
    with pytest.raises(
        ValueError,
        match="GTA6 monitor run 999999 was not found",
    ):
        fail_gta6_monitor_run(
            run_id=999999,
            error="failure",
        )


@pytest.mark.parametrize(
    "field_name, value",
    [
        ("items_found", -1),
        ("items_ingested", -1),
        ("items_duplicated", -1),
    ],
)
def test_complete_rejects_negative_counters(
    field_name,
    value,
):
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    kwargs = {
        "run_id": started["id"],
        "status_code": 200,
        "baseline": False,
        "items_found": 0,
        "items_ingested": 0,
        "items_duplicated": 0,
    }
    kwargs[field_name] = value

    with pytest.raises(
        ValueError,
        match=f"{field_name} must be greater than or equal to zero",
    ):
        complete_gta6_monitor_run(**kwargs)


def test_complete_rejects_boolean_status_code():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    with pytest.raises(
        ValueError,
        match="status_code must be an integer",
    ):
        complete_gta6_monitor_run(
            run_id=started["id"],
            status_code=True,
            baseline=False,
            items_found=0,
            items_ingested=0,
            items_duplicated=0,
        )


def test_complete_rejects_non_boolean_baseline():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    with pytest.raises(
        ValueError,
        match="baseline must be a boolean",
    ):
        complete_gta6_monitor_run(
            run_id=started["id"],
            status_code=200,
            baseline="false",
            items_found=0,
            items_ingested=0,
            items_duplicated=0,
        )


def test_fail_rejects_empty_error():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    with pytest.raises(
        ValueError,
        match="error must be a non-empty string",
    ):
        fail_gta6_monitor_run(
            run_id=started["id"],
            error="",
        )


def test_fail_strips_error():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    result = fail_gta6_monitor_run(
        run_id=started["id"],
        error="  Connection timeout  ",
    )

    assert result["error"] == "Connection timeout"


def test_fail_rejects_boolean_status_code():
    started = start_gta6_monitor_run(
        url="https://example.com/news",
    )

    with pytest.raises(
        ValueError,
        match="status_code must be an integer or None",
    ):
        fail_gta6_monitor_run(
            run_id=started["id"],
            error="HTTP failure",
            status_code=True,
        )
