from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from app.database.youtube_intelligence_repository import persist_intelligence_record
from app.contracts.youtube_intelligence_contracts import (
    CompetitorVideoObservation,
    YouTubeCompetitorProfile,
)
from app.services.youtube_quota_service import consume_quota


DATA_READ_CAPABILITY="youtube.data.read"
OFFICIAL_INTERFACE="YouTube Data API v3"


def _request_digest(payload: Mapping[str,Any]) -> str:
    return sha256(
        json.dumps(dict(payload),sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode("utf-8")
    ).hexdigest()


def search_youtube_official(
    *,
    service: Any,
    query: str,
    region_code: str | None=None,
    relevance_language: str | None=None,
    max_results: int=25,
    page_token: str | None=None,
    cache_lookup: Callable[[str],dict[str,Any] | None] | None=None,
    cache_store: Callable[[str,dict[str,Any]],None] | None=None,
    hard_daily_search_limit: int | None=None,
) -> dict[str,Any]:
    query=str(query or "").strip()
    if not query:
        raise ValueError("search query is required")
    if max_results < 1 or max_results > 50:
        raise ValueError("max_results must be in [1,50]")
    identity={
        "q":query,"type":"video","part":"snippet","maxResults":max_results,
        "regionCode":region_code,"relevanceLanguage":relevance_language,
        "pageToken":page_token,
    }
    digest=_request_digest(identity)
    cached=cache_lookup(digest) if cache_lookup else None
    consume_quota(
        api="youtube_data",operation="search.list",
        request_identity=identity,
        hard_limit=hard_daily_search_limit,
        priority=70,
        cache_state="HIT" if cached is not None else "MISS",
    )
    if cached is not None:
        return {**cached,"cache_state":"HIT","request_digest":digest}

    kwargs={k:v for k,v in identity.items() if v not in (None,"")}
    response=service.search().list(**kwargs).execute()
    if not isinstance(response,dict):
        raise RuntimeError("YouTube Data API search returned invalid response")
    result={
        "schema":"YouTubeOfficialSearchResult/v1",
        "source":"youtube_data_api_v3",
        "query":query,
        "items":list(response.get("items") or ()),
        "next_page_token":response.get("nextPageToken"),
        "retrieved_at":datetime.now(timezone.utc).isoformat(),
        "cache_state":"MISS",
        "request_digest":digest,
    }
    if cache_store:
        cache_store(digest,result)
    return result


def fetch_videos_official(
    *,
    service: Any,
    video_ids: list[str] | tuple[str,...],
    cache_lookup: Callable[[str],dict[str,Any] | None] | None=None,
    cache_store: Callable[[str,dict[str,Any]],None] | None=None,
) -> dict[str,Any]:
    ids=tuple(dict.fromkeys(str(x).strip() for x in video_ids if str(x).strip()))
    if not ids:
        raise ValueError("video_ids are required")
    if len(ids)>50:
        raise ValueError("YouTube videos.list supports at most 50 ids per request")
    identity={"id":",".join(ids),"part":"snippet,contentDetails,statistics,status"}
    digest=_request_digest(identity)
    cached=cache_lookup(digest) if cache_lookup else None
    consume_quota(
        api="youtube_data",operation="videos.list",
        request_identity=identity,
        priority=80,
        cache_state="HIT" if cached is not None else "MISS",
    )
    if cached is not None:
        return {**cached,"cache_state":"HIT","request_digest":digest}
    response=service.videos().list(**identity).execute()
    if not isinstance(response,dict):
        raise RuntimeError("YouTube Data API videos.list returned invalid response")
    result={
        "schema":"YouTubeOfficialVideoBatch/v1",
        "source":"youtube_data_api_v3",
        "items":list(response.get("items") or ()),
        "retrieved_at":datetime.now(timezone.utc).isoformat(),
        "cache_state":"MISS",
        "request_digest":digest,
    }
    if cache_store:
        cache_store(digest,result)
    return result


def normalize_competitor_profile(
    *, channel: Mapping[str,Any], market: str, segment: str, evidence_refs: tuple[str,...]
) -> YouTubeCompetitorProfile:
    snippet=dict(channel.get("snippet") or {})
    return YouTubeCompetitorProfile(
        channel_id=str(channel.get("id") or ""),
        channel_name=str(snippet.get("title") or ""),
        market=market,
        segment=segment,
        observed_at=datetime.now(timezone.utc).isoformat(),
        evidence_refs=evidence_refs,
    )


def normalize_competitor_video(
    *, video: Mapping[str,Any], evidence_refs: tuple[str,...],
    transcript_ref: str | None=None, comments_ref: str | None=None
) -> CompetitorVideoObservation:
    snippet=dict(video.get("snippet") or {})
    stats=dict(video.get("statistics") or {})
    duration=None
    # Keep duration raw if parser is not present; do not invent seconds.
    raw_duration=(video.get("contentDetails") or {}).get("duration")
    view_count=None
    raw_views=stats.get("viewCount")
    if raw_views not in (None,""):
        try:
            view_count=int(raw_views)
        except (TypeError,ValueError):
            view_count=None
    return CompetitorVideoObservation(
        video_id=str(video.get("id") or ""),
        channel_id=str(snippet.get("channelId") or ""),
        title=str(snippet.get("title") or ""),
        published_at=str(snippet.get("publishedAt") or ""),
        duration_seconds=duration,
        view_count=view_count,
        transcript_ref=transcript_ref,
        comments_ref=comments_ref,
        observed_at=datetime.now(timezone.utc).isoformat(),
        evidence_refs=(*evidence_refs,*( (f"youtube:contentDetails:duration:{raw_duration}",) if raw_duration else () )),
    )


def persist_competitor_observation(record: YouTubeCompetitorProfile | CompetitorVideoObservation) -> dict[str,Any]:
    subject_type="channel" if isinstance(record,YouTubeCompetitorProfile) else "video"
    subject_id=record.channel_id if subject_type=="channel" else record.video_id
    return persist_intelligence_record(
        schema_name=record.schema,subject_type=subject_type,subject_id=subject_id,
        payload=record.to_dict(),evidence_refs=record.evidence_refs,
        source_system=OFFICIAL_INTERFACE,
        retrieved_at=getattr(record,"observed_at",None),
    )
