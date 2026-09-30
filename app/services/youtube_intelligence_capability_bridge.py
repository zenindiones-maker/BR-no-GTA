from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from app.database import youtube_intelligence_repository as yt_repo
from app.services.global_capability_registry_base import (
    AVAILABLE,
    FUNCTIONAL,
    PARTIAL,
    CapabilityRecord,
)
from app.services.harness_authorization_service import validate_harness_authorization
from app.services.youtube_credential_broker_service import (
    YouTubeCredentialBrokerClient,
    YouTubeRemoteStateUnknown,
)


ROLE_EXECUTOR="app.services.youtube_intelligence_capability_bridge.execute_youtube_intelligence_role_capability"
PLATFORM_EXECUTOR="app.services.youtube_intelligence_capability_bridge.execute_youtube_platform_capability"
UPLOAD_EXECUTOR="app.services.youtube_intelligence_capability_bridge.execute_youtube_private_upload_capability"

ROLE_RESULT_SCHEMA="YouTubeIntelligenceRoleResult/v1"
PLATFORM_RESULT_SCHEMA="YouTubePlatformOperationResult/v1"

_ROLE_IDS=(
    "youtube.market-intelligence",
    "youtube.trend-scout",
    "youtube.audience-demand-analyst",
    "youtube.topic-opportunity-analyst",
    "youtube.title-strategist",
    "youtube.thumbnail-strategist",
    "youtube.packaging-reviewer",
    "youtube.hook-architect",
    "youtube.story-structure-analyst",
    "youtube.retention-analyst",
    "youtube.ad-suitability-reviewer",
    "youtube.monetization-analyst",
    "youtube.revenue-analyst",
    "youtube.catalog-strategist",
    "youtube.series-strategist",
    "youtube.session-growth-analyst",
    "youtube.analytics-scientist",
    "youtube.experiment-analyst",
    "youtube.postmortem-reviewer",
)

_PLATFORM_OPS={
    "youtube.data.read":("DATA_READ","READ_ONLY"),
    "youtube.video.metadata.update":("VIDEO_METADATA_UPDATE","EXTERNAL_MUTATION"),
    "youtube.thumbnail.set":("THUMBNAIL_SET","EXTERNAL_MUTATION"),
    "youtube.playlist.manage":("PLAYLIST_MANAGE","EXTERNAL_MUTATION"),
    "youtube.comment.read":("COMMENT_READ","READ_ONLY"),
    "youtube.comment.reply":("COMMENT_REPLY","EXTERNAL_MUTATION"),
    "youtube.reporting.read":("REPORTING_READ","READ_ONLY"),
}


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    ).hexdigest()


