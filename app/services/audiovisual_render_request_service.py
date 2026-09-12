from __future__ import annotations

import json
from typing import Any


REQUIRED_AUTHORIZATION_FIELDS = (
    "brain_decision_id",
    "execution_id",
    "authorized_action",
)


def build_audiovisual_render_request(
    render_job: dict[str, Any],
) -> dict[str, str]:
    if not isinstance(render_job, dict) or not render_job:
        raise ValueError("Render Job inválido.")

    for field in REQUIRED_AUTHORIZATION_FIELDS:
        value = str(render_job.get(field) or "").strip()
        if not value:
            raise ValueError(
                f"Render Job não possui autorização obrigatória: {field}."
            )

    if render_job["authorized_action"] != "EXECUTION":
        raise ValueError(
            "Render Job audiovisual exige authorized_action='EXECUTION'."
        )

    scenes = render_job.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("Render Job precisa possuir cenas.")

    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("Cada cena do Render Job deve ser um objeto.")

        for field in (
            "order",
            "duration_seconds",
            "segment_id",
            "content_unit_id",
            "source_start_seconds",
            "source_end_seconds",
        ):
            if field not in scene:
                raise ValueError(
                    f"Cena do Render Job não possui o campo obrigatório: {field}."
                )

    render_job = dict(render_job)
    if "render_job_id" not in render_job:
        render_job["render_job_id"] = render_job.get("id")
    if type(render_job.get("render_job_id")) is not int or render_job["render_job_id"] <= 0:
        raise ValueError("Persisted render_job_id is required")
    return {
        "render_job": json.dumps(
            render_job,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "brain_decision_id": str(render_job["brain_decision_id"]),
        "execution_id": str(render_job["execution_id"]),
        "authorized_action": str(render_job["authorized_action"]),
    }
