from __future__ import annotations

import json
import math
import re
from typing import Any, TypedDict

from app.database import ideas_repository
from app.database import research_repository
from app.services import script_service
from app.services.ai_provider import AIProvider, AIProviderError


# Keep long-form script planning aligned with the human-approved Voice B
# narration calibration used by the production novelty gate. Run 35399181943 /
# artifact 10568953094 measured +0% Voice B in the 145-163 spoken-WPM range;
# 132 WPM is the conservative planning baseline after long-form pause allowance.
VOICE_B_SCRIPT_PLANNING_WPM = 132.0
LONGFORM_MIN_DEVELOPMENT_SECTIONS = 8
MAX_EDITORIAL_GENERATION_ATTEMPTS = 3
MAX_MALFORMED_PROVIDER_RETRIES = 1


class EditorialSequence(TypedDict):
    sequence_id: str
    story_beat: str
    editorial_purpose: str
    central_question: str
    target_duration: float
    estimated_spoken_duration: float
    evidence_refs: list[str]
    supported_claims: list[str]
    required_claims: list[str]
    required_media: list[str]
    novelty_requirements: list[str]
    dependencies: list[str]
    continuity_context: str
    status: str


class SequenceEvidenceGap(TypedDict):
    sequence_id: str
    missing_questions: list[str]
    missing_claim_types: list[str]
    existing_evidence: list[str]
    duplicate_topics_to_avoid: list[str]
    required_novelty: list[str]
    estimated_missing_supported_duration: float


class VideoPlan(TypedDict):
    schema: str
    central_question: str
    editorial_promise: str
    target_duration_seconds: float
    sequences: list[EditorialSequence]


class StoryAssembly(TypedDict):
    schema: str
    sequence_ids: list[str]
    evidence_refs: list[str]
    supported_claims: list[str]
    estimated_spoken_duration: float
    content_supported_duration_minutes: float
    development_section_count: int


class EditorialSequenceBatch(TypedDict):
    batch_id: str
    sequence_ids: list[str]
    target_duration: float
    evidence_refs: list[str]
    supported_claims: list[str]
    sequences: list[EditorialSequence]


EDITORIAL_SCRIPT_STRUCTURE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string", "minLength": 1},
        "introduction": {"type": "string", "minLength": 1},
        "development": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string", "minLength": 1},
                    "body": {"type": "string", "minLength": 1},
                },
                "required": ["heading", "body"],
                "additionalProperties": False,
            },
        },
        "conclusion": {"type": "string", "minLength": 1},
        "cta": {"type": "string", "minLength": 1},
    },
    "required": ["hook", "introduction", "development", "conclusion", "cta"],
    "additionalProperties": False,
}


def _requested_word_count(target_duration_seconds: float | None) -> int | None:
    if target_duration_seconds is None:
        return None
    target_minutes = float(target_duration_seconds) / 60.0
    return max(
        300,
        int(math.ceil(target_minutes * VOICE_B_SCRIPT_PLANNING_WPM)),
    )


def _minimum_development_sections(
    target_duration_seconds: float | None,
) -> int:
    if (
        target_duration_seconds is not None
        and float(target_duration_seconds) >= 1200.0
    ):
        # Hook + intro + 8 development blocks + conclusion + CTA = 12
        # semantic sections for the existing professional handoff.
        return LONGFORM_MIN_DEVELOPMENT_SECTIONS
    return 3


def _structure_word_count(structure: dict[str, Any]) -> int:
    parts = [
        str(structure.get("hook") or ""),
        str(structure.get("introduction") or ""),
        *[
            str(item.get("body") or "")
            for item in (structure.get("development") or ())
            if isinstance(item, dict)
        ],
        str(structure.get("conclusion") or ""),
        str(structure.get("cta") or ""),
    ]
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9]+", " ".join(parts)))


def _normalized_section_signature(section: dict[str, Any]) -> tuple[str, str]:
    heading = re.sub(
        r"[^a-z0-9à-ÿ]+",
        " ",
        str(section.get("heading") or "").casefold(),
    ).strip()
    body = re.sub(
        r"[^a-z0-9à-ÿ]+",
        " ",
        str(section.get("body") or "").casefold(),
    ).strip()
    return heading, body


