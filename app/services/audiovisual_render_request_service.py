from __future__ import annotations

import json
import re
from typing import Any


REQUIRED_AUTHORIZATION_FIELDS = (
    "brain_decision_id",
    "execution_id",
    "authorized_action",
)

# These are Harness provenance identifiers, not credentials. They remain in the
# canonical persisted RenderJob, but are intentionally omitted from the cloud
# worker payload because the worker only needs the bounded execution envelope
# above and rejects credential-shaped fields before archiving inputs.
WORKER_REDACTED_GOVERNANCE_FIELDS = {
    "authorization_id",
    "authorization_subject",
    "parent_authorization_id",
}

_CREDENTIAL_KEY_PATTERN = re.compile(
    r"token|password|secret|api[_-]?key|authorization",
    re.I,
)


def _worker_safe_value(value: Any) -> Any:
    """Return a worker payload that minimizes authority metadata and rejects secrets."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if key_text in WORKER_REDACTED_GOVERNANCE_FIELDS:
                continue
            if _CREDENTIAL_KEY_PATTERN.search(key_text):
                raise ValueError("Credential-bearing fields do not belong in RenderJob dispatch")
            result[key_text] = _worker_safe_value(child)
        return result
    if isinstance(value, list):
        return [_worker_safe_value(item) for item in value]
    return value


def build_worker_safe_render_job(render_job: dict[str, Any]) -> dict[str, Any]:
    """Strip governance-only identifiers and reject credentials before worker transport."""
    if not isinstance(render_job, dict) or not render_job:
        raise ValueError("Render Job inválido.")
    safe = _worker_safe_value(render_job)
    if not isinstance(safe, dict):
        raise ValueError("Render Job worker payload must remain an object.")
    return safe


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

    worker_job = build_worker_safe_render_job(render_job)
    return {
        "render_job": json.dumps(
            worker_job,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "brain_decision_id": str(render_job["brain_decision_id"]),
        "execution_id": str(render_job["execution_id"]),
        "authorized_action": str(render_job["authorized_action"]),
    }
