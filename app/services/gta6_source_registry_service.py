from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Any

from app.database import gta6_brain_repository as brain_repository


AUTHORITY_CLASSES = frozenset({
    "ROCKSTAR_OFFICIAL",
    "TAKE_TWO_OFFICIAL",
    "OFFICIAL_VIDEO",
    "OFFICIAL_SOCIAL",
    "JOURNALISM",
    "DATABASE/REFERENCE",
    "COMMUNITY",
    "RUMOR",
    "OTHER",
})

_OFFICIAL_SOCIAL_HOSTS = {
    "x.com",
    "twitter.com",
    "instagram.com",
    "facebook.com",
    "threads.net",
}
_VIDEO_HOSTS = {
    "youtube.com",
    "youtu.be",
}
_COMMUNITY_HOSTS = {
    "reddit.com",
    "gtaforums.com",
    "discord.com",
}
_REFERENCE_HOSTS = {
    "imdb.com",
    "wikipedia.org",
    "wikidata.org",
}
_JOURNALISM_HOSTS = {
    "ign.com",
    "gamespot.com",
    "eurogamer.net",
    "polygon.com",
    "theverge.com",
    "bloomberg.com",
    "reuters.com",
    "gamesindustry.biz",
}


@dataclass(frozen=True)
class SourceClassification:
    authority_class: str
    reliability_score: float
    refresh_priority: int
    refresh_interval_seconds: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_class": self.authority_class,
            "reliability_score": self.reliability_score,
            "refresh_priority": self.refresh_priority,
            "refresh_interval_seconds": self.refresh_interval_seconds,
        }


def _host(url: str) -> str:
    return (urlparse(str(url or "")).hostname or "").casefold().removeprefix("www.")


def _host_matches(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def classify_gta6_source(
    *,
    url: str,
    source_type: str = "",
    declared_authority: str | None = None,
) -> SourceClassification:
    host = _host(url)
    source_kind = str(source_type or "").upper()
    declared = str(declared_authority or "").upper().strip()

    if host == "rockstargames.com" or host.endswith(".rockstargames.com"):
        authority = "ROCKSTAR_OFFICIAL"
    elif (
        host == "take2games.com"
        or host.endswith(".take2games.com")
        or host == "take-two.com"
        or host.endswith(".take-two.com")
    ):
        authority = "TAKE_TWO_OFFICIAL"
    elif _host_matches(host, _VIDEO_HOSTS) and (
        source_kind in {"OFFICIAL_VIDEO", "PRIMARY_SOURCE", "OFFICIAL"}
        or declared == "OFFICIAL_VIDEO"
    ):
        authority = "OFFICIAL_VIDEO"
    elif _host_matches(host, _OFFICIAL_SOCIAL_HOSTS) and (
        source_kind in {"OFFICIAL_SOCIAL", "PRIMARY_SOURCE", "OFFICIAL"}
        or declared == "OFFICIAL_SOCIAL"
    ):
        authority = "OFFICIAL_SOCIAL"
    elif declared == "RUMOR" or source_kind == "RUMOR":
        authority = "RUMOR"
    elif _host_matches(host, _COMMUNITY_HOSTS) or source_kind == "COMMUNITY":
        authority = "COMMUNITY"
    elif _host_matches(host, _REFERENCE_HOSTS) or source_kind in {
        "DATABASE",
        "REFERENCE",
        "DATABASE/REFERENCE",
    }:
        authority = "DATABASE/REFERENCE"
    elif _host_matches(host, _JOURNALISM_HOSTS) or source_kind == "JOURNALISM":
        authority = "JOURNALISM"
    else:
        # A self-declared authority never upgrades an unknown domain to an
        # official class. Officiality is domain/content-bound evidence.
        authority = "OTHER"

    policy = {
        "ROCKSTAR_OFFICIAL": (1.00, 100, 6 * 3600),
        "TAKE_TWO_OFFICIAL": (1.00, 100, 6 * 3600),
        "OFFICIAL_VIDEO": (0.98, 95, 6 * 3600),
        "OFFICIAL_SOCIAL": (0.95, 90, 6 * 3600),
        "JOURNALISM": (0.72, 70, 12 * 3600),
        "DATABASE/REFERENCE": (0.62, 45, 7 * 86400),
        "COMMUNITY": (0.35, 35, 24 * 3600),
        "RUMOR": (0.15, 25, 24 * 3600),
        "OTHER": (0.45, 40, 24 * 3600),
    }
    reliability, priority, interval = policy[authority]
    return SourceClassification(
        authority_class=authority,
        reliability_score=reliability,
        refresh_priority=priority,
        refresh_interval_seconds=interval,
    )


def register_gta6_source(
    *,
    source_id: str,
    url: str,
    source_type: str,
    discovered_at: str,
    provenance: dict[str, Any],
    declared_authority: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    classification = classify_gta6_source(
        url=url,
        source_type=source_type,
        declared_authority=declared_authority,
    )
    host = _host(url)
    return brain_repository.upsert_source({
        "source_id": source_id,
        "url": url,
        "domain": host,
        "source_type": source_type,
        **classification.to_dict(),
        "discovered_at": discovered_at,
        "active": True,
        "refresh_state": "NEW",
        "provenance": dict(provenance or {}),
        **overrides,
    })
