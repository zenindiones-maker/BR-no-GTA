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
from app.services.monetization_observability_service import (
    MONETIZATION_CAPABILITY_ID,
    MONETIZATION_EXECUTOR_BINDING,
)
from app.services.youtube_department_service import youtube_department_records
from app.services.media_analysis_cloud_service import (
    MEDIA_ANALYSIS_CLOUD_CAPABILITY_ID,
    MEDIA_ANALYSIS_CLOUD_EXECUTOR_BINDING,
)

AGENT_OFFICE_RECORD = CapabilityRecord(
    capability_id="agent-office.execute",
    capability_type="EXECUTOR",
    domain="development",
    implementation=(
        "Harness-subordinated headless Munder Difflin Agent Office coordinator"
    ),
    input_contract="Harness-authorized mission + persistent DelegatedTaskLease set + bounded AgentOfficeTask DAG",
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
    version="2",
    provider_id="munder-difflin-pinned",
    agent_id="agent-office-coordinator",
    side_effects=("ephemeral worktrees", "mission-local mailbox"),
)


AGENT_OFFICE_CODEX_READONLY_RECORD = CapabilityRecord(
    capability_id="agent-office.codex.readonly-analysis",
    capability_type="AGENT",
    domain="development",
    implementation="Agent Office task-owner Codex read-only analysis in a disposable git worktree",
    input_contract="DelegatedTaskLease + task-specific context/artifact refs + exact base SHA",
    output_contract="structured analysis artifact + commands/tests/evidence + AgentOfficeExecutionResult",
    requirements=(
        "DeepSeek Harness DEVELOPMENT authorization",
        "Agent Office delegated lease",
        "Codex CLI authenticated",
        "disposable git worktree",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=("agent-office","codex","readonly","analysis","task-owner","delegated-autonomy"),
    security_boundary=(
        "DeepSeek Harness sole authority; Agent Office derives a bounded lease; Codex runs read-only "
        "inside a disposable worktree and cannot mutate repository, push, merge, publish, access secrets or change policy."
    ),
    cost_class="BOUNDED_BY_LEASE",
    quota_class="CODEX_ACCOUNT",
    latency_class="MODEL_DEPENDENT",
    quality_class="STRUCTURED_ANALYSIS_WITH_EVIDENCE",
    evidence_contract="app.services.agent_office.contracts.AgentOfficeExecutionResult",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.agent_office_harness_service.execute_authorized_agent_office_specialist"
    ),
    version="1",
    provider_id="codex",
    agent_id="codex-readonly",
    side_effects=("ephemeral worktree", "structured runtime artifact"),
)

