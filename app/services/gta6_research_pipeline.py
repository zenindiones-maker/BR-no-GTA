from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from app.services.gta6_news_pipeline import run_gta6_news_pipeline
from app.services.gta6_rockstar_monitor_service import (
    monitor_rockstar_newswire,
)
from app.services.gta6_rockstar_monitor_ingestion import (
    ingest_rockstar_newswire_from_monitor,
)
from app.services.gta6_source_ingestion import (
    ingest_rockstar_newswire,
)
from app.services.gta6_editorial_pipeline import (
    process_gta6_research_results,
)
from app.settings import settings
from app.services.harness_authorization_service import (
    authorization_to_context,
    validate_harness_authorization,
)
from app.services.gta6_knowledge_retrieval_service import retrieve_gta6_knowledge
from app.database.research_repository import get_research_item
from app.services.gta6_source_registry_service import (
    classify_gta6_source,
    register_gta6_source,
)


def run_gta6_research(
    execution_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Executa pesquisa GTA6 somente sob autorização persistida do Harness."""

    context = execution_context or {}
    execution_id = context.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise PermissionError("Harness execution_id is required for RESEARCH")

    authorization = validate_harness_authorization(
        context,
        expected_action="RESEARCH",
        expected_subject="action:RESEARCH",
        expected_execution_id=execution_id,
    )
    execution_context = authorization_to_context(authorization)
    retrieval_query = str(
        context.get("query")
        or context.get("topic")
        or context.get("subject")
        or "GTA VI current developments"
    )
    existing_knowledge = retrieve_gta6_knowledge(
        query=retrieval_query,
        limit=12,
        max_context_bytes=24 * 1024,
        include_history=False,
    )
    research_gap = {
        "query": retrieval_query,
        "existing_units": len(existing_knowledge.get("knowledge_units") or ()),
        "bounded_context_bytes": existing_knowledge.get("context_bytes"),
        "strategy": "DELTA_ONLY_AFTER_CANONICAL_RETRIEVAL",
        "research_required": True,
    }

    rockstar_monitor = monitor_rockstar_newswire()

    rockstar_items = ingest_rockstar_newswire_from_monitor()

    if settings.ROCKSTAR_QUERY_HASH:
        rockstar_items.extend(
            ingest_rockstar_newswire(
                settings.ROCKSTAR_QUERY_HASH
            )
        )

    news_items = run_gta6_news_pipeline()

    discovered_sources: list[dict[str, Any]] = []
    for item in [*rockstar_items, *news_items]:
        url = str(
            item.get("url")
            or item.get("source_url")
            or item.get("canonical_url")
            or ""
        ).strip()
        if not url.startswith("https://"):
            continue
        source_type = str(item.get("source_type") or "OTHER")
        classification = classify_gta6_source(
            url=url,
            source_type=source_type,
        )
        source_id = "research-source-" + sha256(
            url.encode("utf-8")
        ).hexdigest()[:24]
        try:
            registered = register_gta6_source(
                source_id=source_id,
                url=url,
                source_type=source_type,
                discovered_at=str(
                    item.get("published_at")
                    or item.get("observed_at")
                    or datetime.now(timezone.utc).isoformat()
                ),
                provenance={
                    "origin": "gta6_research_pipeline",
                    "execution_id": execution_id,
                    "authority": authorization.authority,
                },
                declared_authority=classification.authority_class,
                refresh_state="DUE",
            )
            discovered_sources.append(registered)
        except Exception:
            # Source registry enrichment must never corrupt canonical research.
            continue

    research_results = [
        *rockstar_items,
        *news_items,
    ]

    editorial = process_gta6_research_results(
        research_results,
    )

    official_research_items: list[dict[str, Any]] = []
    seen_official_ids: set[int] = set()
    for row in rockstar_items:
        research_item_id = row.get("research_item_id") if isinstance(row, dict) else None
        if (
            not isinstance(research_item_id, int)
            or research_item_id <= 0
            or research_item_id in seen_official_ids
        ):
            continue
        resolved = get_research_item(research_item_id)
        if isinstance(resolved, dict):
            official_research_items.append(dict(resolved))
            seen_official_ids.add(research_item_id)

    evidence_refs = list(dict.fromkeys(
        str(
            item.get("url")
            or item.get("source_url")
            or item.get("canonical_url")
            or ""
        ).strip()
        for item in research_results
        if str(
            item.get("url")
            or item.get("source_url")
            or item.get("canonical_url")
            or ""
        ).strip()
    ))

    return {
        "artifact_ref": f"research-execution:{execution_id}",
        "evidence_refs": evidence_refs[:48],
        "existing_knowledge": existing_knowledge,
        "research_gap": research_gap,
        "discovered_sources": discovered_sources,
        "KNOWLEDGE_RETRIEVED_BEFORE_RESEARCH": "PASS",
        "rockstar_monitor": rockstar_monitor,
        "rockstar_newswire": rockstar_items,
        "official_research_items": official_research_items,
        "news_feeds": news_items,
        "total": len(rockstar_items) + len(news_items),
        "editorial": editorial,
    }
