from app.database.queue_repository import (
    get_active_queue_item_by_idea,
    get_queue_item,
    insert_queue_item,
    list_active_queue_items,
    list_queue_items,
    mark_queue_item_completed,
    update_queue_priority,
    update_queue_status,
)


def test_insert_and_get_queue_item():
    queue_id = insert_queue_item(
        idea_id=1,
        priority_score=9.6,
        priority="high",
    )

    item = get_queue_item(queue_id)

    assert item is not None
    assert item["id"] == queue_id
    assert item["idea_id"] == 1
    assert item["priority_score"] == 9.6
    assert item["priority"] == "high"
    assert item["status"] == "queued"
    assert item["completed_at"] is None


def test_list_queue_items_orders_by_priority():
    low_id = insert_queue_item(
        idea_id=2,
        priority_score=3.6,
        priority="low",
    )
    high_id = insert_queue_item(
        idea_id=3,
        priority_score=9.6,
        priority="high",
    )
    medium_id = insert_queue_item(
        idea_id=4,
        priority_score=6.5,
        priority="medium",
    )

    items = list_queue_items()
    ids = [item["id"] for item in items]

    assert ids[:3] == [high_id, medium_id, low_id]


def test_active_queue_item_by_idea():
    queue_id = insert_queue_item(
        idea_id=5,
        priority_score=8.0,
        priority="high",
        status="scheduled",
    )

    item = get_active_queue_item_by_idea(5)

    assert item is not None
    assert item["id"] == queue_id
    assert item["status"] == "scheduled"


def test_list_active_queue_items_excludes_completed():
    active_id = insert_queue_item(
        idea_id=6,
        priority_score=8.5,
        priority="high",
        status="processing",
    )
    completed_id = insert_queue_item(
        idea_id=7,
        priority_score=9.0,
        priority="high",
        status="completed",
    )

    items = list_active_queue_items()
    ids = [item["id"] for item in items]

    assert active_id in ids
    assert completed_id not in ids


def test_update_queue_status():
    queue_id = insert_queue_item(
        idea_id=8,
        priority_score=7.0,
        priority="medium",
    )

    assert update_queue_status(queue_id, "processing") is True

    item = get_queue_item(queue_id)

    assert item is not None
    assert item["status"] == "processing"


def test_update_queue_priority():
    queue_id = insert_queue_item(
        idea_id=9,
        priority_score=5.0,
        priority="low",
    )

    assert update_queue_priority(
        queue_id,
        priority_score=8.8,
        priority="high",
    ) is True

    item = get_queue_item(queue_id)

    assert item is not None
    assert item["priority_score"] == 8.8
    assert item["priority"] == "high"


def test_mark_queue_item_completed():
    queue_id = insert_queue_item(
        idea_id=10,
        priority_score=7.5,
        priority="medium",
    )

    assert mark_queue_item_completed(queue_id) is True

    item = get_queue_item(queue_id)

    assert item is not None
    assert item["status"] == "completed"
    assert item["completed_at"] is not None


def test_update_nonexistent_queue_item_returns_false():
    assert update_queue_status(999999, "processing") is False
    assert update_queue_priority(999999, 8.0, "high") is False
    assert mark_queue_item_completed(999999) is False
