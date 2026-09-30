from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence

from app.contracts.youtube_intelligence_contracts import (
    AudienceComplaintCluster,
    AudiencePraiseCluster,
    AudienceQuestionCluster,
    BRNoGTAEditorialMoat,
    EditorialGapMap,
)


MIN_COMPETITOR_CHANNELS=20
MIN_COMPETITOR_VIDEOS=50


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()
    ).hexdigest()


def evaluate_competitor_corpus(
    *,
    channels: Sequence[Mapping[str,Any]],
    videos: Sequence[Mapping[str,Any]],
    required_markets: Sequence[str]=("BR","GLOBAL"),
) -> dict[str,Any]:
    channel_ids={str(x.get("channel_id") or "") for x in channels if x.get("channel_id")}
    video_ids={str(x.get("video_id") or "") for x in videos if x.get("video_id")}
    markets={str(x.get("market") or "").upper() for x in channels}
    transcripts={
        str(x.get("video_id"))
        for x in videos
        if x.get("video_id") and x.get("transcript_ref")
    }
    comments={
        str(x.get("video_id"))
        for x in videos
        if x.get("video_id") and (x.get("comments_ref") or x.get("comment_sample_ref"))
    }
    requirements={
        "channel_count":len(channel_ids)>=MIN_COMPETITOR_CHANNELS,
        "video_count":len(video_ids)>=MIN_COMPETITOR_VIDEOS,
        "markets":all(m.upper() in markets for m in required_markets),
        "representative_transcripts":len(transcripts)>=min(10,max(1,len(video_ids)//5)),
        "representative_comments":len(comments)>=min(10,max(1,len(video_ids)//5)),
    }
    return {
        "schema":"YouTubeCompetitorCorpusEvaluation/v1",
        "channel_count":len(channel_ids),
        "video_count":len(video_ids),
        "markets":sorted(markets),
        "transcript_video_count":len(transcripts),
        "comment_video_count":len(comments),
        "requirements":requirements,
        "status":"PASS" if all(requirements.values()) else "INCOMPLETE",
        "no_unauthorized_scraping":True,
    }


def build_editorial_gap_map(
    *,
    topic: str,
    market: str,
    competitor_coverage: Sequence[str],
    missing_angles: Sequence[str],
    br_specific_gaps: Sequence[str],
    evidence_refs: Sequence[str],
) -> EditorialGapMap:
    if not evidence_refs:
        raise ValueError("editorial gap map requires evidence")
    return EditorialGapMap(
        topic=topic,
        market=market,
        competitor_coverage=tuple(competitor_coverage),
        missing_angles=tuple(missing_angles),
        br_specific_gaps=tuple(br_specific_gaps),
        observed_at=datetime.now(timezone.utc).isoformat(),
        evidence_refs=tuple(evidence_refs),
    )


def build_editorial_moat(
    *,
    strengths: Sequence[str],
    non_negotiables: Sequence[str],
    validated_by: Sequence[str],
    evidence_refs: Sequence[str],
) -> BRNoGTAEditorialMoat:
    status="VALIDATED" if len(validated_by)>=3 and evidence_refs else "CANDIDATE"
    return BRNoGTAEditorialMoat(
        strengths=tuple(strengths),
        non_negotiables=tuple(non_negotiables),
        validated_by=tuple(validated_by),
        evidence_refs=tuple(evidence_refs),
        status=status,
    )


def cluster_comment_intelligence(
    comments: Iterable[Mapping[str,Any]],
    *,
    evidence_prefix: str="youtube-comment",
) -> dict[str,Any]:
    """Deterministic seed clustering. Semantic clustering can challenge it later.

    This does not treat comments as GTA factual evidence; they are demand/satisfaction signals.
    """
    questions=[]
    complaints=[]
    praise=[]
    complaint_terms=("chato","lento","enrol","repet","ruim","confuso","demora","boring","slow","repetitive")
    praise_terms=("bom","ótimo","otimo","foda","excelente","detalhe","curti","love","great","amazing")
    for raw in comments:
        cid=str(raw.get("comment_id") or "").strip()
        text=str(raw.get("text") or "").strip()
        if not cid or not text:
            continue
        folded=text.casefold()
        ref=f"{evidence_prefix}:{cid}"
        item={"comment_id":cid,"text":text,"evidence_ref":ref}
        if "?" in text:
            questions.append(item)
        if any(term in folded for term in complaint_terms):
            complaints.append(item)
        if any(term in folded for term in praise_terms):
            praise.append(item)

    def _cluster_id(kind: str, rows: list[dict[str,Any]]) -> str:
        return f"{kind}-{_digest(rows)[:16]}"

    return {
        "schema":"YouTubeCommentIntelligence/v1",
        "comments_are_factual_gta_evidence":False,
        "question_cluster":asdict(AudienceQuestionCluster(
            cluster_id=_cluster_id("questions",questions),
            topic="AUDIENCE_QUESTIONS",
            question_count=len(questions),
            representative_comment_refs=tuple(x["evidence_ref"] for x in questions[:10]),
            next_video_demand=bool(questions),
            evidence_refs=tuple(x["evidence_ref"] for x in questions),
        )),
        "complaint_cluster":asdict(AudienceComplaintCluster(
            cluster_id=_cluster_id("complaints",complaints),
            topic="AUDIENCE_COMPLAINTS",
            complaint_count=len(complaints),
            representative_comment_refs=tuple(x["evidence_ref"] for x in complaints[:10]),
            category="VIEWER_EXPERIENCE",
            evidence_refs=tuple(x["evidence_ref"] for x in complaints),
        )),
        "praise_cluster":asdict(AudiencePraiseCluster(
            cluster_id=_cluster_id("praise",praise),
            topic="AUDIENCE_PRAISE",
            praise_count=len(praise),
            representative_comment_refs=tuple(x["evidence_ref"] for x in praise[:10]),
            category="VIEWER_SATISFACTION",
            evidence_refs=tuple(x["evidence_ref"] for x in praise),
        )),
    }
