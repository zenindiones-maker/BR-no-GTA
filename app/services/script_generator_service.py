from __future__ import annotations

import json
from typing import Any

from app.database import ideas_repository
from app.database import research_repository
from app.services import script_service
from app.services.ai_provider import AIProvider, AIProviderError


# Keep long-form script planning aligned with the human-approved Voice B
# narration calibration used by the production novelty gate. Run 35399181943 /
# artifact 10568953094 measured +0% Voice B in the 145-163 spoken-WPM range;
# 132 WPM is the conservative planning baseline after long-form pause allowance.
VOICE_B_SCRIPT_PLANNING_WPM = 132.0


def _build_ai_prompt(
    *,
    title: str,
    description: str,
    research_context: dict[str, Any] | None,
    editorial_context: dict[str, Any] | None = None,
    target_duration_seconds: float | None = None,
) -> str:
    research_text = "Nenhuma fonte de pesquisa adicional disponível."

    if research_context is not None:
        research_text = (
            f"Título da pesquisa: {research_context.get('title', '')}\n"
            f"Conteúdo da pesquisa: {research_context.get('content', '')}\n"
            f"URL: {research_context.get('url', '')}"
        )

    editorial_text = ""
    if editorial_context:
        editorial_text = (
            "\nCONTEXTO EDITORIAL DO YOUTUBE DEPARTMENT\n"
            + json.dumps(editorial_context, ensure_ascii=False, sort_keys=True)
            + "\n"
        )

    duration_instruction = ""
    if target_duration_seconds is not None:
        target_minutes = float(target_duration_seconds) / 60.0
        target_words = max(
            300,
            int(round(target_minutes * VOICE_B_SCRIPT_PLANNING_WPM)),
        )
        duration_instruction = (
            "\nDURAÇÃO ALVO\n"
            f"- Aproximadamente {target_minutes:.1f} minutos de narração.\n"
            f"- Mire aproximadamente {target_words} palavras no roteiro completo.\n"
            "- Distribua o desenvolvimento em blocos suficientes para sustentar a duração "
            "sem repetição artificial de frases.\n"
        )

    return f"""
Você é o roteirista editorial de um canal brasileiro especializado em GTA 6.

Crie uma estrutura de roteiro informativo, factual e envolvente para a pauta abaixo.

PAUTA
Título: {title}

Descrição:
{description}

CONTEXTO DE PESQUISA
{research_text}
{editorial_text}
{duration_instruction}

REGRAS
- Não invente fatos.
- Não apresente especulação como confirmação.
- Use somente as informações fornecidas e as claims explicitamente verificadas.
- Considere o contexto editorial do YouTube Department quando fornecido, mas ele não pode substituir evidência factual.
- Escreva em português brasileiro.
- O roteiro deve ser adequado para narração em vídeo.
- O hook deve despertar curiosidade sem usar clickbait enganoso.
- O desenvolvimento deve possuir pelo menos 3 blocos.
- Cada bloco deve possuir "heading" e "body".
- A resposta deve ser SOMENTE JSON válido.
- Não use markdown.
- Não envolva o JSON em ```.

FORMATO OBRIGATÓRIO

{{
  "hook": "string",
  "introduction": "string",
  "development": [
    {{
      "heading": "string",
      "body": "string"
    }},
    {{
      "heading": "string",
      "body": "string"
    }},
    {{
      "heading": "string",
      "body": "string"
    }}
  ],
  "conclusion": "string",
  "cta": "string"
}}
""".strip()


def _validate_ai_structure(
    structure: Any,
) -> dict[str, Any]:
    if not isinstance(structure, dict):
        raise AIProviderError(
            "AI response must contain a JSON object."
        )

    required_fields = (
        "hook",
        "introduction",
        "development",
        "conclusion",
        "cta",
    )

    for field in required_fields:
        value = structure.get(field)

        if field == "development":
            if not isinstance(value, list) or len(value) < 3:
                raise AIProviderError(
                    "AI response development must contain at least 3 sections."
                )
            continue

        if not isinstance(value, str) or not value.strip():
            raise AIProviderError(
                f"AI response field '{field}' must be a non-empty string."
            )

    development = structure["development"]

    for section in development:
        if not isinstance(section, dict):
            raise AIProviderError(
                "AI response development sections must be objects."
            )

        heading = section.get("heading")
        body = section.get("body")

        if not isinstance(heading, str) or not heading.strip():
            raise AIProviderError(
                "AI response development heading must be non-empty."
            )

        if not isinstance(body, str) or not body.strip():
            raise AIProviderError(
                "AI response development body must be non-empty."
            )

    return {
        "hook": structure["hook"].strip(),
        "introduction": structure["introduction"].strip(),
        "development": [
            {
                "heading": section["heading"].strip(),
                "body": section["body"].strip(),
            }
            for section in development
        ],
        "conclusion": structure["conclusion"].strip(),
        "cta": structure["cta"].strip(),
    }