def youtube_intelligence_role_records() -> tuple[CapabilityRecord,...]:
    records=[]
    for capability_id in _ROLE_IDS:
        role=capability_id.split("youtube.",1)[1].upper().replace("-","_")
        records.append(CapabilityRecord(
            capability_id=capability_id,
            capability_type="CAPABILITY",
            domain="youtube-intelligence",
            implementation="Harness-subordinate YouTube intelligence functional role; filled by minimum sufficient proven executor coalition",
            input_contract="TaskExecutionEnvelope/v1 + evidence refs + role-specific typed inputs",
            output_contract=ROLE_RESULT_SCHEMA,
            requirements=(
                "DeepSeek Harness authorization",
                "task-local lease",
                "evidence-linked inputs",
                "no permanent agent identity required",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH","EDITORIAL","EXECUTION","DECISION"),
            policy_tags=("youtube","intelligence","role","subordinate","minimum-coalition"),
            security_boundary=(
                "DeepSeek Harness remains sole authority. This record declares a functional role, "
                "not a permanent autonomous agent; role execution cannot expand task scope, publish, "
                "write secrets, or promote learning."
            ),
            cost_class="MIXED",
            quota_class="TASK_BOUND",
            latency_class="TASK_DEPENDENT",
            quality_class="EVIDENCE_LINKED_ROLE",
            evidence_contract=ROLE_RESULT_SCHEMA,
            fallback_eligibility=False,
            executor_binding=ROLE_EXECUTOR,
            version="1",
            provider_id="internal",
            side_effects=(),
            authority="NONE",
            memory_write="FORBIDDEN",
            routing_authority="NONE",
            editorial_authority="NONE",
            publication_authority="NONE",
            supports_parallelism=True,
            supports_retry=True,
            supports_resume=True,
            supports_review="reviewer" in capability_id or "analyst" in capability_id,
            side_effect_class="READ_ONLY",
            default_read_scope=("youtube/intelligence","artifacts","brain/evidence"),
            default_write_scope=(),
            allowed_tools=(),
            health_policy="EVIDENCE_REQUIRED",
            execution_kind="DETERMINISTIC_ANALYSIS_AGENT",
            functional_roles=(role,),
            output_contract_ids=(ROLE_RESULT_SCHEMA,),
        ))
    return tuple(records)


def youtube_platform_capability_records() -> tuple[CapabilityRecord,...]:
    records=[]
    for capability_id,(operation,side_effect_class) in _PLATFORM_OPS.items():
        mutation=side_effect_class=="EXTERNAL_MUTATION"
        records.append(CapabilityRecord(
            capability_id=capability_id,
            capability_type="EXECUTOR",
            domain="youtube-platform",
            implementation="Harness-authorized official YouTube API operation through opaque credential broker",
            input_contract="persisted Harness authorization + task id + exact resource binding + bounded official API request",
            output_contract=PLATFORM_RESULT_SCHEMA,
            requirements=(
                "official YouTube API only",
                "YouTubeCredentialBroker/v1",
                "least-privilege OAuth operation scope",
                "durable external-operation outbox" if mutation else "read-only remote request",
            ),
            maturity=PARTIAL if mutation else FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("youtube","official-api","oauth","credential-broker","least-privilege"),
            security_boundary=(
                "DeepSeek Harness authorization + task-local opaque credential handle. "
                "No refresh/access token enters model context or artifacts. External mutations "
                "persist intent before the call and stop on UNKNOWN_REMOTE_STATE."
            ),
            cost_class="FREE_API_QUOTA",
            quota_class="GOOGLE_API_QUOTA",
            latency_class="REMOTE_API",
            quality_class="OFFICIAL_API_BROKER_BOUNDARY",
            evidence_contract=PLATFORM_RESULT_SCHEMA,
            fallback_eligibility=False,
            executor_binding=PLATFORM_EXECUTOR,
            version="1",
            provider_id="google-youtube",
            side_effects=("YouTube remote mutation",) if mutation else (),
            authority="NONE",
            memory_write="FORBIDDEN",
            routing_authority="NONE",
            editorial_authority="NONE",
            publication_authority="NONE",
            supports_parallelism=not mutation,
            supports_retry=not mutation,
            supports_resume=True,
            supports_review=False,
            side_effect_class=side_effect_class,
            default_read_scope=("youtube:authorized-resource",),
            default_write_scope=("youtube:exact-target",) if mutation else (),
            allowed_tools=("youtube-credential-broker",),
            health_policy="BROKER_REQUIRED",
            execution_kind="MUTATION_EXECUTOR" if mutation else "TOOL",
            functional_roles=("YOUTUBE_PLATFORM",),
            output_contract_ids=(PLATFORM_RESULT_SCHEMA,),
        ))

    records.append(CapabilityRecord(
        capability_id="youtube.video.upload",
        capability_type="EXECUTOR",
        domain="youtube-publication",
        implementation="Existing Harness-governed cloud PRIVATE upload path",
        input_contract="canonical publication_id + QA-proven master + PRIVATE visibility",
        output_contract="private YouTube upload execution receipt",
        requirements=(
            "DeepSeek Harness authorization",
            "canonical publication",
            "QA-proven master",
            "PRIVATE visibility only",
            "existing cloud upload durable execution",
        ),
        maturity=FUNCTIONAL,
        availability=AVAILABLE,
        allowed_actions=("EXECUTION","PUBLICATION"),
        policy_tags=("youtube","upload","private-first","human-review"),
        security_boundary=(
            "PRIVATE upload only. Public publication remains a distinct capability and human gate. "
            "No caller may alter visibility during upload."
        ),
        cost_class="FREE_API_QUOTA",
        quota_class="YOUTUBE_VIDEO_INSERT",
        latency_class="REMOTE_MEDIA_UPLOAD",
        quality_class="QA_BOUND_PRIVATE_UPLOAD",
        evidence_contract="YouTubeCloudExecution/v1",
        fallback_eligibility=False,
        executor_binding=UPLOAD_EXECUTOR,
        version="1",
        provider_id="google-youtube",
        side_effects=("YouTube PRIVATE upload",),
        authority="NONE",
        memory_write="FORBIDDEN",
        routing_authority="NONE",
        editorial_authority="NONE",
        publication_authority="PRIVATE_ONLY",
        supports_parallelism=False,
        supports_retry=False,
        supports_resume=True,
        supports_review=False,
        side_effect_class="EXTERNAL_MUTATION",
        default_read_scope=("youtube:publication",),
        default_write_scope=("youtube:private-upload",),
        allowed_tools=("youtube-cloud-upload",),
        health_policy="QA_AND_CLOUD_AUTH_REQUIRED",
        execution_kind="MUTATION_EXECUTOR",
        functional_roles=("YOUTUBE_UPLOAD",),
        output_contract_ids=("YouTubeCloudExecution/v1",),
    ))
    return tuple(records)


def youtube_intelligence_capability_records() -> tuple[CapabilityRecord,...]:
    return (*youtube_intelligence_role_records(),*youtube_platform_capability_records())


def _validate_authorization(capability: Any,payload: Mapping[str,Any]) -> Any:
    capability_id=str(getattr(capability,"capability_id","") or "")
    authorization_ref=str(payload.get("authorization_ref") or "").strip()
    task_id=str(payload.get("task_id") or "").strip()
    if not authorization_ref or not task_id:
        raise PermissionError("Harness authorization_ref and task_id are required")
    auth=validate_harness_authorization(
        authorization_ref,
        expected_action="EXECUTION",
        expected_subject=f"capability:{capability_id}",
    )
    lineage=dict(auth.lineage or {})
    if lineage.get("capability_id") not in (None,capability_id):
        raise PermissionError("Harness authorization capability lineage mismatch")
    return auth


def execute_youtube_intelligence_role_capability(
    capability: Any,
    payload: Mapping[str,Any],
) -> dict[str,Any]:
    capability_id=str(getattr(capability,"capability_id","") or "")
    if capability_id not in _ROLE_IDS:
        raise PermissionError("unknown YouTube intelligence role capability")
    auth=_validate_authorization(capability,payload)
    evidence_refs=tuple(dict.fromkeys(str(x) for x in (payload.get("evidence_refs") or ()) if str(x)))
    if not evidence_refs:
        raise ValueError("YouTube intelligence role requires evidence refs")
    return {
        "schema":ROLE_RESULT_SCHEMA,
        "capability_id":capability_id,
        "task_id":str(payload["task_id"]),
        "authorization_id":auth.authorization_id,
        "authority":"DEEPSEEK_HARNESS",
        "role_is_permanent_agent":False,
        "scope_expansion_allowed":False,
        "publication_authority":"NONE",
        "learning_promotion_authority":"NONE",
        "evidence_refs":list(evidence_refs),
        "input_digest":_digest(dict(payload.get("input") or {})),
        "result":dict(payload.get("candidate_result") or {}),
        "returned_to_harness":True,
    }


def execute_youtube_private_upload_capability(
    capability: Any,
    payload: Mapping[str,Any],
) -> dict[str,Any]:
    if getattr(capability,"capability_id",None)!="youtube.video.upload":
        raise PermissionError("private upload capability mismatch")
    _validate_authorization(capability,payload)
    if str(payload.get("visibility") or "PRIVATE").upper()!="PRIVATE":
        raise PermissionError("upload capability is PRIVATE-only")
    publication_id=payload.get("publication_id")
    if isinstance(publication_id,bool) or not isinstance(publication_id,int) or publication_id<=0:
        raise ValueError("positive publication_id is required")
    from app.services.youtube_cloud_upload_service import (
        dispatch_targeted_private_upload,
    )
    return dispatch_targeted_private_upload(publication_id)


def execute_youtube_platform_capability(
    capability: Any,
    payload: Mapping[str,Any],
    *,
    broker: YouTubeCredentialBrokerClient | None=None,
) -> dict[str,Any]:
    capability_id=str(getattr(capability,"capability_id","") or "")
    spec=_PLATFORM_OPS.get(capability_id)
    if spec is None:
        raise PermissionError("unknown YouTube platform capability")
    operation,side_effect_class=spec
    auth=_validate_authorization(capability,payload)
    task_id=str(payload["task_id"])
    resource_binding=dict(payload.get("resource_binding") or {})
    request_payload=dict(payload.get("request") or {})
    target=str(payload.get("target") or resource_binding.get("video_id") or resource_binding.get("channel_id") or "youtube")
    if not resource_binding:
        raise ValueError("exact resource_binding is required")

    broker=broker or YouTubeCredentialBrokerClient()
    handle=broker.request_handle(
        operation=operation,
        authorization_ref=auth.authorization_id,
        task_id=task_id,
        resource_binding=resource_binding,
    )
    payload_digest=_digest(request_payload)
    operation_id=f"yt-op-{sha256((auth.authorization_id+'|'+operation+'|'+target+'|'+payload_digest).encode()).hexdigest()[:24]}"

    if side_effect_class=="EXTERNAL_MUTATION":
        existing=yt_repo.get_external_operation(operation_id)
        if existing is not None:
            if existing["state"]=="CONFIRMED":
                return {
                    "schema":PLATFORM_RESULT_SCHEMA,
                    "capability_id":capability_id,
                    "operation_id":operation_id,
                    "state":"CONFIRMED",
                    "remote_receipt":existing["remote_receipt"],
                    "replayed_from_durable_receipt":True,
                }
            if existing["state"]=="UNKNOWN_REMOTE_STATE":
                raise YouTubeRemoteStateUnknown(
                    "existing operation has UNKNOWN_REMOTE_STATE; blind resend forbidden"
                )
            raise PermissionError(f"operation is not safely retryable from {existing['state']}")

        yt_repo.create_external_operation(
            operation_id=operation_id,
            capability_id=capability_id,
            authorization_ref=auth.authorization_id,
            operation=operation,
            target=target,
            payload_digest=payload_digest,
            payload=request_payload,
        )
        yt_repo.update_external_operation(operation_id,state="SENT")
        try:
            receipt=broker.execute(
                handle=handle,operation_id=operation_id,
                payload_digest=payload_digest,payload=request_payload,
            )
        except YouTubeRemoteStateUnknown as exc:
            yt_repo.update_external_operation(
                operation_id,state="UNKNOWN_REMOTE_STATE",last_error=str(exc)
            )
            raise
        confirmed=yt_repo.update_external_operation(
            operation_id,state="CONFIRMED",remote_receipt=receipt
        )
        return {
            "schema":PLATFORM_RESULT_SCHEMA,
            "capability_id":capability_id,
            "operation_id":operation_id,
            "state":"CONFIRMED",
            "remote_receipt":confirmed["remote_receipt"],
            "replayed_from_durable_receipt":False,
        }

    receipt=broker.execute(
        handle=handle,operation_id=operation_id,
        payload_digest=payload_digest,payload=request_payload,
    )
    return {
        "schema":PLATFORM_RESULT_SCHEMA,
        "capability_id":capability_id,
        "operation_id":operation_id,
        "state":"CONFIRMED_READ",
        "remote_receipt":receipt,
    }
