import pytest

from app.services.content_unit_service import (
    CONTENT_UNIT_TYPES,
    ContentUnitError,
    create_content_unit,
    create_content_unit_from_content_item,
    validate_content_unit,
)


BASE_KWARGS = {
    "title": "GTA 6 recebeu uma nova informação",
    "unit_type": "short",
    "duration_seconds": 60,
    "media_format": "9:16",
    "script_id": 10,
    "idea_id": 20,
    "objective": "Informar rapidamente a audiência",
    "hook": "Essa informação pode mudar o que sabemos sobre GTA 6.",
    "narration": "Texto narrado sobre a informação.",
    "visual_requirements": [
        {
            "type": "gameplay",
            "description": "Gameplay relacionado ao assunto.",
        }
    ],
}


def test_create_short_content_unit():
    unit = create_content_unit(**BASE_KWARGS)

    assert unit["title"] == BASE_KWARGS["title"]
    assert unit["unit_type"] == "short"
    assert unit["duration_seconds"] == 60.0
    assert unit["media_format"] == "9:16"
    assert unit["script_id"] == 10
    assert unit["idea_id"] == 20
    assert unit["status"] == "ready"


@pytest.mark.parametrize(
    ("unit_type", "media_format"),
    [
        ("short", "9:16"),
        ("reel", "9:16"),
        ("segment", "16:9"),
        ("segment", "9:16"),
    ],
)
def test_supported_content_unit_combinations(
    unit_type,
    media_format,
):
    kwargs = {
        **BASE_KWARGS,
        "unit_type": unit_type,
        "media_format": media_format,
    }

    unit = create_content_unit(**kwargs)

    assert unit["unit_type"] == unit_type
    assert unit["media_format"] == media_format


def test_supported_content_unit_types_are_explicit():
    assert CONTENT_UNIT_TYPES == {
        "short",
        "reel",
        "segment",
    }


@pytest.mark.parametrize(
    "unit_type",
    [
        "video",
        "long",
        "episode",
        "youtube",
        "",
    ],
)
def test_invalid_content_unit_type_is_rejected(unit_type):
    kwargs = {
        **BASE_KWARGS,
        "unit_type": unit_type,
    }

    with pytest.raises(ContentUnitError):
        create_content_unit(**kwargs)


@pytest.mark.parametrize(
    "duration",
    [
        0,
        -1,
        -10.5,
    ],
)
def test_invalid_duration_is_rejected(duration):
    kwargs = {
        **BASE_KWARGS,
        "duration_seconds": duration,
    }

    with pytest.raises(ContentUnitError):
        create_content_unit(**kwargs)


def test_invalid_media_format_is_rejected():
    kwargs = {
        **BASE_KWARGS,
        "media_format": "4:3",
    }

    with pytest.raises(ContentUnitError):
        create_content_unit(**kwargs)


def test_invalid_script_id_is_rejected():
    kwargs = {
        **BASE_KWARGS,
        "script_id": 0,
    }

    with pytest.raises(ContentUnitError):
        create_content_unit(**kwargs)


def test_invalid_idea_id_is_rejected():
    kwargs = {
        **BASE_KWARGS,
        "idea_id": 0,
    }

    with pytest.raises(ContentUnitError):
        create_content_unit(**kwargs)


def test_empty_title_is_rejected():
    kwargs = {
        **BASE_KWARGS,
        "title": "   ",
    }

    with pytest.raises(ContentUnitError):
        create_content_unit(**kwargs)


def test_visual_requirements_default_to_empty_list():
    kwargs = {
        **BASE_KWARGS,
        "visual_requirements": None,
    }

    unit = create_content_unit(**kwargs)

    assert unit["visual_requirements"] == []


def test_content_item_can_be_converted_to_content_unit():
    content_item = {
        "title": "GTA 6: nova informação",
        "script_id": 101,
        "idea_id": 202,
        "objective": "Informar",
        "hook": "Você precisa saber disso.",
        "description": "Narração da unidade.",
        "estimated_duration_seconds": 75,
        "visual_requirements": [
            {
                "type": "gameplay",
                "description": "Gameplay GTA 6",
            }
        ],
    }

    unit = create_content_unit_from_content_item(
        content_item,
        unit_type="short",
        media_format="9:16",
    )

    assert unit["title"] == "GTA 6: nova informação"
    assert unit["script_id"] == 101
    assert unit["idea_id"] == 202
    assert unit["duration_seconds"] == 75.0
    assert unit["unit_type"] == "short"
    assert unit["media_format"] == "9:16"


def test_content_item_conversion_can_override_duration():
    content_item = {
        "title": "GTA 6",
        "script_id": 1,
        "idea_id": 2,
        "objective": "Informar",
        "hook": "Novo detalhe.",
        "description": "Narração.",
        "estimated_duration_seconds": 180,
        "visual_requirements": [],
    }

    unit = create_content_unit_from_content_item(
        content_item,
        unit_type="segment",
        media_format="16:9",
        duration_seconds=90,
    )

    assert unit["duration_seconds"] == 90.0
    assert unit["unit_type"] == "segment"
    assert unit["media_format"] == "16:9"


def test_content_item_without_duration_is_rejected():
    content_item = {
        "title": "GTA 6",
        "script_id": 1,
        "idea_id": 2,
        "objective": "Informar",
        "hook": "Novo detalhe.",
        "description": "Narração.",
        "visual_requirements": [],
    }

    with pytest.raises(ContentUnitError):
        create_content_unit_from_content_item(
            content_item,
            unit_type="short",
            media_format="9:16",
        )


def test_validate_content_unit_accepts_valid_unit():
    unit = create_content_unit(**BASE_KWARGS)

    assert validate_content_unit(unit) is None


def test_validate_content_unit_rejects_missing_field():
    unit = create_content_unit(**BASE_KWARGS)
    del unit["hook"]

    with pytest.raises(ContentUnitError):
        validate_content_unit(unit)


def test_content_unit_normalizes_text_fields():
    kwargs = {
        **BASE_KWARGS,
        "title": "  GTA 6  ",
        "unit_type": " SHORT ",
        "objective": "  Informar  ",
        "hook": "  Novo hook.  ",
        "narration": "  Narração.  ",
    }

    unit = create_content_unit(**kwargs)

    assert unit["title"] == "GTA 6"
    assert unit["unit_type"] == "short"
    assert unit["objective"] == "Informar"
    assert unit["hook"] == "Novo hook."
    assert unit["narration"] == "Narração."


def test_content_unit_does_not_require_database():
    unit = create_content_unit(**BASE_KWARGS)

    assert unit["script_id"] == 10
    assert unit["idea_id"] == 20