def _parse_ai_json_response(text: str) -> dict[str, Any]:
    """Normalize only harmless JSON wrappers, then fail closed on extra prose."""
    normalized = str(text or "").lstrip("\ufeff").strip()
    if not normalized:
        raise AIProviderError("AI provider returned an empty response.")

    fence = "```"
    if normalized.startswith(fence):
        lines = normalized.splitlines()
        if not lines or not lines[0].strip().casefold() in {fence, fence + "json"}:
            raise AIProviderError("AI provider returned invalid JSON.")
        if len(lines) < 3 or lines[-1].strip() != fence:
            raise AIProviderError("AI provider returned invalid JSON.")
        normalized = "\n".join(lines[1:-1]).strip()

    if normalized.casefold().startswith("json\n"):
        normalized = normalized[5:].strip()

    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise AIProviderError("AI provider returned invalid JSON.") from exc

    if not isinstance(parsed, dict):
        raise AIProviderError("AI response must contain a JSON object.")
    return parsed

def _generate_ai_structure(
    *,
    title: str,
    description: str,
    research_context: dict[str, Any] | None,
    ai_provider: AIProvider,
    editorial_context: dict[str, Any] | None = None,
    target_duration_seconds: float | None = None,
) -> dict[str, Any]:
    prompt = _build_ai_prompt(
        title=title,
        description=description,
        research_context=research_context,
        editorial_context=editorial_context,
        target_duration_seconds=target_duration_seconds,
    )

    response = ai_provider.generate(prompt)

    if not response.text or not response.text.strip():
        raise AIProviderError(
            "AI provider returned an empty response."
        )

    parsed = _parse_ai_json_response(response.text)
    return _validate_ai_structure(parsed)


def generate_script_structure(
    idea_id: int,
    *,
    ai_provider: AIProvider | None = None,
    editorial_context: dict[str, Any] | None = None,
    target_duration_seconds: float | None = None,
) -> dict[str, Any]:
    """
    Gera uma estrutura editorial de roteiro a partir de uma ideia aprovada.

    Quando um AIProvider é fornecido, a estrutura editorial é gerada pelo
    provider. Sem provider, mantém o comportamento determinístico legado,
    permitindo que o núcleo editorial continue testável sem rede ou IA.
    """
    idea = ideas_repository.get_idea(idea_id)

    if idea is None:
        raise ValueError("A ideia informada não existe.")

    if idea["status"] != "approved":
        raise ValueError(
            "Só é possível gerar roteiro para uma ideia aprovada."
        )

    description = idea.get("description")

    if (
        not isinstance(description, str)
        or not description.strip()
    ):
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

    if ai_provider is not None:
        ai_structure = _generate_ai_structure(
            title=title,
            description=normalized_description,
            research_context=research_context,
            ai_provider=ai_provider,
            editorial_context=editorial_context,
            target_duration_seconds=target_duration_seconds,
        )

        return {
            "idea_id": idea_id,
            "title": title,
            **ai_structure,
            "research_context": research_context,
        }

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
    Converte a estrutura editorial em texto persistível
    em scripts.content.
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
    *,
    ai_provider: AIProvider | None = None,
    editorial_context: dict[str, Any] | None = None,
    target_duration_seconds: float | None = None,
) -> int:
    """
    Gera a estrutura editorial e persiste uma nova versão como draft.

    O controle de aprovação, versionamento e persistência permanece
    no script_service.
    """
    structure = generate_script_structure(
        idea_id,
        ai_provider=ai_provider,
        editorial_context=editorial_context,
        target_duration_seconds=target_duration_seconds,
    )

    content = _structure_to_content(structure)

    return script_service.create_script(
        idea_id=idea_id,
        title=structure["title"],
        content=content,
        status="draft",
    )
