from uuid import UUID
from unittest.mock import patch

import pytest

from app.services.mpt_render_request_service import (
    build_mpt_render_request,
    build_mpt_task_id,
)


def _render_job(
    *,
    job_id: int = 123,
    script_id: int = 20,
    objective: str = "GTA 6 novidades",
    attempt: int = 1,
) -> dict:
    return {
        "id": job_id,
        "script_id": script_id,
        "objective": objective,
        "attempt": attempt,
    }


def test_build_mpt_task_id_is_deterministic():
    first = build_mpt_task_id(
        render_job_id=123,
        attempt=1,
    )

    second = build_mpt_task_id(
        render_job_id=123,
        attempt=1,
    )

    assert first == second
    assert UUID(first).version == 5


def test_build_mpt_task_id_changes_when_attempt_changes():
    attempt_one = build_mpt_task_id(
        render_job_id=123,
        attempt=1,
    )

    attempt_two = build_mpt_task_id(
        render_job_id=123,
        attempt=2,
    )

    assert attempt_one != attempt_two


def test_build_mpt_task_id_changes_when_render_job_changes():
    job_123 = build_mpt_task_id(
        render_job_id=123,
        attempt=1,
    )

    job_124 = build_mpt_task_id(
        render_job_id=124,
        attempt=1,
    )

    assert job_123 != job_124


@pytest.mark.parametrize(
    "render_job_id, attempt, expected_error",
    [
        (
            0,
            1,
            "O render_job_id precisa ser um inteiro positivo.",
        ),
        (
            123,
            0,
            "O attempt precisa ser um inteiro positivo.",
        ),
        (
            123,
            -1,
            "O attempt precisa ser um inteiro positivo.",
        ),
    ],
)
def test_build_mpt_task_id_rejects_invalid_identity(
    render_job_id,
    attempt,
    expected_error,
):
    with pytest.raises(ValueError, match=expected_error):
        build_mpt_task_id(
            render_job_id=render_job_id,
            attempt=attempt,
        )


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

    assert result["video_subject"] == "GTA 6 novidades"
    assert result["video_script"] == (
        "HOOK\nIntrodução\nDESENVOLVIMENTO\nCONCLUSÃO\nCTA"
    )

    assert result["task_id"] == build_mpt_task_id(
        render_job_id=123,
        attempt=1,
    )

    UUID(result["task_id"])

    get_script.assert_called_once_with(20)


def test_build_mpt_render_request_strips_subject_and_script():
    script = {
        "id": 20,
        "content": "  roteiro completo  ",
    }

    with patch(
        "app.services.mpt_render_request_service.get_script",
        return_value=script,
    ):
        result = build_mpt_render_request(
            _render_job(
                objective="  GTA 6  ",
            )
        )

    assert result["video_subject"] == "GTA 6"
    assert result["video_script"] == "roteiro completo"
    assert result["task_id"] == build_mpt_task_id(
        render_job_id=123,
        attempt=1,
    )


@pytest.mark.parametrize(
    "render_job, expected_error",
    [
        (
            {},
            "O render job informado é inválido.",
        ),
        (
            {
                "id": 0,
                "script_id": 20,
                "objective": "GTA 6",
                "attempt": 1,
            },
            "O render job precisa possuir um id persistido válido.",
        ),
        (
            {
                "id": 123,
                "script_id": 0,
                "objective": "GTA 6",
                "attempt": 1,
            },
            "O render job precisa possuir um script_id persistido válido.",
        ),
        (
            {
                "id": 123,
                "script_id": 20,
                "objective": "",
                "attempt": 1,
            },
            "O render job precisa possuir um objective utilizável.",
        ),
        (
            {
                "id": 123,
                "script_id": 20,
                "objective": "GTA 6",
                "attempt": 0,
            },
            "O render job precisa possuir um attempt positivo válido.",
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
