from typing import Any
import math
import re

MAX_SCENE_DURATION_SECONDS = 30.0


def _tokens(value: str) -> set[str]:
    stop = {
        "para", "com", "uma", "uns", "das", "dos", "que", "por", "como",
        "mais", "menos", "isso", "essa", "esse", "aqui", "hoje", "agora",
        "rockstar", "gta", "grand", "theft", "auto",
    }
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", value or "")
        if token.casefold() not in stop
    }


def _claim_refs_for_narration(
    narration: str,
    verified_claims: list[dict[str, Any]],
) -> list[str]:
    narration_tokens = _tokens(narration)
    scored: list[tuple[int, str]] = []
    for claim in verified_claims:
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("claim_id") or "").strip()
        statement = str(claim.get("statement") or "").strip()
        if not claim_id or not statement:
            continue
        overlap = len(narration_tokens & _tokens(statement))
        if overlap >= 2:
            scored.append((overlap, f"claim:{claim_id}"))
    scored.sort(reverse=True)
    return [ref for _, ref in scored[:3]]


def _media_search_terms(heading: str, narration: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", f"{heading} {narration}"):
        normalized = token.casefold()
        if normalized in {
            "para", "com", "uma", "uns", "das", "dos", "que", "por", "como",
            "mais", "isso", "essa", "esse", "aqui", "hoje", "agora", "vídeo",
        }:
            continue
        if token not in tokens:
            tokens.append(token)
        if len(tokens) >= 8:
            break
    base = " ".join(tokens).strip()
    return [f"GTA VI Rockstar {base}".strip()] if base else ["GTA VI Rockstar official"]


def _visual_direction(
    *,
    heading: str,
    narration: str,
    evidence_refs: list[str],
    visual_type: str,
) -> str:
    excerpt = " ".join(narration.split())[:220]
    evidence_note = (
        " Usar evidência oficial correspondente aos claims vinculados e exibir selo FATO."
        if evidence_refs
        else " Tratar qualquer leitura não factual com selo INTERPRETAÇÃO e usar apenas assets oficiais como apoio visual."
    )
    return (
        f"{visual_type}: ilustrar especificamente o bloco '{heading}' com asset/captura oficial "
        f"coerente com a narração: “{excerpt}”.{evidence_note}"
    )


def create_production_plan(
    content_item: dict[str, Any],
) -> dict[str, Any]:
    """Build a production-ready plan without discarding script structure or lineage."""

    if not isinstance(content_item, dict) or not content_item:
        raise ValueError("O content item informado é inválido.")

    required_fields = [
        "script_id", "idea_id", "objective", "format",
        "estimated_duration_seconds", "narrative_blocks", "visual_requirements",
    ]
    for field in required_fields:
        if field not in content_item:
            raise ValueError(f"O content item não possui o campo obrigatório: {field}.")

    narrative_blocks = content_item.get("narrative_blocks")
    if not isinstance(narrative_blocks, list) or not narrative_blocks:
        raise ValueError("O content item precisa possuir blocos narrativos.")

    duration = content_item["estimated_duration_seconds"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("estimated_duration_seconds deve ser finito e positivo.")
    duration = float(duration)

    valid_blocks = [
        block for block in narrative_blocks
        if isinstance(block, dict)
        and str(block.get("heading", "")).strip()
        and str(block.get("content", "")).strip()
    ]
    if not valid_blocks:
        raise ValueError("Não existem blocos narrativos válidos para criar cenas.")

    total_words = sum(max(1, len(str(block["content"]).split())) for block in valid_blocks)
    verified_claims = [
        dict(item) for item in (content_item.get("verified_claims") or [])
        if isinstance(item, dict)
    ]
    scenes: list[dict[str, Any]] = []
    scene_order = 0

    for block_index, block in enumerate(valid_blocks):
        heading = str(block["heading"]).strip()
        narration = str(block["content"]).strip()
        purpose = str(block.get("purpose", "")).strip()
        block_words = max(1, len(narration.split()))
        block_duration = duration * block_words / total_words
        part_count = max(1, int(math.ceil(block_duration / MAX_SCENE_DURATION_SECONDS)))
        words = narration.split()
        base_visual_type = _select_visual_type(heading)

        for part_index in range(part_count):
            scene_order += 1
            start = round(part_index * len(words) / part_count)
            end = round((part_index + 1) * len(words) / part_count)
            chunk = " ".join(words[start:end]).strip() or narration
            part_duration = (
                block_duration - (block_duration / part_count) * (part_count - 1)
                if part_index == part_count - 1
                else block_duration / part_count
            )
            visual_type = base_visual_type
            if base_visual_type == "title_card" and part_index > 0:
                visual_type = "official_source_broll"
            elif base_visual_type == "summary_graphics" and part_index > 0:
                visual_type = "official_source_broll"

            evidence_refs = _claim_refs_for_narration(chunk, verified_claims)
            scene_heading = (
                f"{heading} — parte {part_index + 1}/{part_count}"
                if part_count > 1 else heading
            )
            requirements = [f"Objetivo narrativo: {purpose}."] if purpose else []
            requirements.extend([
                "Usar mídia resolvível por source_url/asset_ref ou busca governada.",
                "Não representar inferência como fato.",
            ])
            scenes.append(
                {
                    "order": scene_order,
                    "narrative_block": scene_heading,
                    "narration": chunk,
                    "visual_type": visual_type,
                    "visual_description": _visual_direction(
                        heading=heading,
                        narration=chunk,
                        evidence_refs=evidence_refs,
                        visual_type=visual_type,
                    ),
                    "media_search_terms": _media_search_terms(heading, chunk),
                    "evidence_refs": evidence_refs,
                    "duration_seconds": part_duration,
                    "requirements": requirements,
                }
            )

    # Preserve exact total duration despite floating-point proportional allocation.
    drift = duration - sum(float(scene["duration_seconds"]) for scene in scenes)
    scenes[-1]["duration_seconds"] = float(scenes[-1]["duration_seconds"]) + drift
    if any(float(scene["duration_seconds"]) > MAX_SCENE_DURATION_SECONDS + 0.001 for scene in scenes):
        raise RuntimeError("production scene exceeds maximum duration after proportional split")

    return {
        "content_item_id": content_item["id"],
        "script_id": content_item["script_id"],
        "idea_id": content_item["idea_id"],
        "title": str(content_item.get("title") or "").strip() or None,
        "description": str(content_item.get("description") or "").strip(),
        "objective": content_item["objective"],
        "audience": content_item.get("audience"),
        "format": content_item["format"],
        "tone": content_item.get("tone"),
        "hook": content_item.get("hook"),
        "cta": content_item.get("cta"),
        "facts_sources": list(content_item.get("facts_sources") or []),
        "verified_claims": verified_claims,
        "youtube_strategy": content_item.get("youtube_strategy"),
        "editorial_evidence_refs": list(content_item.get("editorial_evidence_refs") or []),
        "estimated_duration_seconds": duration,
        "status": "ready",
        "scenes": scenes,
        "audio_requirements": [
            "Utilizar narração clara e inteligível.",
            "Manter música e efeitos sonoros abaixo da voz.",
            "Sincronizar mudanças de áudio com cada bloco narrativo e transição factual/editorial.",
        ],
        "visual_requirements": list(content_item.get("visual_requirements") or []),
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
