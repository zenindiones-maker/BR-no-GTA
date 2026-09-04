from unittest.mock import patch

import pytest

from app.services.mpt_render_request_service import (
    build_mpt_render_request,
)


def _render_job(
    *,
    job_id: int = 123,
    script_id: int = 20,
    objective: str = "GTA 6 novidades",
) -> dict:
    return {
        "id": job_id,
        "script_id": script_id,
        "objective": objective,
    }


def test_build_mpt_render_request_maps_render_job_contract():
    script = {
        "id": 20,
        "title": "GTA 6 novidades",
        "content": "HOOK\nIntrodução\nDESENVOLVIMENTO\nCONCLUSÃO\nCTA",
        "status": "draft",
    }

    with patch(
        "app.services.mpt_render_request_service.get_script",
        return_value=script,
    ) as get_script:
        result = build_mpt_render_request(
            _render_job()
        )

    assert result == {
        "video_subject": "GTA 6 novidades",
        "video_script": (
            "HOOK\nIntrodução\nDESENVOLVIMENTO\nCONCLUSÃO\nCTA"
        ),
        "task_id": "123",
    }

    get_script.assert_called_once_with(20)


def test_build_mpt_render_request_strips_subject_and_script():
    script = {
        "id": 20,
        "content": "  roteiro completo  ",
    }

    result = None

    with patch(
        "app.services.mpt_render_request_service.get_script",
        return_value=script,
    ):
        result = build_mpt_render_request(
            _render_job(
                objective="  GTA 6  "
            )
        )

    assert result == {
        "video_subject": "GTA 6",
        "video_script": "roteiro completo",
        "task_id": "123",
    }


@pytest.mark.parametrize(
    "render_job, expected_error",
    [
        (
            {},
            "O render job informado é inválido.",
        ),
        (
            {"id": 0, "script_id": 20, "objective": "GTA 6"},
            "O render job precisa possuir um id persistido válido.",
        ),
        (
            {"id": 123, "script_id": 0, "objective": "GTA 6"},
            "O render job precisa possuir um script_id persistido válido.",
        ),
        (
            {"id": 123, "script_id": 20, "objective": ""},
            "O render job precisa possuir um objective utilizável.",
        ),
    ],
)
def test_build_mpt_render_request_rejects_invalid_render_job(
    render_job,
    expected_error,
):
    with pytest.raises(ValueError, match=expected_error):
        build_mpt_render_request(render_job)


def test_build_mpt_render_request_rejects_missing_script():
    with patch(
        "app.services.mpt_render_request_service.get_script",
        return_value=None,
    ):
        with pytest.raises(
            ValueError,
            match="Script não encontrado para script_id=20.",
        ):
            build_mpt_render_request(
                _render_job()
            )


def test_build_mpt_render_request_rejects_empty_script():
    script = {
        "id": 20,
        "content": "   ",
    }

    with patch(
        "app.services.mpt_render_request_service.get_script",
        return_value=script,
    ):
        with pytest.raises(
            ValueError,
            match="O script 20 não possui conteúdo utilizável.",
        ):
            build_mpt_render_request(
                _render_job()
            )
