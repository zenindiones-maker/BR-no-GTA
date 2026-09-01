from typing import Any

from app.database import ideas_repository
from app.database import research_repository
from app.services import script_service


def generate_script_structure(
    idea_id: int,
) -> dict[str, Any]:
    """
    Gera uma estrutura editorial de roteiro a partir de uma ideia aprovada.

    A função não persiste o roteiro.
    Ela apenas constrói a estrutura editorial que poderá
    posteriormente ser salva pelo script_service.
    """
    idea = ideas_repository.get_idea(idea_id)

    if idea is None:
        raise ValueError("A ideia informada não existe.")

    if idea["status"] != "approved":
        raise ValueError(
            "Só é possível gerar roteiro para uma ideia aprovada."
        )

    description = idea.get("description")

    if not isinstance(description, str) or not description.strip():
        raise ValueError(
            "A ideia precisa possuir uma descrição utilizável."
        )

    research_context = None

    research_item_id = idea.get("research_item_id")

    if research_item_id is not None:
        research_context = research_repository.get_research_item(
            research_item_id
        )

    title = idea["title"].strip()
    normalized_description = description.strip()

    hook = (
        f"Você sabia que {title.lower()}? "
        "Entenda o que está por trás dessa mudança."
    )

    introduction = (
        f"Hoje vamos analisar {title.lower()}. "
        f"A pauta parte da seguinte questão: "
        f"{normalized_description}"
    )

    development = [
        {
            "heading": "Contexto",
            "body": (
                f"Primeiro, precisamos entender o contexto de "
                f"{title.lower()}."
            ),
        },
        {
            "heading": "O que sabemos",
            "body": (
                f"As informações disponíveis indicam que "
                f"{normalized_description}"
            ),
        },
        {
            "heading": "Impacto",
            "body": (
                "O ponto principal é entender como essas informações "
                "podem afetar o público e a experiência apresentada."
            ),
        },
    ]

    conclusion = (
        f"Em resumo, {title.lower()} merece atenção porque "
        "pode representar uma mudança relevante para o público."
    )

    cta = (
        "Se você quer acompanhar as próximas novidades, "
        "inscreva-se no canal e acompanhe os próximos conteúdos."
    )

    return {
        "idea_id": idea_id,
        "title": title,
        "hook": hook,
        "introduction": introduction,
        "development": development,
        "conclusion": conclusion,
        "cta": cta,
        "research_context": research_context,
    }


def _structure_to_content(
    structure: dict[str, Any],
) -> str:
    """
    Converte a estrutura editorial em texto persistível no scripts.content.
    """
    sections = [
        f"HOOK\n{structure['hook']}",
        f"INTRODUÇÃO\n{structure['introduction']}",
    ]

    for section in structure["development"]:
        sections.append(
            f"{section['heading'].upper()}\n{section['body']}"
        )

    sections.extend(
        [
            f"CONCLUSÃO\n{structure['conclusion']}",
            f"CTA\n{structure['cta']}",
        ]
    )

    return "\n\n".join(sections)


def generate_and_save_script(
    idea_id: int,
) -> int:
    """
    Gera a estrutura editorial e persiste uma nova versão como draft.

    O controle de aprovação, versionamento e persistência permanece
    no script_service.
    """
    structure = generate_script_structure(idea_id)

    content = _structure_to_content(structure)

    return script_service.create_script(
        idea_id=idea_id,
        title=structure["title"],
        content=content,
        status="draft",
    )
