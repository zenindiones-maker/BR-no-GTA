from __future__ import annotations

from dataclasses import replace

from app.services.global_capability_registry_base import *  # noqa: F401,F403
from app.services.global_capability_registry_base import (
    AVAILABLE,
    FUNCTIONAL,
    PARTIAL,
    PROVEN,
    CapabilityRecord,
    GLOBAL_CAPABILITY_REGISTRY as _REGISTRY,
)

AGENT_OFFICE_RECORD = CapabilityRecord(
    capability_id="agent-office.execute",
    capability_type="EXECUTOR",
    domain="development",
    implementation=(
        "Harness-subordinated headless Munder Difflin Agent Office coordinator"
    ),
    input_contract="AgentOfficeExecutionSpec + bounded AgentOfficeTask list",
    output_contract=(
        "AgentOfficeExecutionResult + CapabilityEvidence/CanonicalExecutionResult"
    ),
    requirements=(
        "persisted Harness DEVELOPMENT authorization",
        "Harness Routing/Policy decision",
        "pinned Munder Difflin upstream commit",
        "existing Codex executor integration",
        "existing Agent Skills registry",
        "git worktree support",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=(
        "agent-office",
        "munder-difflin",
        "multi-agent",
        "codex",
        "agent-skills",
        "worktree",
        "evidence",
        "headless",
    ),
    security_boundary=(
        "DeepSeek Harness is sole authority; AGENT_OFFICE_COORDINATOR has delegated-only "
        "mission scope; exact branch/base SHA, agent, capability, path, time and cost bounds; "
        "no scheduler, publication, secret access, canonical memory or parallel control plane"
    ),
    cost_class="BOUNDED_BY_SPEC",
    quota_class="HARNESS_SELECTED_WORKERS",
    latency_class="BOUNDED_ASYNC",
    quality_class="DETERMINISTIC_BOUNDARY_HEADLESS_CANARY_REQUIRED",
    evidence_contract="app.services.agent_office.contracts.AgentOfficeExecutionResult",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.agent_office_harness_service.execute_agent_office_capability"
    ),
    version="1",
    provider_id="munder-difflin-pinned",
    agent_id="agent-office-coordinator",
    side_effects=("ephemeral worktrees", "mission-local mailbox"),
)

PHONE_CONTROL_RECORD = CapabilityRecord(capability_id="phone.control", capability_type="EXECUTOR", domain="device/mobile-control", implementation="Harness-authorized bounded Mobile Harness adapter over Mobilerun Portal HTTP", input_contract="allowlisted phone operation + deterministic parameters", output_contract="sanitized phone control result + Harness evidence", requirements=("persisted Harness EXECUTION authorization", "local-android-http backend", "Mobilerun Portal on loopback", "isolated Mobile Harness Python runtime", "runtime-only Portal token"), maturity=PARTIAL, availability=AVAILABLE, allowed_actions=("EXECUTION",), policy_tags=("phone", "mobile", "android", "device-control", "local", "zero-cost"), security_boundary="DeepSeek Harness routing + persisted capability authorization + exact executor binding; explicit allowlist only; no autonomous authority, publication, install, permission grant, or arbitrary script", cost_class="FREE_NO_BILLING", quota_class="LOCAL_DEVICE", latency_class="LOCAL_INTERACTIVE", quality_class="PROVEN_PRIMITIVES_BOUNDED_ADAPTER", evidence_contract="app.services.harness_capability_service.CapabilityEvidence", fallback_eligibility=False, executor_binding="app.services.phone_control_service.execute_phone_control_capability", version="1", provider_id="mobilerun-local", side_effects=("device UI state change",))

