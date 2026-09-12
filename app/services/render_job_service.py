from typing import Any
from copy import deepcopy

def create_render_job(
    video_execution_spec: dict[str, Any],
    *,
    video_id: int | None = None,
) -> dict[str, Any]:
    """
    Transforma uma Video Execution Spec em uma tarefa concreta
    de renderização e persiste essa tarefa na fila.

    Esta camada não executa o render.
    Ela prepara e persiste uma unidade de trabalho que poderá
    ser consumida futuramente por um executor de vídeo.
    """

    if video_id is not None and (
        not isinstance(video_id, int) or video_id <= 0
    ):
        raise ValueError("video_id must be a positive integer.")

    if (
        not isinstance(video_execution_spec, dict)
        or not video_execution_spec
    ):
        raise ValueError(
            "O video execution spec informado é inválido."
        )

    required_fields = [
        "content_item_id",
        "script_id",
        "idea_id",
        "objective",
        "format",
        "estimated_duration_seconds",
        "scenes",
        "audio_requirements",
        "visual_requirements",
        "render",
    ]

    for field in required_fields:
        if field not in video_execution_spec:
            raise ValueError(
                "O video execution spec não possui "
                f"o campo obrigatório: {field}."
            )

    scenes = video_execution_spec.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise ValueError(
            "O video execution spec precisa possuir cenas."
        )

    execution_scenes = []

    required_scene_fields = [
        "order",
        "narrative_block",
        "narration",
        "visual_type",
        "visual_description",
        "duration_seconds",
        "execution_requirements",
    ]

    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError(
                "Cada cena do video execution spec "
                "deve ser um objeto válido."
            )

        for field in required_scene_fields:
            if field not in scene:
                raise ValueError(
                    f"A cena não possui o campo obrigatório: {field}."
                )

        execution_scene = {
            "order": scene["order"],
            "narrative_block": scene["narrative_block"],
            "narration": scene["narration"],
            "visual_type": scene["visual_type"],
            "visual_description": scene["visual_description"],
            "duration_seconds": scene["duration_seconds"],
            "execution_requirements": list(
                scene.get("execution_requirements") or []
            ),
        }

        for field in (
            "segment_id",
            "content_unit_id",
            "file_path",
            "source_start_seconds",
            "source_end_seconds",
            "role",
            "media_path",
            "transcript_words",
        ):
            if field in scene:
                execution_scene[field] = deepcopy(scene[field])

        execution_scenes.append(execution_scene)

    render = video_execution_spec.get("render")

    if not isinstance(render, dict) or not render:
        raise ValueError(
            "O video execution spec precisa possuir "
            "uma configuração de renderização válida."
        )

    required_render_fields = [
        "resolution",
        "fps",
        "aspect_ratio",
        "container",
        "video_codec",
        "audio_codec",
    ]

    for field in required_render_fields:
        if field not in render:
            raise ValueError(
                "A configuração de renderização não possui "
                f"o campo obrigatório: {field}."
            )


    render_job = {
        "content_item_id": video_execution_spec["content_item_id"],
        "script_id": video_execution_spec["script_id"],
        "idea_id": video_execution_spec["idea_id"],
        "objective": video_execution_spec["objective"],
        "format": video_execution_spec["format"],
        "estimated_duration_seconds": (
            video_execution_spec["estimated_duration_seconds"]
        ),
        "status": "queued",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
        "scenes": execution_scenes,
        "audio_requirements": list(
            video_execution_spec.get("audio_requirements") or []
        ),
        "visual_requirements": list(
            video_execution_spec.get("visual_requirements") or []
        ),
        "render": dict(render),
    }

    # Contexto de autorização/correlação do BR.
    # Deve atravessar Video Execution Spec -> Render Job.
    for field in (
        "brain_decision_id",
        "execution_id",
        "authorized_action",
    ):
        if field in video_execution_spec:
            render_job[field] = video_execution_spec[field]

    if video_id is not None:
        render_job["video_id"] = video_id

    if "edit_plan" in video_execution_spec:
        render_job["edit_plan"] = deepcopy(video_execution_spec["edit_plan"])
    return render_job