def _merge_complementary_longform_structure(
    base: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Merge only distinct development blocks from bounded provider passes.

    The merge never manufactures prose. Every retained block is provider output
    generated from the same verified evidence context; downstream duration,
    novelty, duplication and human-review gates remain authoritative.
    """
    merged = {
        "hook": str(base.get("hook") or ""),
        "introduction": str(base.get("introduction") or ""),
        "development": [
            dict(item)
            for item in (base.get("development") or ())
            if isinstance(item, dict)
        ],
        "conclusion": str(base.get("conclusion") or ""),
        "cta": str(base.get("cta") or ""),
    }
    seen = {
        _normalized_section_signature(item)
        for item in merged["development"]
    }
    for item in candidate.get("development") or ():
        if not isinstance(item, dict):
            continue
        signature = _normalized_section_signature(item)
        if not all(signature) or signature in seen:
            continue
        merged["development"].append(dict(item))
        seen.add(signature)
    return merged


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
    target_words = _requested_word_count(target_duration_seconds)
    minimum_sections = _minimum_development_sections(
        target_duration_seconds
    )
    verified_claim_count = 0
    if isinstance(editorial_context, dict):
        verified_claims = editorial_context.get("verified_claims")
        if isinstance(verified_claims, list):
            verified_claim_count = sum(
                1 for item in verified_claims if isinstance(item, dict)
            )
    if target_duration_seconds is not None and target_words is not None:
        target_minutes = float(target_duration_seconds) / 60.0
        # Put most of the long-form budget in evidence-bearing development
        # blocks. This is a generation contract only: the downstream duration
        # and no-padding gates remain authoritative.
        development_word_floor = max(
            180,
            int(math.ceil((target_words * 0.78) / minimum_sections)),
        )
        duration_instruction = (
            "\nDURAÇÃO ALVO\n"
            f"- Aproximadamente {target_minutes:.1f} minutos de narração.\n"
            f"- O roteiro completo DEVE ter pelo menos {target_words} palavras úteis.\n"
            f"- O desenvolvimento DEVE conter pelo menos {minimum_sections} blocos distintos.\n"
            f"- Planeje cada body de development com aproximadamente {development_word_floor} "
            "palavras úteis ou mais, sem repetir informação.\n"
            f"- Há {verified_claim_count} claims verificadas no contexto editorial; distribua-as "
            "entre ângulos factuais distintos e aprofunde contexto/implicações somente quando "
            "a relação estiver sustentada.\n"
            "- Não fique preso a repetir o título da pauta: use as claims verificadas relacionadas "
            "para construir contexto GTA VI mais amplo quando isso for factual e pertinente.\n"
            "- Expanda apenas com contexto, análise e implicações sustentados pelas evidências fornecidas.\n"
            "- Não use repetição, paráfrase vazia ou filler para alcançar a duração.\n"
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
- O desenvolvimento deve possuir pelo menos {minimum_sections} blocos.
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



def _repair_invalid_json_string_escapes(text: str) -> str:
    """Escape only invalid backslashes inside JSON string literals."""
    valid_simple = {'"', "\\", "/", "b", "f", "n", "r", "t"}
    out: list[str] = []
    in_string = False
    index = 0

    while index < len(text):
        char = text[index]

        if not in_string:
            out.append(char)
            if char == '"':
                in_string = True
            index += 1
            continue

        if char == '"':
            out.append(char)
            in_string = False
            index += 1
            continue

        if char != "\\":
            out.append(char)
            index += 1
            continue

        if index + 1 >= len(text):
            out.append("\\\\")
            index += 1
            continue

        following = text[index + 1]
        if following in valid_simple:
            out.extend(("\\", following))
            index += 2
            continue

        if following == "u":
            hex_part = text[index + 2:index + 6]
            if (
                len(hex_part) == 4
                and all(ch in "0123456789abcdefABCDEF" for ch in hex_part)
            ):
                out.extend(("\\", "u", *hex_part))
                index += 6
                continue

        # Preserve literal provider text: only quote the backslash itself.
        out.append("\\\\")
        index += 1

    return "".join(out)


def _malformed_provider_json_error(exc: Exception) -> AIProviderError:
    return AIProviderError(
        "AI provider returned invalid JSON.",
        code="malformed_structured_output",
        retryable=True,
        failure_pattern="editorial_provider_malformed_json",
        failure_stage="response_decode",
        response_present=True,
        structured_output_present=True,
        parse_stage="json_decode",
        exception_class=type(exc).__name__,
        sanitized_reason="malformed_structured_output",
    )


def _parse_ai_json_response(text: str) -> dict[str, Any]:
    """Normalize wrappers, minimally repair escaping, then fail closed."""
    normalized = str(text or "").lstrip("\ufeff").strip()
    if not normalized:
        raise AIProviderError("AI provider returned an empty response.")

    fence = "```"
    if normalized.startswith(fence):
        lines = normalized.splitlines()
        if not lines or not lines[0].strip().casefold() in {fence, fence + "json"}:
            raise _malformed_provider_json_error(
                json.JSONDecodeError("invalid JSON fence", normalized, 0)
            )
        if len(lines) < 3 or lines[-1].strip() != fence:
            raise _malformed_provider_json_error(
                json.JSONDecodeError("unterminated JSON fence", normalized, 0)
            )
        normalized = "\n".join(lines[1:-1]).strip()

    if normalized.casefold().startswith("json\n"):
        normalized = normalized[5:].strip()

    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as first_exc:
        repaired = _repair_invalid_json_string_escapes(normalized)
        if repaired == normalized:
            raise _malformed_provider_json_error(first_exc) from first_exc
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError as repaired_exc:
            raise _malformed_provider_json_error(
                repaired_exc
            ) from repaired_exc

    if not isinstance(parsed, dict):
        raise AIProviderError("AI response must contain a JSON object.")
    return parsed

def _editorial_verified_claims(
    editorial_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(editorial_context, dict):
        return []
    value = editorial_context.get("verified_claims")
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _claim_statement(claim: dict[str, Any]) -> str:
    return str(
        claim.get("statement")
        or claim.get("text")
        or claim.get("claim")
        or ""
    ).strip()


def _claim_evidence_refs(claim: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for value in claim.get("evidence_refs") or ():
        clean = str(value or "").strip()
        if clean and clean not in refs:
            refs.append(clean)
    for key in ("fact_check_evidence_ref", "evidence_ref", "source"):
        clean = str(claim.get(key) or "").strip()
        if clean and clean not in refs:
            refs.append(clean)
    return refs


def _editorial_tokens(value: str) -> set[str]:
    stop = {
        "para", "como", "isso", "essa", "esse", "uma", "com", "dos", "das",
        "gta", "grand", "theft", "auto", "rockstar", "sobre", "mais", "pela",
        "pelo", "que", "por", "the", "and", "from", "with", "into", "vi",
    }
    return {
        token
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", str(value or "").casefold())
        if len(token) >= 4 and token not in stop
    }


def _spoken_seconds_for_words(word_count: int) -> float:
    return max(0.0, float(word_count) * 60.0 / VOICE_B_SCRIPT_PLANNING_WPM)


def _section_word_count(section: dict[str, Any]) -> int:
    return len(
        re.findall(
            r"[A-Za-zÀ-ÿ0-9]+",
            str(section.get("body") or ""),
        )
    )


def _build_longform_video_plan(
    *,
    title: str,
    description: str,
    initial_structure: dict[str, Any],
    editorial_context: dict[str, Any] | None,
    target_duration_seconds: float,
) -> tuple[VideoPlan, list[SequenceEvidenceGap]]:
    claims = _editorial_verified_claims(editorial_context)
    sections = [
        dict(item)
        for item in initial_structure.get("development") or ()
        if isinstance(item, dict)
    ]
    if not sections:
        raise AIProviderError("Long-form story plan contains no development beats.")

    rows: list[dict[str, Any]] = []
    for index, section in enumerate(sections, start=1):
        heading = str(section.get("heading") or "").strip()
        body = str(section.get("body") or "").strip()
        rows.append({
            "sequence_id": f"sequence-{index:03d}",
            "heading": heading,
            "body": body,
            "tokens": _editorial_tokens(heading + " " + body),
            "claims": [],
        })

    for claim in claims:
        statement = _claim_statement(claim)
        if not statement:
            continue
        claim_tokens = _editorial_tokens(statement)
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for index, row in enumerate(rows):
            overlap = len(claim_tokens & set(row["tokens"]))
            scored.append((overlap, -index, row))
        best_overlap, _stable, best = max(scored, key=lambda item: (item[0], item[1]))
        if best_overlap == 0:
            best = min(rows, key=lambda row: (len(row["claims"]), row["sequence_id"]))
        best["claims"].append(claim)

    framing_words = len(re.findall(
        r"[A-Za-zÀ-ÿ0-9]+",
        " ".join([
            str(initial_structure.get("hook") or ""),
            str(initial_structure.get("introduction") or ""),
            str(initial_structure.get("conclusion") or ""),
            str(initial_structure.get("cta") or ""),
        ]),
    ))
    development_target_seconds = max(
        0.0,
        float(target_duration_seconds) - _spoken_seconds_for_words(framing_words),
    )
    weights = [max(1, len(row["claims"])) for row in rows]
    weight_total = float(sum(weights) or 1)

    sequences: list[EditorialSequence] = []
    gaps: list[SequenceEvidenceGap] = []
    previous_id = ""
    previous_heading = ""
    for row, weight in zip(rows, weights):
        supported_claims = [
            _claim_statement(claim)
            for claim in row["claims"]
            if _claim_statement(claim)
        ]
        evidence_refs = list(dict.fromkeys(
            ref
            for claim in row["claims"]
            for ref in _claim_evidence_refs(claim)
        ))
        estimated_seconds = _spoken_seconds_for_words(
            _section_word_count({"body": row["body"]})
        )
        target_seconds = development_target_seconds * float(weight) / weight_total
        status = "SUPPORTED" if supported_claims else "EVIDENCE_GAP"
        sequence: EditorialSequence = {
            "sequence_id": str(row["sequence_id"]),
            "story_beat": str(row["heading"]),
            "editorial_purpose": str(row["body"])[:500],
            "central_question": f"Como este beat ajuda a responder: {description.strip()}",
            "target_duration": round(target_seconds, 3),
            "estimated_spoken_duration": round(estimated_seconds, 3),
            "evidence_refs": evidence_refs[:24],
            "supported_claims": supported_claims[:24],
            "required_claims": [],
            "required_media": [],
            "novelty_requirements": [
                "avoid claim duplication across sequences",
                "add only evidence-supported editorial value",
            ],
            "dependencies": [previous_id] if previous_id else [],
            "continuity_context": previous_heading,
            "status": status,
        }
        sequences.append(sequence)
        if status == "EVIDENCE_GAP":
            gaps.append({
                "sequence_id": sequence["sequence_id"],
                "missing_questions": [sequence["central_question"]],
                "missing_claim_types": ["source-grounded supporting claim"],
                "existing_evidence": evidence_refs,
                "duplicate_topics_to_avoid": [item["story_beat"] for item in sequences[:-1]],
                "required_novelty": list(sequence["novelty_requirements"]),
                "estimated_missing_supported_duration": round(
                    max(0.0, target_seconds - estimated_seconds), 3
                ),
            })
        previous_id = sequence["sequence_id"]
        previous_heading = sequence["story_beat"]

    return ({
        "schema": "video-plan/v1",
        "central_question": description.strip(),
        "editorial_promise": (
            f"Responder à pauta '{title}' com progressão narrativa baseada somente em evidência verificada."
        ),
        "target_duration_seconds": float(target_duration_seconds),
        "sequences": sequences,
    }, gaps)


def _select_sequence_expansion_batches(
    *,
    video_plan: VideoPlan,
    current_structure: dict[str, Any],
    target_duration_seconds: float,
    pass_budget: int,
) -> list[EditorialSequenceBatch]:
    if pass_budget <= 0:
        return []

    eligible = [
        dict(sequence)
        for sequence in video_plan["sequences"]
        if sequence["status"] == "SUPPORTED"
        and sequence["supported_claims"]
    ]
    if not eligible:
        return []

    batch_count = min(int(pass_budget), len(eligible))
    weights = [max(1, len(item["supported_claims"])) for item in eligible]
    total_weight = int(sum(weights) or 1)
    current_seconds = _spoken_seconds_for_words(
        _structure_word_count(current_structure)
    )
    remaining_seconds = max(
        0.0,
        float(target_duration_seconds) - current_seconds,
    )

    groups: list[list[EditorialSequence]] = []
    current: list[EditorialSequence] = []
    cumulative_weight = 0
    next_boundary = 1

    for index, (sequence, weight) in enumerate(zip(eligible, weights)):
        current.append(sequence)
        cumulative_weight += weight
        remaining_items = len(eligible) - index - 1
        remaining_groups = batch_count - len(groups) - 1
        if remaining_groups <= 0:
            continue
        boundary = total_weight * next_boundary / batch_count
        if (
            cumulative_weight >= boundary
            and remaining_items >= remaining_groups
        ):
            groups.append(current)
            current = []
            next_boundary += 1

    if current:
        groups.append(current)

    while len(groups) > batch_count:
        tail = groups.pop()
        groups[-1].extend(tail)

    batches: list[EditorialSequenceBatch] = []
    for batch_index, sequences in enumerate(groups, start=1):
        batch_weight = sum(
            max(1, len(item["supported_claims"]))
            for item in sequences
        )
        evidence_refs = list(dict.fromkeys(
            ref
            for item in sequences
            for ref in item["evidence_refs"]
        ))
        supported_claims = list(dict.fromkeys(
            claim
            for item in sequences
            for claim in item["supported_claims"]
        ))
        batches.append({
            "batch_id": f"sequence-batch-{batch_index:02d}",
            "sequence_ids": [
                item["sequence_id"] for item in sequences
            ],
            "target_duration": round(
                remaining_seconds * batch_weight / total_weight,
                3,
            ),
            "evidence_refs": evidence_refs[:48],
            "supported_claims": supported_claims[:48],
            "sequences": sequences,
        })
    return batches


def _sequence_batch_editorial_context(
    editorial_context: dict[str, Any] | None,
    batch: EditorialSequenceBatch,
) -> dict[str, Any]:
    source = dict(editorial_context or {})
    all_claims = _editorial_verified_claims(editorial_context)
    wanted = set(batch.get("supported_claims") or ())
    source["verified_claims"] = [
        claim
        for claim in all_claims
        if _claim_statement(claim) in wanted
    ]
    source["sequence_batch_context"] = {
        "batch_id": batch["batch_id"],
        "sequence_ids": list(batch["sequence_ids"]),
        "target_duration": batch["target_duration"],
        "evidence_refs": list(batch["evidence_refs"]),
        "sequences": [
            {
                "sequence_id": item["sequence_id"],
                "story_beat": item["story_beat"],
                "central_question": item["central_question"],
                "continuity_context": item["continuity_context"],
                "target_duration": item["target_duration"],
                "evidence_refs": list(item["evidence_refs"]),
                "supported_claims": list(item["supported_claims"]),
            }
            for item in batch["sequences"]
        ],
    }
    return source


def _build_sequence_batch_prompt(
    *,
    title: str,
    description: str,
    research_context: dict[str, Any] | None,
    editorial_context: dict[str, Any] | None,
    batch: EditorialSequenceBatch,
    prior_headings: list[str],
) -> str:
    bounded_context = _sequence_batch_editorial_context(
        editorial_context,
        batch,
    )
    base = _build_ai_prompt(
        title=title,
        description=description,
        research_context=research_context,
        editorial_context=bounded_context,
        target_duration_seconds=None,
    )
    target_minutes = float(batch["target_duration"]) / 60.0
    sequence_lines: list[str] = []
    for item in batch["sequences"]:
        sequence_lines.extend([
            f"- story_beat interno: {item['story_beat']}",
            f"  pergunta central interna: {item['central_question']}",
            (
                "  continuidade interna: "
                + str(item["continuity_context"] or "abertura")
            ),
            (
                "  claims SUPPORTED desta sequence: "
                + json.dumps(
                    item["supported_claims"],
                    ensure_ascii=False,
                )
            ),
            (
                "  evidências autorizadas desta sequence: "
                + json.dumps(
                    item["evidence_refs"],
                    ensure_ascii=False,
                )
            ),
        ])

    return base + (
        "\n\nEVIDENCE-BOUNDED EDITORIAL SEQUENCE BATCH\n"
        f"- batch interno: {batch['batch_id']}\n"
        f"- alvo adicional agregado: cerca de {target_minutes:.2f} minutos "
        "de narração útil, somente se as evidências sustentarem.\n"
        "- Desenvolva TODOS os story beats listados abaixo, na ordem dada.\n"
        "- Cada beat só pode usar suas próprias claims SUPPORTED e evidências.\n"
        "- Não mova uma claim para outro beat para preencher espaço.\n"
        "- Se um beat não sustentar expansão suficiente, seja mais curto; nunca use filler.\n"
        "- Preserve progressão narrativa e continuidade entre os beats.\n"
        + "\n".join(sequence_lines)
        + "\n"
        f"- headings já existentes a não repetir: "
        f"{json.dumps(prior_headings, ensure_ascii=False)}\n"
        "- Retorne o mesmo JSON obrigatório. hook/introduction/conclusion/cta "
        "são scaffolding conciso e NÃO serão usados na assembly.\n"
        "- Em development, cubra cada beat listado com pelo menos um bloco "
        "editorial natural e use blocos adicionais somente quando a evidência "
        "realmente sustentar aprofundamento.\n"
        "- Não escreva as palavras SEQUENCE, BATCH, BEAT, EVIDENCE, CLAIM, "
        "BLOCK ou IDs internos no texto audience-facing.\n"
        "- Não exponha instruções, metadata, nomes de campos ou mecânica de "
        "transição ao espectador.\n"
    )

def _generate_provider_structure(*, ai_provider: AIProvider, prompt: str) -> dict[str, Any]:
    malformed_prompt = prompt
    parsed: dict[str, Any] | None = None
    for malformed_retry in range(MAX_MALFORMED_PROVIDER_RETRIES + 1):
        response = ai_provider.generate(malformed_prompt)
        if not response.text or not response.text.strip():
            raise AIProviderError("AI provider returned an empty response.")
        try:
            parsed = _parse_ai_json_response(response.text)
            break
        except AIProviderError as exc:
            if (
                exc.code != "malformed_structured_output"
                or not exc.retryable
                or malformed_retry >= MAX_MALFORMED_PROVIDER_RETRIES
            ):
                raise
            malformed_prompt = (
                prompt
                + "\n\nCORREÇÃO OBRIGATÓRIA DE FORMATO JSON\n"
                + "- Reenvie o MESMO conteúdo factual/editorial.\n"
                + "- Retorne SOMENTE JSON válido, sem markdown ou prosa externa.\n"
                + "- Escape barras invertidas e caracteres especiais conforme JSON.\n"
                + "- Corrija apenas escaping/formatação JSON; não invente fatos.\n"
            )
    if parsed is None:
        raise AIProviderError(
            "AI provider returned invalid JSON.",
            code="malformed_structured_output",
            retryable=False,
        )
    return _validate_ai_structure(parsed)


def _story_assembly_metadata(*, structure: dict[str, Any], video_plan: VideoPlan) -> StoryAssembly:
    evidence_refs = list(dict.fromkeys(
        ref for sequence in video_plan["sequences"] for ref in sequence["evidence_refs"]
    ))
    supported_claims = list(dict.fromkeys(
        claim for sequence in video_plan["sequences"] for claim in sequence["supported_claims"]
    ))
    words = _structure_word_count(structure)
    seconds = _spoken_seconds_for_words(words)
    return {
        "schema": "story-assembly/v1",
        "sequence_ids": [item["sequence_id"] for item in video_plan["sequences"]],
        "evidence_refs": evidence_refs[:48],
        "supported_claims": supported_claims[:48],
        "estimated_spoken_duration": round(seconds, 3),
        "content_supported_duration_minutes": round(seconds / 60.0, 3),
        "development_section_count": len(structure.get("development") or ()),
    }


def _global_editorial_qa(
    *,
    structure: dict[str, Any],
    video_plan: VideoPlan,
    evidence_gaps: list[SequenceEvidenceGap],
    target_duration_seconds: float,
) -> dict[str, Any]:
    assembly = _story_assembly_metadata(structure=structure, video_plan=video_plan)
    signatures = [
        _normalized_section_signature(item)
        for item in structure.get("development") or ()
        if isinstance(item, dict)
    ]
    duplicate_count = max(0, len(signatures) - len(set(signatures)))
    supported_seconds = float(assembly["estimated_spoken_duration"])
    return {
        "schema": "global-editorial-qa/v1",
        "NARRATIVE_CONTINUITY": "CANDIDATE_REQUIRES_REAL_REVIEW",
        "STORY_PROGRESSION": "CANDIDATE_REQUIRES_REAL_REVIEW",
        "INTER_SEQUENCE_REPETITION": "PASS" if duplicate_count == 0 else "FAIL",
        "CLAIM_DUPLICATION": "NOT_SEMANTICALLY_REVERIFIED",
        "CONTRADICTIONS": "NOT_SEMANTICALLY_REVERIFIED",
        "EVIDENCE_COVERAGE": "PASS" if not evidence_gaps else "GAPS_PRESENT",
        "NOVELTY": "DOWNSTREAM_GATE_REQUIRED",
        "INFORMATION_DENSITY": "DOWNSTREAM_GATE_REQUIRED",
        "TRANSITION_NATURALNESS": "CANDIDATE_REQUIRES_REAL_REVIEW",
        "TOPIC_COHERENCE": "CANDIDATE_REQUIRES_REAL_REVIEW",
        "TOTAL_SUPPORTED_DURATION": (
            "PASS" if supported_seconds >= float(target_duration_seconds) else "FAIL"
        ),
        "content_supported_duration_minutes": round(supported_seconds / 60.0, 3),
        "target_duration_minutes": round(float(target_duration_seconds) / 60.0, 3),
        "supported_claim_count": len(assembly["supported_claims"]),
        "unsupported_claim_count": None,
        "sequence_evidence_gap_count": len(evidence_gaps),
        "duplicate_section_count": duplicate_count,
        "ARTIFICIAL_PADDING": "OFF",
    }


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
    target_words = _requested_word_count(target_duration_seconds)
    minimum_sections = _minimum_development_sections(target_duration_seconds)
    initial = _generate_provider_structure(ai_provider=ai_provider, prompt=prompt)

    if target_words is None:
        return initial
    if (
        _structure_word_count(initial) >= target_words
        and len(initial.get("development") or ()) >= minimum_sections
    ):
        return initial

    verified_claims = _editorial_verified_claims(editorial_context)
    if (
        target_duration_seconds is not None
        and float(target_duration_seconds) >= 1200.0
        and len(verified_claims) >= 2
    ):
        video_plan, evidence_gaps = _build_longform_video_plan(
            title=title,
            description=description,
            initial_structure=initial,
            editorial_context=editorial_context,
            target_duration_seconds=float(target_duration_seconds),
        )
        assembly = initial
        expansion_batches = _select_sequence_expansion_batches(
            video_plan=video_plan,
            current_structure=assembly,
            target_duration_seconds=float(target_duration_seconds),
            pass_budget=max(
                0,
                MAX_EDITORIAL_GENERATION_ATTEMPTS - 1,
            ),
        )
        generated_batches: list[dict[str, Any]] = []
        for batch in expansion_batches:
            prior_headings = [
                str(item.get("heading") or "").strip()
                for item in assembly.get("development") or ()
                if isinstance(item, dict)
                and str(item.get("heading") or "").strip()
            ]
            batch_prompt = _build_sequence_batch_prompt(
                title=title,
                description=description,
                research_context=research_context,
                editorial_context=editorial_context,
                batch=batch,
                prior_headings=prior_headings,
            )
            generated = _generate_provider_structure(
                ai_provider=ai_provider,
                prompt=batch_prompt,
            )
            before_words = _structure_word_count(assembly)
            assembly = _merge_complementary_longform_structure(
                assembly,
                generated,
            )
            generated_batches.append({
                "batch_id": batch["batch_id"],
                "sequence_ids": list(batch["sequence_ids"]),
                "evidence_refs": list(batch["evidence_refs"]),
                "supported_claim_count": len(
                    batch["supported_claims"]
                ),
                "expansion_target_duration": batch["target_duration"],
                "added_words": max(
                    0,
                    _structure_word_count(assembly) - before_words,
                ),
            })
            if (
                _structure_word_count(assembly) >= target_words
                and len(assembly.get("development") or ())
                >= minimum_sections
            ):
                break

        story_assembly = _story_assembly_metadata(structure=assembly, video_plan=video_plan)
        global_qa = _global_editorial_qa(
            structure=assembly,
            video_plan=video_plan,
            evidence_gaps=evidence_gaps,
            target_duration_seconds=float(target_duration_seconds),
        )
        assembly["_internal_editorial_structure"] = {
            "schema": "evidence-bounded-story-assembly-candidate/v1",
            "video_plan": video_plan,
            "editorial_sequence_batches_generated": generated_batches,
            "sequence_evidence_gaps": evidence_gaps,
            "story_assembly": story_assembly,
            "global_editorial_qa": global_qa,
        }
        if (
            global_qa["TOTAL_SUPPORTED_DURATION"] == "PASS"
            and len(assembly.get("development") or ()) >= minimum_sections
        ):
            return assembly

        raise AIProviderError(
            "AI response cannot sustain requested long-form duration without padding. "
            "story_assembly_mode=evidence_bounded_sequences "
            f"content_supported_duration_minutes={global_qa['content_supported_duration_minutes']} "
            f"target_duration_minutes={global_qa['target_duration_minutes']} "
            f"sequence_count={len(video_plan['sequences'])} "
            f"sequence_batch_count={len(expansion_batches)} "
            f"evidence_gap_count={len(evidence_gaps)} "
            f"observed_words={_structure_word_count(assembly)} target_words={target_words} "
            f"observed_development_sections={len(assembly.get('development') or ())} "
            f"required_development_sections={minimum_sections}"
        )

    previous_structure = initial
    for attempt in range(2, MAX_EDITORIAL_GENERATION_ATTEMPTS + 1):
        prior_words = _structure_word_count(previous_structure)
        prior_sections = len(previous_structure.get("development") or ())
        remaining_words = max(300, target_words - prior_words)
        complementary_block_floor = max(180, int(math.ceil(remaining_words / 4.0)))
        required_new_blocks = max(
            3,
            min(6, int(math.ceil(remaining_words / complementary_block_floor))),
        )
        prior_headings = [
            str(item.get("heading") or "").strip()
            for item in previous_structure.get("development") or ()
            if isinstance(item, dict) and str(item.get("heading") or "").strip()
        ]
        attempt_prompt = prompt + (
            "\n\nEXPANSÃO EDITORIAL COMPLEMENTAR OBRIGATÓRIA\n"
            f"- A composição validada até aqui possui {prior_words} palavras e {prior_sections} blocos de desenvolvimento.\n"
            f"- Ainda faltam aproximadamente {remaining_words} palavras úteis para o contrato de duração.\n"
            f"- Produza pelo menos {required_new_blocks} novos blocos de development, planejando cada body com cerca de {complementary_block_floor} palavras úteis ou mais quando as evidências sustentarem.\n"
            f"- Os novos blocos, em conjunto, devem buscar cobrir as {remaining_words} palavras úteis restantes sem filler.\n"
            "- Produza SOMENTE ângulos/blocos de desenvolvimento complementares sustentados pelas MESMAS evidências verificadas.\n"
            "- NÃO reescreva nem parafraseie os blocos já produzidos.\n"
            f"- Evite repetir estes headings: {json.dumps(prior_headings, ensure_ascii=False)}\n"
            "- Preserve estritamente os fatos e evidências fornecidos.\n"
            "- Aprofunde contexto, consequências, comparações e implicações somente quando sustentados pelas evidências.\n"
            "- Não use filler, repetição ou paráfrase vazia para bater duração.\n"
            "- Mantenha o mesmo JSON obrigatório; hook/introduction/conclusion/cta podem ser concisos porque somente development será agregado.\n"
        )
        structure = _generate_provider_structure(ai_provider=ai_provider, prompt=attempt_prompt)
        if (
            _structure_word_count(structure) >= target_words
            and len(structure.get("development") or ()) >= minimum_sections
        ):
            return structure
        previous_structure = _merge_complementary_longform_structure(previous_structure, structure)
        if (
            _structure_word_count(previous_structure) >= target_words
            and len(previous_structure.get("development") or ()) >= minimum_sections
        ):
            return previous_structure

    final_words = _structure_word_count(previous_structure)
    final_sections = len(previous_structure.get("development") or ())
    raise AIProviderError(
        "AI response cannot sustain requested long-form duration without padding. "
        f"observed_words={final_words} target_words={target_words} "
        f"observed_development_sections={final_sections} "
        f"required_development_sections={minimum_sections}"
    )

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

    internal = structure.get("_internal_editorial_structure")
    if isinstance(internal, dict):
        qa = dict(internal.get("global_editorial_qa") or {})
        story = dict(internal.get("story_assembly") or {})
        print("STORY_ASSEMBLY_MODE=EVIDENCE_BOUNDED_SEQUENCES")
        print("CONTENT_SUPPORTED_DURATION_MINUTES=" + str(qa.get("content_supported_duration_minutes")))
        print("EDITORIAL_SEQUENCE_COUNT=" + str(len((internal.get("video_plan") or {}).get("sequences") or ())))
        print("SEQUENCE_EVIDENCE_GAP_COUNT=" + str(qa.get("sequence_evidence_gap_count")))
        print("SUPPORTED_CLAIMS_IN_ASSEMBLY=" + str(len(story.get("supported_claims") or ())))
        print("PRODUCTION_METADATA_IN_SCRIPT_CONTENT=FORBIDDEN")

    return script_service.create_script(
        idea_id=idea_id,
        title=structure["title"],
        content=content,
        status="draft",
    )
