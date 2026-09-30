from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from app.contracts.youtube_intelligence_contracts import (
    SyntheticMediaDisclosureDecision,
    YouTubePublicationSpec,
)
from app.services.youtube_platform_foundation_service import decide_synthetic_media_disclosure


def build_youtube_publication_spec(
    *,
    video_id: str,
    master_artifact_sha: str,
    title: str,
    description: str,
    thumbnail_ref: str,
    language: str,
    category: str | None,
    playlist: str | None,
    series: str | None,
    chapters: Sequence[Mapping[str,Any]],
    privacy: str="PRIVATE",
    publish_at: str | None=None,
    monetization_intent: str="UNKNOWN",
    contains_synthetic_media: bool | None=None,
    synthetic_media_disclosure_decision: SyntheticMediaDisclosureDecision | Mapping[str,Any] | None=None,
    originality_review_ref: str | None=None,
    ypp_transformative_value_status: str="UNKNOWN",
    related_videos: Sequence[str]=(),
    end_screen_plan: Mapping[str,Any] | None=None,
    cards_plan: Sequence[Mapping[str,Any]]=(),
    comment_strategy: Mapping[str,Any] | None=None,
    human_approval_ref: str | None=None,
    evidence_refs: Sequence[str]=(),
) -> YouTubePublicationSpec:
    privacy=str(privacy or "").upper()
    if privacy not in {"PRIVATE","UNLISTED","PUBLIC"}:
        raise ValueError("unsupported YouTube privacy status")
    if privacy != "PRIVATE" and not human_approval_ref:
        raise PermissionError("non-PRIVATE publication spec requires explicit human approval")
    if len(str(master_artifact_sha))!=64:
        raise ValueError("publication spec requires exact master artifact SHA-256")
    if not title.strip() or not thumbnail_ref.strip():
        raise ValueError("publication spec requires title and thumbnail")
    if language!="pt-BR":
        raise ValueError("BR-no-GTA canonical publication language is pt-BR")

    if synthetic_media_disclosure_decision is None:
        if contains_synthetic_media is True:
            raise PermissionError(
                "synthetic media disclosure decision is required when synthetic media is present"
            )
        synthetic_media_disclosure_decision = decide_synthetic_media_disclosure(
            realistic_media=False,
            meaningfully_altered_or_generated=False,
            uncertain=contains_synthetic_media is None,
            rationale=(
                "explicitly declared no realistic synthetic media"
                if contains_synthetic_media is False
                else "master disclosure state not yet resolved"
            ),
        )
    disclosure = (
        synthetic_media_disclosure_decision.to_dict()
        if hasattr(synthetic_media_disclosure_decision, "to_dict")
        else dict(synthetic_media_disclosure_decision)
    )
    decision = str(disclosure.get("decision") or "")
    if decision not in {"NOT_REQUIRED","REQUIRED","UNCERTAIN_REVIEW_REQUIRED"}:
        raise ValueError("invalid synthetic media disclosure decision")
    if decision == "REQUIRED":
        contains_synthetic_media = True
    elif decision == "NOT_REQUIRED":
        contains_synthetic_media = False

    ypp_status = str(ypp_transformative_value_status or "UNKNOWN").upper()
    if privacy != "PRIVATE":
        if not originality_review_ref or ypp_status != "PASS":
            raise PermissionError(
                "non-PRIVATE publication requires originality review with YPP transformative value PASS"
            )
        if decision == "UNCERTAIN_REVIEW_REQUIRED":
            raise PermissionError(
                "non-PRIVATE publication requires resolved synthetic media disclosure"
            )
    return YouTubePublicationSpec(
        video_id=str(video_id),
        master_artifact_sha=str(master_artifact_sha).lower(),
        title=title.strip(),
        description=str(description),
        thumbnail_ref=thumbnail_ref,
        language=language,
        category=category,
        playlist=playlist,
        series=series,
        chapters=tuple(dict(x) for x in chapters),
        privacy=privacy,
        publish_at=publish_at,
        monetization_intent=monetization_intent,
        contains_synthetic_media=contains_synthetic_media,
        synthetic_media_disclosure=disclosure,
        originality_review_ref=originality_review_ref,
        ypp_transformative_value_status=ypp_status,
        related_videos=tuple(str(x) for x in related_videos),
        end_screen_plan=dict(end_screen_plan or {}),
        cards_plan=tuple(dict(x) for x in cards_plan),
        comment_strategy=dict(comment_strategy or {}),
        human_approval_ref=human_approval_ref,
        evidence_refs=tuple(evidence_refs),
    )


def publication_spec_to_private_upload(spec: YouTubePublicationSpec) -> dict[str,Any]:
    if spec.privacy!="PRIVATE":
        raise PermissionError("initial BR-no-GTA upload must remain PRIVATE")
    return {
        "schema":"YouTubePrivateUploadIntent/v1",
        "video_id":spec.video_id,
        "artifact_sha":spec.master_artifact_sha,
        "title":spec.title,
        "description":spec.description,
        "thumbnail_ref":spec.thumbnail_ref,
        "privacy":"PRIVATE",
        "human_review_required":True,
        "public_transition_authorized":False,
        "evidence_refs":list(spec.evidence_refs),
    }


def validate_publication_spec_against_master(
    spec: YouTubePublicationSpec,
    *,
    observed_master_sha: str,
    master_qa_status: str,
    duration_seconds: float,
) -> dict[str,Any]:
    if str(observed_master_sha).lower()!=spec.master_artifact_sha:
        raise PermissionError("publication spec/master SHA mismatch")
    if str(master_qa_status).upper()!="PASS":
        raise PermissionError("publication requires MASTER QA PASS")
    if float(duration_seconds)<20*60:
        raise PermissionError("publication violates BR-no-GTA >=20 minute final gate")
    return {
        "schema":"YouTubePublicationSpecValidation/v1",
        "video_id":spec.video_id,
        "master_sha_match":True,
        "master_qa_status":"PASS",
        "duration_gate":"PASS",
        "private_first":spec.privacy=="PRIVATE",
        "human_review_required":True,
        "status":"PASS",
    }