PRODUCTION_MEDIA_BINDING_RECORD = CapabilityRecord(capability_id="production.media.bind-selected-segments", capability_type="CAPABILITY", domain="production-media", implementation="Harness-governed bounded binding of selected Media segments into ProductionPlan", input_contract="persisted ProductionPlan + selected segment ids + authorization lineage", output_contract="persisted composed ProductionPlan + CapabilityEvidence/CanonicalExecutionResult", requirements=("persisted Harness EXECUTION authorization", "Harness Routing/Policy decision", "exact Global Capability Registry executor binding", "matching production lineage and execution_id"), maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("EXECUTION",), policy_tags=("production", "media", "selection", "binding", "zero-cost"), security_boundary="DeepSeek Harness authority + persisted authorization + exact routing/Registry capability and executor binding; caller cannot select executor; bind_selected_segments is reachable only after all gates", cost_class="FREE_NO_BILLING", quota_class="LOCAL_DETERMINISTIC", latency_class="LOCAL", quality_class="DETERMINISTIC_BOUNDARY", evidence_contract="app.services.harness_capability_service.CapabilityEvidence", fallback_eligibility=False, executor_binding="app.services.production_media_composition_service.execute_production_media_binding_capability", version="1", side_effects=("ProductionPlan media binding persistence",))

