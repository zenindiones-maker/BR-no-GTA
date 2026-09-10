from typing import Any


def create_production_plan(
    content_item: dict[str, Any],
) -> dict[str, Any]:
    """
    Transforma um content item em um plano estruturado de produção.

    Esta camada não gera vídeo.
    Ela define como o conteúdo deverá ser produzido.
    """

    if not isinstance(content_item, dict) or not content_item:
        raise ValueError("O content item informado é inválido.")

    required_fields = [
        "script_id",
        "idea_id",
        "objective",
        "format",
        "estimated_duration_seconds",
        "narrative_blocks",
        "visual_requirements",
    ]

    for field in required_fields:
        if field not in content_item:
            raise ValueError(
                f"O content item não possui o campo obrigatório: {field}."
            )

    narrative_blocks = content_item.get("narrative_blocks")

    if not isinstance(narrative_blocks, list) or not narrative_blocks:
        raise ValueError(
            "O content item precisa possuir blocos narrativos."
        )

    # Uma execução de produção gera um único master de 50 minutos.
    # A divisão em duas publicações de 25 minutos acontece depois,
    # na camada de publicação, sem duplicar a renderização.
    production_duration_seconds = 50 * 60

    valid_blocks = [
        block
        for block in narrative_blocks
        if str(block.get("heading", "")).strip()
        and str(block.get("content", "")).strip()
    ]

    if not valid_blocks:
        raise ValueError(
            "Não existem blocos narrativos válidos para criar cenas."
        )

    scene_count = len(valid_blocks)
    base_duration = production_duration_seconds // scene_count
    duration_remainder = production_duration_seconds % scene_count

    scenes = []

    for index, block in enumerate(valid_blocks, start=1):
        heading = str(block.get("heading", "")).strip()
        narration = str(block.get("content", "")).strip()
        purpose = str(block.get("purpose", "")).strip()

        if not heading or not narration:
            continue

        visual_type = _select_visual_type(heading)

        requirements = [
            f"Visual deve reforçar o bloco: {heading}.",
        ]

        if purpose:
            requirements.append(
                f"Objetivo narrativo: {purpose}."
            )

        scenes.append(
            {
                "order": index,
                "narrative_block": heading,
                "narration": narration,
                "visual_type": visual_type,
                "visual_description": (
                    f"Visual relacionado diretamente ao tema "
                    f"do bloco '{heading}', reforçando a narração."
                ),
                "duration_seconds": (
                    base_duration
                    + (
                        duration_remainder
                        if index == scene_count
                        else 0
                    )
                ),
                "requirements": requirements,
            }
        )

    if not scenes:
        raise ValueError(
            "Não foi possível criar cenas a partir dos blocos narrativos."
        )

    audio_requirements = [
        "Utilizar narração clara e inteligível.",
        "Manter música e efeitos sonoros abaixo da voz.",
        "Sincronizar mudanças de áudio com os principais momentos narrativos.",
    ]

    visual_requirements = list(
        content_item.get("visual_requirements") or []
    )

    return {
        "content_item_id": content_item["id"],
        "script_id": content_item["script_id"],
        "idea_id": content_item["idea_id"],
        "objective": content_item["objective"],
        "format": content_item["format"],
        "estimated_duration_seconds": production_duration_seconds,
        "status": "ready",
        "scenes": scenes,
        "audio_requirements": audio_requirements,
        "visual_requirements": visual_requirements,
    }


def _select_visual_type(heading: str) -> str:
    """
    Seleciona um tipo visual básico a partir da função narrativa do bloco.
    """

    normalized = heading.strip().lower()

    if "introdu" in normalized:
        return "title_card"

    if "context" in normalized:
        return "gameplay"

    if "impact" in normalized:
        return "gameplay_with_graphics"

    if "conclus" in normalized:
        return "summary_graphics"

    return "b_roll"
