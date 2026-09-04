from pathlib import Path

import pytest

from app.services.money_printer_turbo_input import (
    create_money_printer_turbo_input_package,
)


def _render_job() -> dict:
    return {
        "content_item_id": 10,
        "script_id": 20,
        "idea_id": 30,
        "objective": "Explicar uma novidade do GTA 6",
        "format": "youtube",
        "estimated_duration_seconds": 60,
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Introdução",
                "narration": "O GTA 6 pode trazer uma grande novidade.",
                "visual_type": "gameplay",
                "visual_description": "Gameplay de GTA 6.",
                "duration_seconds": 10,
                "execution_requirements": [
                    "usar material horizontal",
                ],
            },
            {
                "order": 2,
                "narrative_block": "Desenvolvimento",
                "narration": "A informação chamou atenção da comunidade.",
                "visual_type": "news",
                "visual_description": "Imagens relacionadas à notícia.",
                "duration_seconds": 15,
                "execution_requirements": [],
            },
        ],
        "audio_requirements": [
            "narração em português brasileiro",
        ],
        "visual_requirements": [
            "16:9",
            "1920x1080",
        ],
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
    }


def test_creates_expected_input_package(tmp_path: Path):
    package = create_money_printer_turbo_input_package(
        _render_job(),
        tmp_path / "input",
    )

    assert package.directory == tmp_path / "input"

    assert package.job_file == (
        tmp_path / "input" / "job.json"
    )
    assert package.script_file == (
        tmp_path / "input" / "script.txt"
    )
    assert package.scenes_file == (
        tmp_path / "input" / "scenes.json"
    )

    assert package.job_file.is_file()
    assert package.script_file.is_file()
    assert package.scenes_file.is_file()


def test_script_contains_scene_narrations_in_order(
    tmp_path: Path,
):
    package = create_money_printer_turbo_input_package(
        _render_job(),
        tmp_path / "input",
    )

    script = package.script_file.read_text(
        encoding="utf-8"
    )

    assert (
        script
        == "O GTA 6 pode trazer uma grande novidade.\n\n"
        "A informação chamou atenção da comunidade.\n"
    )


def test_scenes_preserve_execution_information(
    tmp_path: Path,
):
    package = create_money_printer_turbo_input_package(
        _render_job(),
        tmp_path / "input",
    )

    import json

    scenes = json.loads(
        package.scenes_file.read_text(
            encoding="utf-8"
        )
    )

    assert len(scenes) == 2

    assert scenes[0]["order"] == 1
    assert scenes[0]["visual_type"] == "gameplay"
    assert scenes[0]["execution_requirements"] == [
        "usar material horizontal"
    ]

    assert scenes[1]["order"] == 2


def test_job_metadata_does_not_expose_entire_render_job(
    tmp_path: Path,
):
    package = create_money_printer_turbo_input_package(
        _render_job(),
        tmp_path / "input",
    )

    import json

    job = json.loads(
        package.job_file.read_text(
            encoding="utf-8"
        )
    )

    assert job["content_item_id"] == 10
    assert job["script_id"] == 20
    assert job["idea_id"] == 30
    assert job["objective"] == (
        "Explicar uma novidade do GTA 6"
    )

    assert "scenes" not in job
    assert "job_type" not in job
    assert "queue" not in job
    assert "attempt" not in job
    assert "status" not in job


def test_rejects_invalid_render_job(
    tmp_path: Path,
):
    with pytest.raises(
        ValueError,
        match="render job informado é inválido",
    ):
        create_money_printer_turbo_input_package(
            {},
            tmp_path / "input",
        )


def test_rejects_missing_required_field(
    tmp_path: Path,
    ):
    render_job = _render_job()
    del render_job["objective"]

    with pytest.raises(
        ValueError,
        match="objective",
    ):
        create_money_printer_turbo_input_package(
            render_job,
            tmp_path / "input",
        )


def test_rejects_empty_narration(
    tmp_path: Path,
):
    render_job = _render_job()

    for scene in render_job["scenes"]:
        scene["narration"] = ""

    with pytest.raises(
        ValueError,
        match="narração utilizável",
    ):
        create_money_printer_turbo_input_package(
            render_job,
            tmp_path / "input",
        )


def test_rejects_invalid_scene(
    tmp_path: Path,
):
    render_job = _render_job()
    render_job["scenes"] = [{}]

    with pytest.raises(
        ValueError,
        match="campo obrigatório",
    ):
        create_money_printer_turbo_input_package(
            render_job,
            tmp_path / "input",
        )
