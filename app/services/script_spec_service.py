from typing import Any

from app.database import research_repository
from app.database import scripts_repository


def generate_script_spec(
    script_id: int,
) -> dict[str, Any]:
    """
    Transforma um roteiro persistido em uma especificação editorial
    utilizável pelas próximas etapas do pipeline.
    """

    script = scripts_repository.get_script(script_id)

    if script is None:
        raise ValueError("O roteiro informado não existe.")

    content = script.get("content")

    if not isinstance(content, str) or not content.strip():
        raise ValueError("O roteiro precisa possuir conteúdo utilizável.")

    idea_id = script["idea_id"]

    objective = (
        f"Informar e contextualizar o público sobre "
        f"{script['title']}."
    )

    audience = (
        "Público interessado em GTA, Rockstar Games, "
        "notícias, novidades e análise de videogames."
    )

    estimated_duration_seconds = max(
        60,
        len(content.split()) // 2,
    )

    script_format = "YouTube editorial"

    tone = "informativo, direto e analítico"

    hook = _extract_section(content, "HOOK")

    narrative_blocks = _build_narrative_blocks(content)

    facts_sources = _get_research_sources(idea_id)

    cta = _extract_section(content, "CTA")

    visual_requirements = [
        {
            "type": "context",
            "description": (
                "Utilizar imagens, gameplay ou elementos visuais "
                "relacionados diretamente ao tema apresentado."
            ),
        },
        {
            "type": "support",
            "description": (
                "Utilizar elementos visuais para reforçar "
                "informações, fatos e mudanças mencionadas no roteiro."
            ),
        },
    ]

    return {
        "script_id": script_id,
        "idea_id": idea_id,
        "objective": objective,
        "audience": audience,
        "estimated_duration_seconds": estimated_duration_seconds,
        "format": script_format,
        "tone": tone,
        "hook": hook,
        "narrative_blocks": narrative_blocks,
        "facts_sources": facts_sources,
        "cta": cta,
        "visual_requirements": visual_requirements,
    }


def _extract_section(
    content: str,
    section_name: str,
) -> str:
    """
    Extrai uma seção textual do formato persistido pelo
    script_generator_service.
    """

    sections = content.split("\n\n")

    prefix = f"{section_name}\n"

    for section in sections:
        if section.startswith(prefix):
            return section[len(prefix):].strip()

    return ""


def _build_narrative_blocks(
    content: str,
) -> list[dict[str, str]]:
    """
    Converte as seções narrativas persistidas em blocos
    estruturados para produção.
    """

    block_mapping = {
        "INTRODUÇÃO": "apresentar a pauta e estabelecer o contexto",
        "CONTEXTO": "explicar o contexto necessário para compreender o tema",
        "O QUE SABEMOS": "apresentar as informações conhecidas sobre o tema",
        "IMPACTO": "explicar possíveis consequências e relevância para o público",
        "CONCLUSÃO": "consolidar os principais pontos apresentados",
    }

    blocks: list[dict[str, str]] = []

    for section in content.split("\n\n"):
        if "\n" not in section:
            continue

        heading, body = section.split("\n", 1)

        if heading not in block_mapping:
            continue

        blocks.append(
            {
                "heading": heading.title(),
                "content": body.strip(),
                "purpose": block_mapping[heading],
            }
        )

    return blocks


def _get_research_sources(
    idea_id: int,
) -> list[dict[str, Any]]:
    """
    Recupera a fonte de pesquisa associada à ideia, quando existir.
    """

    from app.database import ideas_repository

    idea = ideas_repository.get_idea(idea_id)

    if idea is None:
        return []

    research_item_id = idea.get("research_item_id")

    if research_item_id is None:
        return []

    research_item = research_repository.get_research_item(
        research_item_id
    )

    if research_item is None:
        return []

    return [research_item]
