from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from app.database import continuous_operation_repository as continuous_repository
from app.database import gta6_brain_repository as brain_repository
from app.database.memory_claim_repository import get_memory_claim


MAX_FILE_BYTES = 96 * 1024


def _yaml_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, dict, int, float)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return json.dumps(str(value), ensure_ascii=False)


def _markdown(frontmatter: dict[str, Any], title: str, body: str) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {_yaml_value(value)}")
    lines.extend(["---", "", f"# {title}", "", str(body).strip(), ""])
    text = "\n".join(lines)
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("GTA6 Obsidian projection file exceeds bounded size")
    return text


def _write(root: Path, relative: str, text: str) -> str:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return relative


def _slug(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9À-ÿ._-]+", "-", str(value or "").strip())
    return text.strip("-") or "Unknown"


def export_gta6_second_brain_projection(
    *,
    root: Path,
    generated_at: str | None = None,
) -> list[str]:
    now = generated_at or datetime.now(timezone.utc).isoformat()
    files: list[str] = []
    entities = brain_repository.list_entities(limit=2000)
    relations = brain_repository.list_relations(limit=4000)
    sources = brain_repository.list_sources(active_only=False, limit=2000)
    frontier = brain_repository.list_frontier(
        statuses=("OPEN", "INVESTIGATING", "RESOLVED", "STALE", "BLOCKED"),
        limit=500,
    )
    claim_meta = brain_repository.list_claim_metadata(limit=2000)
    daily_runs = brain_repository.list_daily_runs(limit=30)
    lineage = {
        int(item["claim_id"]): item
        for item in continuous_repository.list_claim_lineage(limit=500)
    }
    entity_by_id = {str(item["entity_id"]): item for item in entities}

    entity_folders = {
        "CHARACTER": "Characters",
        "LOCATION": "Locations",
        "VEHICLE": "Vehicles",
        "MECHANIC": "Mechanics",
        "ORGANIZATION": "Organizations",
        "EVENT": "Events",
        "SOURCE": "Sources",
        "CLAIM": "Claims",
        "EVIDENCE": "Evidence",
        "VIDEO": "Videos",
        "TOPIC": "Topics",
    }
    relations_by_entity: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        relations_by_entity.setdefault(str(relation["subject_id"]), []).append(relation)
        relations_by_entity.setdefault(str(relation["object_id"]), []).append(relation)

    for entity in entities:
        entity_id = str(entity["entity_id"])
        entity_type = str(entity["entity_type"]).upper()
        folder = entity_folders.get(entity_type, "Topics")
        links: list[str] = []
        for relation in relations_by_entity.get(entity_id, ()):
            subject_id = str(relation["subject_id"])
            object_id = str(relation["object_id"])
            other_id = object_id if subject_id == entity_id else subject_id
            other = entity_by_id.get(other_id)
            if other is None:
                continue
            other_folder = entity_folders.get(
                str(other["entity_type"]).upper(), "Topics"
            )
            direction = (
                str(relation["predicate"])
                if subject_id == entity_id
                else "inverse:" + str(relation["predicate"])
            )
            links.append(
                f"- **{direction}** → "
                f"[[10-Entities/{other_folder}/{other_id}|{other['canonical_name']}]]"
            )
        files.append(_write(
            root,
            f"10-Entities/{folder}/{entity_id}.md",
            _markdown(
                {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "canonical_name": entity["canonical_name"],
                    "aliases": entity.get("aliases") or [],
                    "status": entity.get("status"),
                    "first_seen_at": entity.get("first_seen_at"),
                    "last_seen_at": entity.get("last_seen_at"),
                    "canonical_source": "BR_SQLITE",
                    "obsidian_authority": "NONE",
                },
                str(entity["canonical_name"]),
                "\n".join([
                    f"**ID canônico:** {entity_id}",
                    f"**Tipo:** {entity_type}",
                    "",
                    "## Relações canônicas",
                    *(links or ["Nenhuma relação tipada persistida ainda."]),
                ]),
            ),
        ))

    status_folder = {
        "ACTIVE": "Verified",
        "VERIFIED": "Verified",
        "DISCOVERED": "Unverified",
        "UNVERIFIED": "Unverified",
        "CONTRADICTED": "Contradicted",
        "REJECTED": "Contradicted",
        "SUPERSEDED": "Superseded",
    }
    editorial_unused: list[str] = []
    editorial_used: list[str] = []
    editorial_opportunities: list[str] = []

    for meta in claim_meta:
        claim_id = int(meta["claim_id"])
        claim = get_memory_claim(claim_id)
        if claim is None:
            continue
        row = lineage.get(claim_id, {})
        brain_status = str(meta.get("brain_status") or "DISCOVERED").upper()
        folder = status_folder.get(brain_status, "Unverified")
        subject_entity = entity_by_id.get(str(meta.get("subject_entity_id") or ""))
        subject_link = str(row.get("subject") or "Unknown")
        if subject_entity is not None:
            entity_folder = entity_folders.get(
                str(subject_entity["entity_type"]).upper(), "Topics"
            )
            subject_link = (
                f"[[10-Entities/{entity_folder}/{subject_entity['entity_id']}|"
                f"{subject_entity['canonical_name']}]]"
            )

        files.append(_write(
            root,
            f"20-Claims/{folder}/Claim-{claim_id}.md",
            _markdown(
                {
                    "claim_id": claim_id,
                    "brain_status": brain_status,
                    "canonical_claim_status": claim.get("status"),
                    "subject_entity_id": meta.get("subject_entity_id"),
                    "predicate": meta.get("predicate"),
                    "object_entity_id": meta.get("object_entity_id"),
                    "confidence": claim.get("confidence"),
                    "world_novelty": meta.get("world_novelty"),
                    "knowledge_novelty": meta.get("knowledge_novelty"),
                    "editorial_novelty": meta.get("editorial_novelty"),
                    "freshness_class": meta.get("freshness_class"),
                    "freshness_due_at": meta.get("freshness_due_at"),
                    "superseded_by_claim_id": meta.get("superseded_by_claim_id"),
                    "related_claims": meta.get("related_claims") or [],
                    "source_id": row.get("source_id"),
                    "evidence_ref": row.get("evidence_ref"),
                    "canonical_source": "BR_SQLITE",
                    "obsidian_authority": "NONE",
                },
                f"Claim {claim_id}",
                "\n".join([
                    str(claim.get("claim") or ""),
                    "",
                    f"**Entidade:** {subject_link}",
                    f"**Fonte:** {row.get('source_url') or 'n/a'}",
                    f"**Evidência:** {row.get('evidence_ref') or 'n/a'}",
                    f"**World novelty:** {meta.get('world_novelty') or 'UNKNOWN'}",
                    f"**Knowledge novelty:** {meta.get('knowledge_novelty') or 'UNKNOWN'}",
                    f"**Editorial novelty:** {meta.get('editorial_novelty') or 'UNUSED'}",
                ]),
            ),
        ))

        claim_link = f"[[20-Claims/{folder}/Claim-{claim_id}|Claim {claim_id}]]"
        if meta.get("used_in_content"):
            editorial_used.append(claim_link)
        else:
            editorial_unused.append(claim_link)
        if (
            str(meta.get("world_novelty") or "").upper() in {"HIGH", "NEW"}
            and str(meta.get("knowledge_novelty") or "").upper() == "NEW"
            and str(meta.get("editorial_novelty") or "").upper() == "UNUSED"
        ):
            editorial_opportunities.append(claim_link)

    source_folder = {
        "ROCKSTAR_OFFICIAL": "Official",
        "TAKE_TWO_OFFICIAL": "Official",
        "OFFICIAL_VIDEO": "Official",
        "OFFICIAL_SOCIAL": "Official",
        "JOURNALISM": "Journalism",
        "DATABASE/REFERENCE": "Reference",
        "COMMUNITY": "Community",
        "RUMOR": "Community",
        "OTHER": "Other",
    }
    for source in sources:
        authority = str(source.get("authority_class") or "OTHER").upper()
        folder = source_folder.get(authority, "Other")
        files.append(_write(
            root,
            f"30-Sources/{folder}/{_slug(source['source_id'])}.md",
            _markdown(
                {
                    "source_id": source["source_id"],
                    "url": source["url"],
                    "domain": source["domain"],
                    "source_type": source["source_type"],
                    "authority_class": authority,
                    "reliability_score": source.get("reliability_score"),
                    "last_checked_at": source.get("last_checked_at"),
                    "last_changed_at": source.get("last_changed_at"),
                    "content_hash": source.get("content_hash"),
                    "refresh_priority": source.get("refresh_priority"),
                    "refresh_interval_seconds": source.get("refresh_interval_seconds"),
                    "active": source.get("active"),
                    "canonical_source": "BR_SQLITE",
                    "obsidian_authority": "NONE",
                },
                f"Source — {source['domain']}",
                "\n".join([
                    str(source["url"]),
                    "",
                    f"**Authority:** {authority}",
                    f"**Refresh state:** {source.get('refresh_state')}",
                    f"**Last changed:** {source.get('last_changed_at') or 'n/a'}",
                ]),
            ),
        ))

    frontier_links: list[str] = []
    for question in frontier:
        status = str(question.get("status") or "OPEN").upper()
        folder = (
            "Open-Questions"
            if status in {"OPEN", "INVESTIGATING", "STALE", "BLOCKED"}
            else "Resolved"
        )
        relative = f"40-Research/{folder}/{_slug(question['question_id'])}.md"
        frontier_links.append(
            f"- [[{relative[:-3]}|{question['question']}]] — "
            f"{status} · priority {question.get('priority')}"
        )
        files.append(_write(
            root,
            relative,
            _markdown(
                {
                    "question_id": question["question_id"],
                    "status": status,
                    "topic": question.get("topic"),
                    "entity_ids": question.get("entity_ids") or [],
                    "priority": question.get("priority"),
                    "current_confidence": question.get("current_confidence"),
                    "supporting_evidence": question.get("supporting_evidence") or [],
                    "contradictory_evidence": question.get("contradictory_evidence") or [],
                    "missing_evidence": question.get("missing_evidence") or [],
                    "sources_to_watch": question.get("sources_to_watch") or [],
                    "last_checked_at": question.get("last_checked_at"),
                    "canonical_source": "BR_SQLITE",
                    "obsidian_authority": "NONE",
                },
                str(question["question"]),
                "\n".join([
                    f"**Próxima estratégia:** "
                    f"{question.get('next_research_strategy') or 'não definida'}",
                    "",
                    "## Evidência faltante",
                    *(
                        [f"- {item}" for item in question.get("missing_evidence") or []]
                        or ["- nenhuma"]
                    ),
                ]),
            ),
        ))

    latest_run = daily_runs[0] if daily_runs else {}
    files.append(_write(
        root,
        "00-Brain/Dashboard.md",
        _markdown(
            {
                "brain": "GTA6_KNOWLEDGE_BRAIN",
                "authority": "DEEPSEEK_HARNESS",
                "canonical_memory": "BR_SQLITE",
                "obsidian_role": "LONG_TERM_HUMAN_KNOWLEDGE_VIEW",
                "generated_at": now,
                "entity_count": len(entities),
                "source_count": len(sources),
                "claim_count": len(claim_meta),
                "frontier_count": len(frontier),
            },
            "GTA6 Knowledge Brain",
            "\n".join([
                "Obsidian é projeção navegável; não é autoridade nem banco canônico.",
                "",
                f"- Entidades: **{len(entities)}**",
                f"- Claims enriquecidos: **{len(claim_meta)}**",
                f"- Fontes: **{len(sources)}**",
                f"- Frontier: **{len(frontier)}**",
                "",
                "[[Research-Frontier]] · [[Daily-Knowledge]] · "
                "[[50-Editorial/Opportunities]]",
            ]),
        ),
    ))
    files.append(_write(
        root,
        "00-Brain/Research-Frontier.md",
        _markdown(
            {"status": "INDEX", "generated_at": now, "question_count": len(frontier)},
            "Research Frontier",
            "\n".join(frontier_links) or "Nenhuma pergunta na Frontier.",
        ),
    ))
    files.append(_write(
        root,
        "00-Brain/Daily-Knowledge.md",
        _markdown(
            {
                "status": latest_run.get("status") or "NO_RUN",
                "daily_run_id": latest_run.get("run_id"),
                "generated_at": now,
            },
            "Daily Knowledge",
            "\n".join([
                f"Último run: **{latest_run.get('run_id') or 'nenhum'}**",
                f"Fontes verificadas: {latest_run.get('sources_checked', 0)}",
                f"Fontes alteradas: {latest_run.get('sources_changed', 0)}",
                f"Novos claims: {latest_run.get('new_claims', 0)}",
                f"Claims verificados: {latest_run.get('verified_claims', 0)}",
                f"Claims contraditos: {latest_run.get('contradicted_claims', 0)}",
                f"Duplicatas evitadas: {latest_run.get('duplicates_avoided', 0)}",
            ]),
        ),
    ))

    for relative, title, links in (
        ("50-Editorial/Never-Used.md", "Never Used", editorial_unused),
        ("50-Editorial/Used-In-Videos.md", "Used In Videos", editorial_used),
        ("50-Editorial/Opportunities.md", "Editorial Opportunities", editorial_opportunities),
    ):
        files.append(_write(
            root,
            relative,
            _markdown(
                {"status": "INDEX", "generated_at": now, "claim_count": len(links)},
                title,
                "\n".join(f"- {link}" for link in links)
                or "Nenhum claim nesta categoria.",
            ),
        ))
    return files