AGENT_OFFICE_CODEX_BOUNDED_DEVELOPMENT_RECORD = CapabilityRecord(
    capability_id="agent-office.codex.bounded-development",
    capability_type="AGENT",
    domain="development",
    implementation="Agent Office task-owner Codex workspace-write engineering in a disposable git worktree",
    input_contract=(
        "DelegatedTaskLease + exact base SHA + explicit allowed_paths/write_set + command allowlist + "
        "test/benchmark acceptance criteria"
    ),
    output_contract=(
        "local candidate commit + files/diff/commands/tests/benchmarks/artifact refs + "
        "CANDIDATE_READY_FOR_INTEGRATION"
    ),
    requirements=(
        "DeepSeek Harness DEVELOPMENT authorization",
        "Agent Office delegated lease",
        "Codex CLI authenticated",
        "disposable git worktree",
        "explicit write set",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=("agent-office","codex","bounded-development","worktree","candidate","task-owner"),
    security_boundary=(
        "DeepSeek Harness sole authority. Codex may edit/test only inside lease-owned paths in a disposable "
        "workspace-write sandbox and may create only a local candidate commit. No push, merge, canonical branch write, "
        "network side effect, secret access, policy/authority mutation, deployment or publication."
    ),
    cost_class="BOUNDED_BY_LEASE",
    quota_class="CODEX_ACCOUNT",
    latency_class="MODEL_AND_TEST_DEPENDENT",
    quality_class="CANDIDATE_ONLY_INTEGRATION_GATE_REQUIRED",
    evidence_contract="app.services.agent_office.contracts.AgentOfficeExecutionResult",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.agent_office_harness_service.execute_authorized_agent_office_specialist"
    ),
    version="1",
    provider_id="codex",
    agent_id="codex-development",
    side_effects=("ephemeral worktree mutation", "local candidate commit", "structured runtime artifact"),
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

NARRATION_GENERATE_PTBR_RECORD = CapabilityRecord(
    capability_id="narration.generate.pt-BR",
    capability_type="CAPABILITY",
    domain="narration",
    implementation="Harness-governed deterministic PT-BR narration bundle materialization",
    input_contract="approved PT-BR script sections + exact Harness EXECUTION lineage",
    output_contract="versioned narration-bundle with A1 master, segment manifest, native timing, voice profile and QA",
    requirements=(
        "persisted Harness EXECUTION authorization",
        "Harness Routing/Policy decision",
        "edge-tts 7.2.8 zero-cost provider",
        "FFmpeg/ffprobe master QA",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("narration", "voice", "pt-br", "a1", "cache", "timing", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness remains sole authority; narration materializes only the approved script, "
        "does not make editorial decisions, cannot publish, and exposes no parallel control plane."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="REMOTE_TTS_BOUNDED_CONCURRENCY",
    latency_class="REMOTE_ASYNC_SEGMENTED",
    quality_class="CONTENT_ADDRESSED_SEGMENTS_MASTER_EBU_R128_QA",
    evidence_contract="narration-manifest.json + narration-qa.json + speech-timing.json + voice-speed-profile.json",
    fallback_eligibility=False,
    executor_binding="app.services.narration_pipeline.execute_narration_capability",
    version="2",
    provider_id="edge-tts",
    agent_id="audiovisual-worker",
    side_effects=("narration bundle artifact", "content-addressed segment cache", "voice speed evidence"),
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

YOUTUBE_PACKAGE_PERSIST_RECORD = CapabilityRecord(
    capability_id="youtube.package.persist",
    capability_type="CAPABILITY",
    domain="youtube-department",
    implementation="Harness-governed persistence of the canonical pre-publication YouTube content package",
    input_contract="verified Goal/Script/ContentItem + YouTube specialist outputs + evidence refs + exact Harness YOUTUBE lineage",
    output_contract="persisted youtube_content_packages row + CapabilityEvidence",
    requirements=(
        "persisted Harness YOUTUBE authorization",
        "Harness Routing/Policy decision",
        "exact Global Capability Registry executor binding",
        "verified evidence lineage",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("YOUTUBE",),
    policy_tags=("youtube", "package", "metadata", "persistence", "evidence", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness routing + persisted capability authorization + exact Registry executor binding; "
        "persists planned metadata only and cannot upload or make a video public"
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="EVIDENCE_GROUNDED_PACKAGE_PERSISTENCE",
    evidence_contract="app.services.harness_capability_service.CapabilityEvidence",
    fallback_eligibility=False,
    executor_binding="app.services.youtube_package_service.execute_youtube_package_persist_capability",
    version="1",
    provider_id="internal",
    side_effects=("canonical YouTube content package persistence",),
)

YOUTUBE_ANALYTICS_READ_RECORD = CapabilityRecord(capability_id="youtube.analytics.read", capability_type="EXECUTOR", domain="youtube-analytics", implementation="Harness-authorized read-only YouTube Analytics API v2 executor", input_contract="persisted publication_id + governed date window", output_contract="normalized metrics/provenance + CapabilityEvidence/CanonicalExecutionResult", requirements=("persisted Harness EXECUTION authorization", "Harness Routing/Policy decision", "persisted youtube_video_id", "Google OAuth yt-analytics.readonly scope"), maturity=PARTIAL, availability=AVAILABLE, allowed_actions=("EXECUTION",), policy_tags=("youtube", "analytics", "read-only", "metrics", "zero-cost"), security_boundary="DeepSeek Harness routing + persisted authorization + exact Registry executor binding; publication identity resolves youtube_video_id; read-only analytics; no caller-selected executor or video override", cost_class="FREE_NO_BILLING", quota_class="GOOGLE_API_QUOTA", latency_class="REMOTE_API", quality_class="STRUCTURALLY_VALIDATED_RUNTIME_UNPROVEN", evidence_contract="app.services.harness_capability_service.CapabilityEvidence", fallback_eligibility=False, executor_binding="app.services.youtube_analytics_service.execute_youtube_analytics_read_capability", version="1", provider_id="google-youtube-analytics", side_effects=())

YOUTUBE_ANALYTICS_LEARNING_RECORD = CapabilityRecord(capability_id="knowledge.learn.youtube-analytics", capability_type="EXECUTOR", domain="knowledge/learning", implementation="Harness-authorized deterministic YouTube Analytics learning persistence", input_contract="normalized youtube.analytics.read evidence + authorization lineage", output_contract="idempotent existing Memory Event Log observation + CapabilityEvidence/CanonicalExecutionResult", requirements=("persisted Harness EXECUTION authorization", "Harness Routing/Policy decision", "exact Global Capability Registry executor binding", "normalized analytics provenance"), maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("EXECUTION",), policy_tags=("knowledge", "learning", "youtube", "analytics", "zero-cost"), security_boundary="DeepSeek Harness authority + persisted authorization + exact routing/Registry binding; deterministic append-only Memory Event Log reuse; no editorial or publication authority", cost_class="FREE_NO_BILLING", quota_class="LOCAL_DETERMINISTIC", latency_class="LOCAL", quality_class="DETERMINISTIC_BOUNDARY", evidence_contract="app.services.harness_capability_service.CapabilityEvidence", fallback_eligibility=False, executor_binding="app.services.youtube_analytics_learning_service.execute_youtube_analytics_learning_capability", version="1", provider_id="internal", side_effects=("Memory Event Log append",))

MARKITDOWN_NORMALIZE_RECORD = CapabilityRecord(capability_id="content.normalize.markdown", capability_type="EXECUTOR", domain="content-ingestion", implementation="Harness-authorized Microsoft MarkItDown 0.1.7 normalization adapter", input_contract="allowlisted public http/https source URI", output_contract="normalized Markdown + source provenance + CapabilityEvidence/CanonicalExecutionResult", requirements=("persisted Harness EXECUTION authorization", "Harness Routing/Policy decision", "exact Registry executor binding", "markitdown 0.1.7"), maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("EXECUTION",), policy_tags=("ingestion", "normalization", "markdown", "evidence", "zero-cost"), security_boundary="DeepSeek Harness routing + persisted authorization + exact Registry executor binding; only http/https allowlisted document formats or YouTube; plugins disabled; no shell, local-file, arbitrary executor, LLM, Azure, publication, or editorial authority", cost_class="FREE_NO_BILLING", quota_class="REMOTE_SOURCE", latency_class="REMOTE_IO", quality_class="PINNED_DETERMINISTIC_ADAPTER", evidence_contract="app.services.harness_capability_service.CapabilityEvidence", fallback_eligibility=False, executor_binding="app.services.markitdown_ingestion_service.execute_markitdown_normalization_capability", version="1", provider_id="microsoft-markitdown", side_effects=())

HUMAN_PRESENTATION_ACTION_FIRST_RECORD = CapabilityRecord(
    capability_id="human.presentation.action-first",
    capability_type="PRESENTATION",
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
    authority="NONE",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
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

MONETIZATION_RECORD = CapabilityRecord(
    capability_id=MONETIZATION_CAPABILITY_ID,
    capability_type="EXECUTOR",
    domain="youtube-monetization",
    implementation="Harness-governed official YouTube Analytics monetary observability adapter",
    input_contract="governed date window + owner OAuth credentials or normalized API response",
    output_contract="ChannelMonetizationSnapshot with availability/limitations/provenance",
    requirements=("YouTube Analytics API v2", "yt-analytics-monetary.readonly for monetary metrics"),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("youtube", "analytics", "monetization", "revenue", "observability"),
    security_boundary="DeepSeek Harness selects and authorizes read-only observation; no credentials in evidence; no publication authority",
    cost_class="FREE_NO_BILLING",
    quota_class="GOOGLE_API_QUOTA",
    latency_class="REMOTE_API",
    quality_class="GRACEFUL_MISSING_METRICS",
    evidence_contract="app.services.monetization_observability_service.ChannelMonetizationSnapshot",
    fallback_eligibility=False,
    executor_binding=MONETIZATION_EXECUTOR_BINDING,
    version="1",
    provider_id="google-youtube-analytics",
    agent_id="tubegent-monetization",
    side_effects=(),
)

SYSTEM_IMPROVEMENT_RECORD = CapabilityRecord(
    capability_id="system.improvement.propose",
    capability_type="AGENT",
    domain="system-improvement",
    implementation="Harness-subordinated evidence-driven system improvement proposal generator",
    input_contract="health, failure, latency, cost and test evidence",
    output_contract="bounded proposal requiring review/tests/commit/CI gate",
    requirements=("DeepSeek Harness routing", "evidence package"),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=("system", "improvement", "proposal", "tests", "review"),
    security_boundary="Proposal only; never self-modifies production. Structural change requires evidence, tests, review/gate, commit and CI.",
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="PROPOSAL_ONLY_FAIL_CLOSED",
    evidence_contract="app.services.system_synergy_service.SystemImprovementProposal",
    fallback_eligibility=False,
    executor_binding="app.services.system_synergy_service.execute_system_improvement_proposal",
    version="1",
    provider_id="internal",
    agent_id="system-improvement-agent",
    side_effects=(),
)

GTA6_BRAIN_DECISION_RECORD = CapabilityRecord(
    capability_id="gta6.brain.decide",
    capability_type="AGENT",
    domain="gta6-decision",
    implementation="Harness-subordinated GTA6 Brain domain decision specialist",
    input_contract="canonical GTA6 operational state + optional mission/goal lineage",
    output_contract="BrainDecision + AgentInvocationReceipt + canonical Harness evidence",
    requirements=(
        "persisted Harness DECISION authorization",
        "Harness-selected ai.reasoning.text provider/model",
        "canonical BR database observation",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DECISION",),
    policy_tags=("gta6", "brain", "domain-specialist", "decision", "evidence", "learning"),
    security_boundary=(
        "DeepSeek Harness remains sole authority. GTA6 Brain may recommend exactly one bounded action "
        "but cannot authorize or execute it; provider/model is selected by Harness policy."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="HARNESS_AI_PROVIDER_POLICY",
    latency_class="REMOTE_AI",
    quality_class="DOMAIN_DECISION_STRUCTURED_FAIL_CLOSED",
    evidence_contract="app.services.gta6_brain.BrainDecision + AgentInvocationReceipt",
    fallback_eligibility=False,
    executor_binding="app.services.gta6_brain_harness_service.execute_authorized_gta6_brain_decision",
    version="1",
    provider_id=None,
    agent_id="gta6-brain",
    side_effects=(),
)

MEDIA_ANALYSIS_CLOUD_RECORD = CapabilityRecord(
    capability_id=MEDIA_ANALYSIS_CLOUD_CAPABILITY_ID,
    capability_type="EXECUTOR",
    domain="media-analysis",
    implementation="Harness-governed fixed GitHub Actions MediaKnowledge and Whisper analysis dispatcher",
    input_contract="public HTTPS media source + bounded logical source name",
    output_contract="GitHub Actions run identity for media-knowledge/speech-analysis artifacts",
    requirements=("GitHub Actions", "media-worker.yml", "heavy execution stays off A15"),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("media", "analysis", "cloud", "whisperx", "knowledge", "github-actions"),
    security_boundary=(
        "DeepSeek Harness authorization + exact Registry binding; fixed media-worker workflow only; "
        "caller cannot provide shell commands or arbitrary workflow; no publication authority"
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="GITHUB_ACTIONS",
    latency_class="REMOTE_HEAVY",
    quality_class="CLOUD_MEDIAKNOWLEDGE_WHISPER_QA",
    evidence_contract="GitHub Actions run + media-knowledge/speech-analysis artifact lineage",
    fallback_eligibility=False,
    executor_binding=MEDIA_ANALYSIS_CLOUD_EXECUTOR_BINDING,
    version="1",
    provider_id="github-actions",
    agent_id="audiovisual-worker",
    side_effects=("GitHub Actions workflow dispatch",),
)

_YOUTUBE_DEPARTMENT_RECORDS = youtube_department_records()

for _record in (
    AGENT_OFFICE_RECORD,
    AGENT_OFFICE_CODEX_READONLY_RECORD,
    AGENT_OFFICE_CODEX_BOUNDED_DEVELOPMENT_RECORD,
    PHONE_CONTROL_RECORD,
    PRODUCTION_MEDIA_SELECTION_RECORD,
    PRODUCTION_MEDIA_BINDING_RECORD,
    PRODUCTION_BRAND_ASSET_BINDING_RECORD,
    PRODUCTION_RENDER_RECORD,
    NARRATION_GENERATE_PTBR_RECORD,
    FRESH_GTA6_RESEARCH_RECORD,
    YOUTUBE_PACKAGE_PERSIST_RECORD,
    YOUTUBE_ANALYTICS_READ_RECORD,
    YOUTUBE_ANALYTICS_LEARNING_RECORD,
    MARKITDOWN_NORMALIZE_RECORD,
    HUMAN_PRESENTATION_ACTION_FIRST_RECORD,
    TELEGRAM_BRAND_ASSET_RECORD,
    TELEGRAM_USER_INPUT_RECORD,
    MONETIZATION_RECORD,
    SYSTEM_IMPROVEMENT_RECORD,
    GTA6_BRAIN_DECISION_RECORD,
    MEDIA_ANALYSIS_CLOUD_RECORD,
    *_YOUTUBE_DEPARTMENT_RECORDS,
):
    if _record.capability_id in _REGISTRY._by_id:
        raise ValueError(f"Duplicate capability_id: {_record.capability_id}")
    _REGISTRY._by_id[_record.capability_id] = _record
    _REGISTRY._records = tuple(sorted((*_REGISTRY._records, _record), key=lambda item: item.capability_id))

# Normalize legacy Registry records. Active records must point to exact callables;
# superseded/internal implementation details must not pretend to be standalone
# Harness capabilities.
_NATIVE_ADAPTER_BINDINGS = {
    "media.discovery": "app.services.native_capability_adapters.execute_media_discovery_capability",
    "production.plan": "app.services.native_capability_adapters.execute_production_plan_capability",
    "qa.preflight": "app.services.native_capability_adapters.execute_qa_preflight_capability",
    "script.generate": "app.services.native_capability_adapters.execute_script_generate_capability",
    "video.edit.vedit": "app.services.native_capability_adapters.execute_vedit_plan_capability",
}
for _capability_id, _binding in _NATIVE_ADAPTER_BINDINGS.items():
    _existing = _REGISTRY._by_id.get(_capability_id)
    if _existing is None:
        raise ValueError(f"Missing native capability Registry record: {_capability_id}")
    _normalized = replace(
        _existing,
        executor_binding=_binding,
        security_boundary=(
            _existing.security_boundary
            + "; exact bounded native adapter invoked only after Harness routing and persisted authorization"
        ),
    )
    _REGISTRY._by_id[_capability_id] = _normalized
    _REGISTRY._records = tuple(
        sorted(
            (_normalized if record.capability_id == _capability_id else record for record in _REGISTRY._records),
            key=lambda item: item.capability_id,
        )
    )

_LEGACY_SUPERSEDED_CAPABILITIES = {
    "cloud.github-actions": "infrastructure primitive; use specific cloud capability such as media.analysis.cloud or production.render.execute",
    "media.ffmpeg": "internal render-engine implementation; use production.render.execute",
    "media.select": "superseded by production.media.select-segments",
    "media.technical-analysis": "superseded by media.analysis.cloud",
    "video.render": "superseded by production.render.execute",
}
for _capability_id, _reason in _LEGACY_SUPERSEDED_CAPABILITIES.items():
    _existing = _REGISTRY._by_id.get(_capability_id)
    if _existing is None:
        raise ValueError(f"Missing legacy capability Registry record: {_capability_id}")
    _deprecated = replace(
        _existing,
        availability=UNKNOWN,
        executor_binding=None,
        implementation=f"DEPRECATED SUPPORT PATH: {_reason}",
        quality_class="DEPRECATED_NOT_DIRECTLY_ROUTABLE",
        security_boundary=(
            "Not directly executable. " + _reason
            + ". DeepSeek Harness must select the canonical bounded replacement."
        ),
        fallback_eligibility=False,
    )
    _REGISTRY._by_id[_capability_id] = _deprecated
    _REGISTRY._records = tuple(
        sorted(
            (_deprecated if record.capability_id == _capability_id else record for record in _REGISTRY._records),
            key=lambda item: item.capability_id,
        )
    )

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