PRODUCTION_MEDIA_SELECTION_RECORD = CapabilityRecord(
    capability_id="production.media.select-segments",
    capability_type="CAPABILITY",
    domain="production-media-selection",
    implementation="Harness-governed production scene selection from an explicit MediaKnowledge identity",
    input_contract="persisted ProductionPlan + explicit MediaKnowledge id + Harness EXECUTION lineage",
    output_contract="one persisted ContentSegment per ordered scene + CapabilityEvidence/CanonicalExecutionResult",
    requirements=(
        "persisted Harness EXECUTION authorization",
        "Harness Routing/Policy decision",
        "exact Global Capability Registry executor binding",
        "explicit MediaKnowledge identity",
        "sufficient continuous source duration",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("production", "media", "selection", "segments", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness exact capability/routing/authorization boundary; the caller supplies only a persisted "
        "MediaKnowledge identity and cannot inject an executor or fabricated segment ids."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="DETERMINISTIC_BOUNDARY",
    evidence_contract="app.services.harness_capability_service.CapabilityEvidence",
    fallback_eligibility=False,
    executor_binding="app.services.production_media_selection_capability_service.execute_production_media_selection_capability",
    version="1",
    provider_id="internal",
    side_effects=("ContentUnit persistence", "ContentSegment persistence"),
)

PRODUCTION_BRAND_ASSET_BINDING_RECORD = CapabilityRecord(
    capability_id="production.brand-assets.bind",
    capability_type="CAPABILITY",
    domain="production-branding",
    implementation="Harness-governed deterministic binding of active Telegram intro/watermark identities into one new RenderJob snapshot",
    input_contract="content_item_id + active canonical Telegram brand asset records + Harness EXECUTION lineage",
    output_contract="brand asset snapshot + CapabilityEvidence/CanonicalExecutionResult",
    requirements=(
        "persisted Harness EXECUTION authorization",
        "Harness Routing/Policy decision",
        "exact Global Capability Registry executor binding",
        "remotely verified active Telegram asset identity",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("production", "branding", "asset", "intro", "watermark", "binding", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness exact capability/routing/authorization boundary. Reads active canonical asset metadata only; "
        "does not download media on the control device, does not mutate existing RenderJobs, and grants no publication authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="DETERMINISTIC_BOUNDARY",
    evidence_contract="app.services.harness_capability_service.CapabilityEvidence",
    fallback_eligibility=False,
    executor_binding="app.services.production_brand_asset_service.execute_production_brand_asset_binding_capability",
    version="1",
    provider_id="internal",
    side_effects=(),
)

PRODUCTION_RENDER_EXECUTOR_BINDING = "app.services.render_worker_service.process_render_job"
PRODUCTION_RENDER_RECORD = CapabilityRecord(
    capability_id="production.render.execute",
    capability_type="EXECUTOR",
    domain="production-render",
    implementation=(
        "Harness-governed RenderJob execution through GitHub Actions, VEdit and FFmpeg"
    ),
    input_contract=(
        "persisted RenderJob + Harness EXECUTION lineage + versioned render profile"
    ),
    output_contract=(
        "GitHub run/job evidence + MP4/QA/manifests or terminal failure evidence"
    ),
    requirements=(
        "persisted Harness EXECUTION authorization",
        "Harness Routing/Policy decision",
        "versioned VEdit long-form render profile",
        "GitHub Actions cloud runner",
        "canonical observed result reconciliation",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=(
        "production", "render", "audiovisual", "vedit", "ffmpeg",
        "github-actions", "learning",
    ),
    security_boundary=(
        "DeepSeek Harness selects and authorizes the render capability/profile; "
        "workers only execute the immutable RenderJob and may not choose policy, "
        "learning versions or publication actions."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="GITHUB_ACTIONS",
    latency_class="REMOTE_LONG_RUNNING",
    quality_class="FFPROBE_QA_FAIL_CLOSED",
    evidence_contract="HarnessEpisode + render manifests + ffprobe/QA + GitHub run/job evidence",
    fallback_eligibility=False,
    executor_binding=PRODUCTION_RENDER_EXECUTOR_BINDING,
    version="1",
    provider_id="github-actions",
    agent_id="audiovisual-worker",
    skill_id="vedit.longform.render-profile",
    side_effects=("GitHub Actions dispatch", "render artifact creation"),
)

FRESH_GTA6_RESEARCH_RECORD = CapabilityRecord(
    capability_id="gta6.research.fresh-cloud",
    capability_type="EXECUTOR",
    domain="research",
    implementation="Harness-governed fresh GTA6 evidence collector on ephemeral GitHub Actions runner",
    input_contract="GTA6 factual/current query + persisted Harness RESEARCH authorization",
    output_contract="timestamped official Rockstar evidence + secondary/community source packet + execution evidence",
    requirements=(
        "persisted Harness RESEARCH authorization",
        "Harness Routing/Policy decision",
        "exact Global Capability Registry executor binding",
        "standard GitHub Actions runner",
        "official Rockstar source allowlist",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("RESEARCH",),
    policy_tags=("gta6", "research", "fresh", "cloud", "evidence", "sources", "fact", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness exact capability/routing/authorization boundary; read-only public-source collection; "
        "official Rockstar domains are authoritative, secondary sources require corroboration, community sources are signals only; "
        "no editorial, publication, scheduler or autonomous AI authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="PUBLIC_WEB_GITHUB_ACTIONS",
    latency_class="REMOTE_EPHEMERAL",
    quality_class="SOURCE_GROUNDED_FAIL_CLOSED",
    evidence_contract="app.services.telegram_fresh_research_service.FreshResearchEvidence",
    fallback_eligibility=False,
    executor_binding="app.services.telegram_fresh_research_service.execute_fresh_gta6_research_capability",
    version="1",
    provider_id="internal",
    side_effects=(),
)

YOUTUBE_ANALYTICS_READ_RECORD = CapabilityRecord(capability_id="youtube.analytics.read", capability_type="EXECUTOR", domain="youtube-analytics", implementation="Harness-authorized read-only YouTube Analytics API v2 executor", input_contract="persisted publication_id + governed date window", output_contract="normalized metrics/provenance + CapabilityEvidence/CanonicalExecutionResult", requirements=("persisted Harness EXECUTION authorization", "Harness Routing/Policy decision", "persisted youtube_video_id", "Google OAuth yt-analytics.readonly scope"), maturity=PARTIAL, availability=AVAILABLE, allowed_actions=("EXECUTION",), policy_tags=("youtube", "analytics", "read-only", "metrics", "zero-cost"), security_boundary="DeepSeek Harness routing + persisted authorization + exact Registry executor binding; publication identity resolves youtube_video_id; read-only analytics; no caller-selected executor or video override", cost_class="FREE_NO_BILLING", quota_class="GOOGLE_API_QUOTA", latency_class="REMOTE_API", quality_class="STRUCTURALLY_VALIDATED_RUNTIME_UNPROVEN", evidence_contract="app.services.harness_capability_service.CapabilityEvidence", fallback_eligibility=False, executor_binding="app.services.youtube_analytics_service.execute_youtube_analytics_read_capability", version="1", provider_id="google-youtube-analytics", side_effects=())

YOUTUBE_ANALYTICS_LEARNING_RECORD = CapabilityRecord(capability_id="knowledge.learn.youtube-analytics", capability_type="EXECUTOR", domain="knowledge/learning", implementation="Harness-authorized deterministic YouTube Analytics learning persistence", input_contract="normalized youtube.analytics.read evidence + authorization lineage", output_contract="idempotent existing Memory Event Log observation + CapabilityEvidence/CanonicalExecutionResult", requirements=("persisted Harness EXECUTION authorization", "Harness Routing/Policy decision", "exact Global Capability Registry executor binding", "normalized analytics provenance"), maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("EXECUTION",), policy_tags=("knowledge", "learning", "youtube", "analytics", "zero-cost"), security_boundary="DeepSeek Harness authority + persisted authorization + exact routing/Registry binding; deterministic append-only Memory Event Log reuse; no editorial or publication authority", cost_class="FREE_NO_BILLING", quota_class="LOCAL_DETERMINISTIC", latency_class="LOCAL", quality_class="DETERMINISTIC_BOUNDARY", evidence_contract="app.services.harness_capability_service.CapabilityEvidence", fallback_eligibility=False, executor_binding="app.services.youtube_analytics_learning_service.execute_youtube_analytics_learning_capability", version="1", provider_id="internal", side_effects=("Memory Event Log append",))

MARKITDOWN_NORMALIZE_RECORD = CapabilityRecord(capability_id="content.normalize.markdown", capability_type="EXECUTOR", domain="content-ingestion", implementation="Harness-authorized Microsoft MarkItDown 0.1.7 normalization adapter", input_contract="allowlisted public http/https source URI", output_contract="normalized Markdown + source provenance + CapabilityEvidence/CanonicalExecutionResult", requirements=("persisted Harness EXECUTION authorization", "Harness Routing/Policy decision", "exact Registry executor binding", "markitdown 0.1.7"), maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("EXECUTION",), policy_tags=("ingestion", "normalization", "markdown", "evidence", "zero-cost"), security_boundary="DeepSeek Harness routing + persisted authorization + exact Registry executor binding; only http/https allowlisted document formats or YouTube; plugins disabled; no shell, local-file, arbitrary executor, LLM, Azure, publication, or editorial authority", cost_class="FREE_NO_BILLING", quota_class="REMOTE_SOURCE", latency_class="REMOTE_IO", quality_class="PINNED_DETERMINISTIC_ADAPTER", evidence_contract="app.services.harness_capability_service.CapabilityEvidence", fallback_eligibility=False, executor_binding="app.services.markitdown_ingestion_service.execute_markitdown_normalization_capability", version="1", provider_id="microsoft-markitdown", side_effects=())

HUMAN_PRESENTATION_ACTION_FIRST_RECORD = CapabilityRecord(
    capability_id="human.presentation.action-first",
    capability_type="SKILL",
    domain="human-presentation",
    implementation=(
        "Deterministic action-first presentation renderer adapted from "
        "ayghri/i-have-adhd@b15d0be58f55b33972ba3e39709e0e5208ef30cb"
    ),
    input_contract="complete canonical Harness result + surface + presentation mode",
    output_contract="human-facing presentation text + integrity/provenance metadata",
    requirements=(
        "canonical result already produced",
        "persisted Harness DECISION authorization",
        "Harness Routing/Policy decision",
        "exact Global Capability Registry executor binding",
        "pinned upstream provenance",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DECISION",),
    policy_tags=(
        "presentation", "human", "action-first", "telegram", "termux",
        "work", "codex", "admin", "no-authority", "zero-cost",
    ),
    security_boundary=(
        "Presentation-only deterministic projection after canonical execution/evidence. "
        "May not mutate canonical result, write memory, choose routing, change factual classification, "
        "hide FAIL/INSUFFICIENT_EVIDENCE/policy violations, trigger production, or grant publication authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="SEMANTIC_PRESERVATION_FAIL_CLOSED",
    evidence_contract="app.services.human_presentation_service.PresentationResult",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.human_presentation_service.execute_human_presentation_capability"
    ),
    version="0.3.0-br1",
    provider_id="ayghri-i-have-adhd-pinned",
    skill_id="human.presentation.action-first",
    instruction_path=".dsh/skills/human-presentation-action-first/SKILL.md",
    side_effects=(),
)

TELEGRAM_BRAND_ASSET_RECORD = CapabilityRecord(
    capability_id="telegram.asset.register",
    capability_type="EXECUTOR",
    domain="telegram-ingress",
    implementation="Harness-governed registration of verified Telegram intro/watermark file identity and provenance",
    input_contract="paired Telegram user/chat/message + verified getFile identity + intro|watermark classification",
    output_contract="active canonical brand asset record + Harness routing/authorization evidence",
    requirements=(
        "paired Telegram ingress",
        "Telegram getFile verification",
        "persisted Harness EXECUTION authorization",
        "exact Global Capability Registry executor binding",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("telegram", "asset", "branding", "intro", "watermark", "zero-cost"),
    security_boundary=(
        "Telegram authentication is ingress identity only; DeepSeek Harness remains sole authority. "
        "The capability persists file identity/provenance only, never bot token bytes and never publication authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="TELEGRAM_API",
    latency_class="REMOTE_API",
    quality_class="DETERMINISTIC_METADATA_BOUNDARY",
    evidence_contract="app.services.harness_execution_result.CanonicalExecutionResult",
    fallback_eligibility=False,
    executor_binding="app.services.telegram_harness_service.execute_telegram_asset_registration_capability",
    version="1",
    provider_id="telegram-bot-api",
    side_effects=("canonical brand asset metadata persistence",),
)

TELEGRAM_USER_INPUT_RECORD = CapabilityRecord(
    capability_id="telegram.input.ingest",
    capability_type="EXECUTOR",
    domain="telegram-ingress",
    implementation="Harness-governed canonical capture, classification and bounded GTA6 memory learning from paired Telegram user input",
    input_contract="paired Telegram message plus optional remotely verified attachment identity",
    output_contract="canonical telegram_user_input + Memory Event + optional Claim/semantic Memory + CapabilityEvidence",
    requirements=(
        "paired Telegram ingress",
        "persisted Harness EXECUTION authorization",
        "exact Global Capability Registry executor binding",
        "Telegram getFile verification for attachments",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("telegram", "ingress", "learning", "memory", "gta6", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness remains sole authority. Every paired user input is captured with immutable provenance; "
        "only bounded classifications are promoted into semantic memory. User-supplied news is marked uncertain; "
        "attachments persist identity/provenance only on the A15; no publication, editorial, scheduler or arbitrary executor authority is granted."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="DETERMINISTIC_PROVENANCE_MEMORY_BOUNDARY",
    evidence_contract="app.services.harness_capability_service.CapabilityEvidence",
    fallback_eligibility=False,
    executor_binding="app.services.telegram_learning_service.execute_telegram_input_ingestion_capability",
    version="1",
    provider_id="internal",
    side_effects=("canonical Telegram ingress persistence", "Memory Event append", "bounded semantic memory learning"),
)

for _record in (
    AGENT_OFFICE_RECORD,
    PHONE_CONTROL_RECORD,
    PRODUCTION_MEDIA_SELECTION_RECORD,
    PRODUCTION_MEDIA_BINDING_RECORD,
    PRODUCTION_BRAND_ASSET_BINDING_RECORD,
    PRODUCTION_RENDER_RECORD,
    FRESH_GTA6_RESEARCH_RECORD,
    YOUTUBE_ANALYTICS_READ_RECORD,
    YOUTUBE_ANALYTICS_LEARNING_RECORD,
    MARKITDOWN_NORMALIZE_RECORD,
    HUMAN_PRESENTATION_ACTION_FIRST_RECORD,
    TELEGRAM_BRAND_ASSET_RECORD,
    TELEGRAM_USER_INPUT_RECORD,
):
    if _record.capability_id in _REGISTRY._by_id:
        raise ValueError(f"Duplicate capability_id: {_record.capability_id}")
    _REGISTRY._by_id[_record.capability_id] = _record
    _REGISTRY._records = tuple(sorted((*_REGISTRY._records, _record), key=lambda item: item.capability_id))

# Real runtime proof: GitHub Actions run 35033861020 executed the explicit
# OpenCode Free model through OmniRoute 3.8.50 on a standard public runner,
# with no credentials, no fallback and cost_class FREE_NO_BILLING. Promotion
# is metadata only; the Harness still selects and authorizes every execution.
for _capability_id in ("ai.provider.opencode-free", "executor.omniroute-gateway"):
    _existing = _REGISTRY._by_id.get(_capability_id)
    if _existing is None:
        raise ValueError(f"Missing proven OmniRoute Registry record: {_capability_id}")
    _promoted = replace(
        _existing,
        maturity=PROVEN,
        availability=AVAILABLE,
        quality_class="PROVEN_ZERO_COST_RUNTIME_RUN_35033861020",
    )
    _REGISTRY._by_id[_capability_id] = _promoted
    _REGISTRY._records = tuple(
        sorted(
            (_promoted if record.capability_id == _capability_id else record for record in _REGISTRY._records),
            key=lambda item: item.capability_id,
        )
    )

# gta6.fact-check is a native deterministic executor. The base registry keeps
# the skill discoverable as unproven metadata; this overlay promotes the exact
# implementation only after the bounded runtime exists in this repository.
_existing_fact_check = _REGISTRY._by_id.get("gta6.fact-check")
if _existing_fact_check is None:
    raise ValueError("Missing gta6.fact-check Registry record")
FACT_CHECK_RECORD = replace(
    _existing_fact_check,
    implementation="Harness-governed deterministic GTA6 claim/evidence fact-check executor",
    input_contract="claim + provenance-complete evidence + mission/task/goal lineage",
    output_contract="FactCheckResult + AgentInvocationReceipt + canonical Harness evidence",
    requirements=(
        "persisted Harness RESEARCH or EDITORIAL authorization",
        "Harness Routing/Policy decision",
        "exact Global Capability Registry executor binding",
        "provenance-complete evidence",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    security_boundary=(
        "DeepSeek Harness exact authorization/routing/executor binding; deterministic evidence assessment only; "
        "missing provenance fails closed; no autonomous research, memory write, editorial decision, publication, or fallback authority"
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="DETERMINISTIC_PROVENANCE_FAIL_CLOSED",
    evidence_contract="app.services.gta6_fact_check_service.FactCheckResult",
    executor_binding="app.services.gta6_fact_check_service.execute_gta6_fact_check_capability",
    provider_id="internal",
    side_effects=(),
)
_REGISTRY._by_id[FACT_CHECK_RECORD.capability_id] = FACT_CHECK_RECORD
_REGISTRY._records = tuple(
    sorted(
        (
            FACT_CHECK_RECORD if record.capability_id == FACT_CHECK_RECORD.capability_id else record
            for record in _REGISTRY._records
        ),
        key=lambda item: item.capability_id,
    )
)

GLOBAL_CAPABILITY_REGISTRY = _REGISTRY