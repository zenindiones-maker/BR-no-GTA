import sqlite3

import pytest

from app.database.production_plan_repository import (
    get_production_plan_by_content_item_id,
    insert_production_plan,
)


def test_insert_and_get_production_plan(test_database):
    from app.database.content_repository import insert_content_item

    content_item_id = insert_content_item(
        title="Plano GTA6",
        content_type="YouTube editorial",
        status="ready",
    )

    production_plan = {
        "content_item_id": content_item_id,
        "script_id": 10,
        "idea_id": 20,
        "objective": "Informar sobre GTA6.",
        "format": "YouTube editorial",
        "estimated_duration_seconds": 120,
        "scenes": [
            {
                "order": 1,
                "narrative_block": "HOOK",
                "narration": "Abertura.",
                "visual_type": "gameplay",
                "visual_description": "Gameplay de GTA6.",
                "duration_seconds": 8,
                "requirements": [],
            }
        ],
        "audio_requirements": [],
        "visual_requirements": [],
        "status": "ready",
    }

    production_plan_id = insert_production_plan(
        content_item_id=content_item_id,
        production_plan=production_plan,
    )

    result = get_production_plan_by_content_item_id(content_item_id)

    assert production_plan_id > 0
    assert result is not None
    assert result["id"] == production_plan_id
    assert result["content_item_id"] == content_item_id
    assert result["status"] == "ready"
    assert result["production_plan"]["content_item_id"] == content_item_id
    assert result["production_plan"]["script_id"] == 10
    assert result["production_plan"]["idea_id"] == 20
    assert result["production_plan"]["scenes"] == production_plan["scenes"]


def test_get_production_plan_returns_none_when_missing(test_database):
    assert get_production_plan_by_content_item_id(999999) is None


def test_insert_production_plan_rejects_duplicate_content_item(test_database):
    from app.database.content_repository import insert_content_item

    content_item_id = insert_content_item(
        title="Plano duplicado",
        content_type="YouTube editorial",
        status="ready",
    )

    production_plan = {
        "content_item_id": content_item_id,
        "status": "ready",
    }

    insert_production_plan(
        content_item_id=content_item_id,
        production_plan=production_plan,
    )

    with pytest.raises(sqlite3.IntegrityError):
        insert_production_plan(
            content_item_id=content_item_id,
            production_plan=production_plan,
        )


@pytest.mark.parametrize(
    "content_item_id, production_plan",
    [
        (0, {"status": "ready"}),
        (-1, {"status": "ready"}),
        (1, {}),
        (1, None),
    ],
)
def test_insert_production_plan_rejects_invalid_input(
    test_database,
    content_item_id,
    production_plan,
):
    with pytest.raises(ValueError):
        insert_production_plan(
            content_item_id=content_item_id,
            production_plan=production_plan,
        )
