from typing import Any

from app.database.content_repository import insert_content_item


REQUIRED_FIELDS = (
    "script_id",
    "idea_id",
    "objective",
    "audience",
    "estimated_duration_seconds",
    "format",
    "tone",
    "hook",
    "narrative_blocks",
    "facts_sources",
    "cta",
    "visual_requirements",
)


def create_content_item(
    script_spec: dict[str, Any],
) -> dict[str, Any]:
    """
    Converte uma especificação editorial de roteiro em um Content Item
    pronto para seguir para a etapa de planejamento de produção.

    Esta camada não gera vídeo e não executa IA generativa.
    Ela apenas organiza e valida o contrato editorial.
    """

    if not isinstance(script_spec, dict) or not script_spec:
        raise ValueError("A especificação editorial é obrigatória.")

    missing_fields = [
        field for field in REQUIRED_FIELDS
        if field not in script_spec
    ]

    if missing_fields:
        raise ValueError(
            "A especificação editorial está incompleta: "
            + ", ".join(missing_fields)
        )

    if not script_spec["script_id"]:
        raise ValueError("A especificação precisa possuir script_id.")

    if not script_spec["idea_id"]:
        raise ValueError("A especificação precisa possuir idea_id.")

    if not script_spec["objective"]:
        raise ValueError("A especificação precisa possuir objetivo.")

    if not script_spec["audience"]:
        raise ValueError("A especificação precisa possuir público.")

    if script_spec["estimated_duration_seconds"] <= 0:
        raise ValueError(
            "A especificação precisa possuir duração estimada válida."
        )

    if not script_spec["narrative_blocks"]:
        raise ValueError(
            "A especificação precisa possuir blocos narrativos."
        )

    if not script_spec["visual_requirements"]:
        raise ValueError(
            "A especificação precisa possuir requisitos visuais."
        )

    title = _build_title(script_spec)
    description = _build_description(script_spec)

    content_item_id = insert_content_item(
        title=title,
        content_type=script_spec["format"],
        status="ready",
    )

    return {
        "id": content_item_id,
        "script_id": script_spec["script_id"],
        "idea_id": script_spec["idea_id"],
        "title": title,
        "description": description,
        "format": script_spec["format"],
        "objective": script_spec["objective"],
        "audience": script_spec["audience"],
        "estimated_duration_seconds": (
            script_spec["estimated_duration_seconds"]
        ),
        "tone": script_spec["tone"],
        "hook": script_spec["hook"],
        "narrative_blocks": script_spec["narrative_blocks"],
        "facts_sources": script_spec["facts_sources"],
        "cta": script_spec["cta"],
        "visual_requirements": script_spec["visual_requirements"],
        "status": "ready",
    }


def _build_title(
    script_spec: dict[str, Any],
) -> str:
    """
    Recupera o título editorial da especificação.

    O título é derivado do roteiro associado quando disponível.
    """
    script_id = script_spec["script_id"]

    if script_id:
        return f"Content Item — Script {script_id}"

    return "Content Item"


def _build_description(
    script_spec: dict[str, Any],
) -> str:
    """
    Cria uma descrição operacional para o Content Item.
    """
    return (
        f"{script_spec['objective']} "
        f"Formato: {script_spec['format']}. "
        f"Público: {script_spec['audience']}."
    )
