from typing import Any


def create_video_execution_spec(
    video_spec: dict[str, Any],
) -> dict[str, Any]:
    """
    Transforma uma Video Spec em uma especificação pronta para execução.

    Esta camada não executa nem renderiza o vídeo.
    Ela define os parâmetros necessários para uma futura etapa
    de renderização/execução.
    """

    if not isinstance(video_spec, dict) or not video_spec:
        raise ValueError("O video spec informado é inválido.")

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
    ]

    for field in required_fields:
        if field not in video_spec:
            raise ValueError(
                f"O video spec não possui o campo obrigatório: {field}."
            )

    scenes = video_spec.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise ValueError(
            "O video spec precisa possuir cenas."
        )

    execution_scenes = []

    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError(
                "Cada cena do video spec deve ser um objeto válido."
            )

        required_scene_fields = [
            "order",
            "narrative_block",
            "narration",
            "visual_type",
            "visual_description",
            "duration_seconds",
            "requirements",
        ]

        for field in required_scene_fields:
            if field not in scene:
                raise ValueError(
                    f"A cena não possui o campo obrigatório: {field}."
                )

        execution_scenes.append(
            {
                "order": scene["order"],
                "narrative_block": scene["narrative_block"],
                "narration": scene["narration"],
                "visual_type": scene["visual_type"],
                "visual_description": scene["visual_description"],
                "duration_seconds": scene["duration_seconds"],
                "execution_requirements": list(
                    scene.get("requirements") or []
                ),
            }
        )

    return {
        "content_item_id": video_spec["content_item_id"],
        "script_id": video_spec["script_id"],
        "idea_id": video_spec["idea_id"],
        "objective": video_spec["objective"],
        "format": video_spec["format"],
        "estimated_duration_seconds": (
            video_spec["estimated_duration_seconds"]
        ),
        "status": "ready",
        "scenes": execution_scenes,
        "audio_requirements": list(
            video_spec.get("audio_requirements") or []
        ),
        "visual_requirements": list(
            video_spec.get("visual_requirements") or []
        ),
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
    }
