from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


GTA6_FACT_TYPES = {
    "news",
    "gameplay",
    "feature",
    "release",
    "update",
    "rumor",
    "community",
    "culture",
}

GTA6_CONFIDENCE_LEVELS = {
    "confirmed",
    "probable",
    "unconfirmed",
    "rumor",
}


@dataclass(frozen=True)
class GTA6KnowledgeItem:
    title: str
    summary: str
    source_name: str
    source_url: str
    fact_type: str
    confidence: str
    published_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title is required")

        if not isinstance(self.summary, str):
            raise ValueError("summary must be a string")

        if not isinstance(self.source_name, str) or not self.source_name.strip():
            raise ValueError("source_name is required")

        if not isinstance(self.source_url, str) or not self.source_url.strip():
            raise ValueError("source_url is required")

        if self.fact_type not in GTA6_FACT_TYPES:
            raise ValueError(
                f"invalid GTA6 fact type: {self.fact_type}"
            )

        if self.confidence not in GTA6_CONFIDENCE_LEVELS:
            raise ValueError(
                f"invalid GTA6 confidence: {self.confidence}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "fact_type": self.fact_type,
            "confidence": self.confidence,
            "published_at": self.published_at,
        }


def create_gta6_knowledge_item(
    *,
    title: str,
    summary: str,
    source_name: str,
    source_url: str,
    fact_type: str,
    confidence: str,
    published_at: str | None = None,
) -> GTA6KnowledgeItem:
    return GTA6KnowledgeItem(
        title=title,
        summary=summary,
        source_name=source_name,
        source_url=source_url,
        fact_type=fact_type,
        confidence=confidence,
        published_at=published_at,
    )


def create_gta6_research_item(
    *,
    title: str,
    summary: str,
    source_name: str,
    source_url: str,
    fact_type: str = "news",
    confidence: str = "unconfirmed",
    published_at: str | None = None,
) -> GTA6KnowledgeItem:
    if published_at is None:
        published_at = datetime.now(timezone.utc).isoformat()

    return create_gta6_knowledge_item(
        title=title,
        summary=summary,
        source_name=source_name,
        source_url=source_url,
        fact_type=fact_type,
        confidence=confidence,
        published_at=published_at,
    )
