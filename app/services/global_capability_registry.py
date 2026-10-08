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
from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_MUTATE_CANDIDATE,
    CAN_PRODUCE_ARTIFACT_REFS,
    CAN_READ_REPOSITORY,
    CAN_REVIEW,
    CAN_RUN_BENCHMARK,
    CAN_RUN_TESTS,
    CAN_SEMANTIC_REASONING,
    CAN_WRITE_REPOSITORY,
    EFFECT_HUMAN_MESSAGE_DELIVERY,
    OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1,
    OUTPUT_CONTRACT_EDITORIAL_SCRIPT_BUNDLE_V1,
    SURFACE_TELEGRAM_GROUP,
)
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
    execution_kind="ORCHESTRATOR",
    functional_roles=("ORCHESTRATOR",),
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

    supports_parallelism=True,
    supports_retry=True,
    supports_resume=True,
    supports_review=True,
    side_effect_class="BOUNDED_MUTATION",
    default_read_scope=("app", "scripts", "tests", ".github/workflows", "config", "integrations"),
    default_write_scope=("app", "scripts", "tests"),
    allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
    health_policy="EXECUTOR_RUNTIME_REQUIRED",
)

DEVELOPMENT_CHECKPOINT_PERSIST_RECORD = CapabilityRecord(
    capability_id="development.checkpoint.persist",
    capability_type="EXECUTOR",
    domain="development-continuity",
    implementation="Harness-authorized fail-closed remote development recovery checkpoint persistence",
    input_contract="DevelopmentProgressLedger/v1 + bounded recovery request + expected previous remote OID",
    output_contract="DevelopmentRecoveryCheckpoint/v1 with remote write/readback evidence",
    requirements=(
        "persisted DeepSeek Harness DEVELOPMENT authorization",
        "recovery/dev/** target only",
        "governed path classification and secret scan",
        "shadow Git index",
        "remote fast-forward write + readback verification",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=("development","continuity","recovery","checkpoint","git","fail-closed"),
    security_boundary=(
        "DeepSeek Harness remains sole authority; executor can write only recovery/dev/**, "
        "never canonical branches, publication, deployment, provider spend or external side-effect replay"
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="GITHUB_GIT_REMOTE",
    latency_class="LOCAL_PLUS_REMOTE_GIT",
    quality_class="REMOTE_READBACK_VERIFIED_FAIL_CLOSED",
    evidence_contract="DevelopmentRecoveryCheckpoint/v1",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.development_checkpoint_capability_service."
        "execute_development_checkpoint_persist_capability"
    ),
    version="1",
    provider_id="github-git",
    side_effects=("recovery ref fast-forward update",),
    authority="NONE",
    memory_write="DEVELOPMENT_RECOVERY_ONLY",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    supports_parallelism=False,
    supports_retry=True,
    supports_resume=True,
    supports_review=True,
    side_effect_class="BOUNDED_MUTATION",
    default_read_scope=("app","tests","scripts","docs",".github","config","schemas"),
    default_write_scope=("recovery/dev/**",),
    allowed_tools=("git","python"),
    health_policy="REMOTE_GIT_READBACK_REQUIRED",
    execution_kind="MUTATION_EXECUTOR",
    functional_roles=("DEVELOPMENT_CONTINUITY",),
)


HERMES_MULTIAGENT_RUNTIME_RECORD = CapabilityRecord(
    capability_id="collaboration.hermes.execute",
    capability_type="EXECUTOR",
    domain="collaboration",
    implementation=(
        "Pinned NousResearch/hermes-agent durable Kanban/profile runtime "
        "subordinated to a DeepSeek Harness CollaborationPlan"
    ),
    input_contract=(
        "Harness EXECUTION authorization + exact base SHA + routed CollaborationPlan + "
        "bounded HermesMissionExecutionSpec"
    ),
    output_contract=(
        "HermesMissionExecutionResult + board/handoff/review evidence + "
        "CanonicalExecutionResult + HarnessEpisode lineage"
    ),
    requirements=(
        "persisted DeepSeek Harness EXECUTION authorization",
        "Harness CollaborationPlan",
        "GLOBAL_CAPABILITY_REGISTRY canonical task routing",
        "pinned NousResearch/hermes-agent upstream SHA",
        "mandatory forbidden-action lease",
        "durable isolated Kanban board",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=(
        "collaboration",
        "hermes-agent",
        "multi-agent",
        "kanban",
        "durable",
        "handoff",
        "review",
        "delegated-only",
        "zero-cost-runtime",
    ),
    security_boundary=(
        "DeepSeek Harness remains sole routing/policy/authorization authority. Hermes receives only "
        "mission-scoped Kanban coordination plus allowlisted br_harness tools, may not expand the "
        "CollaborationPlan, may not call canonical executors directly, and has no secret, credential, "
        "policy, canonical-memory, branch-write, paid-action or publication authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="HARNESS_BOUNDED_MISSION",
    latency_class="MISSION_DEPENDENT",
    quality_class="DURABLE_MULTIAGENT_REVIEW_GATED",
    evidence_contract="app.services.hermes_multiagent.contracts.HermesMissionExecutionResult",
    fallback_eligibility=False,
    executor_binding="app.services.hermes_multiagent.runtime.execute_hermes_mission_capability",
    version="1",
    provider_id="nousresearch-hermes-agent",
    agent_id="hermes-runtime",
    side_effects=("mission-local Kanban SQLite", "structured evidence artifacts"),

    supports_parallelism=True,
    supports_retry=True,
    supports_resume=True,
    supports_review=True,
    side_effect_class="COORDINATION_ONLY",
    default_read_scope=(),
    default_write_scope=(),
    allowed_tools=(
        "kanban_show", "kanban_complete", "kanban_request_review",
        "kanban_request_changes", "kanban_block", "kanban_heartbeat",
        "kanban_comment", "kanban_create", "kanban_link", "kanban_unblock",
        "br_harness_status", "br_harness_capability_request",
        "br_harness_submit_evidence",
    ),
    health_policy="PINNED_RUNTIME",
)



ARTIFACT_EVIDENCE_REUSE_RECORD = CapabilityRecord(
    capability_id="artifact.evidence.reuse",
    capability_type="CAPABILITY",
    domain="development",
    implementation=(
        "Harness-governed deterministic reuse of an already materialized "
        "artifact by immutable ref + sha256 lineage"
    ),
    input_contract=(
        "pre-materialized mission artifact refs + sha256/size metadata"
    ),
    output_contract=(
        "validated artifact manifest preserving the same refs/hashes without "
        "semantic interpretation or provider execution"
    ),
    requirements=(
        "persisted Harness DEVELOPMENT authorization",
        "exact Global Capability Registry executor binding",
        "pre-materialized artifact under the mission artifact root",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=(
        "artifact", "evidence", "reuse", "pre-materialized", "lineage",
        "normalize", "normalizar", "extract", "extrair", "incident",
        "incidente", "evidencia", "evidências", "zero-cost",
    ),
    security_boundary=(
        "DeepSeek Harness exact authorization/routing; immutable artifact refs "
        "and sha256 metadata only; no LLM/provider call, repository mutation, "
        "publication, memory promotion or policy authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="HASH_VERIFIED_ARTIFACT_LINEAGE_REUSE",
    evidence_contract="CapabilityEvidence + TaskResultEnvelope artifact lineage",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.artifact_evidence_reuse_service."
        "execute_pre_materialized_artifact_reuse"
    ),
    version="1",
    provider_id="internal",
    agent_id="artifact-lineage-worker",
    side_effects=(),
    supports_parallelism=True,
    supports_retry=False,
    supports_resume=True,
    supports_review=False,
    side_effect_class="READ_ONLY",
    default_read_scope=(),
    default_write_scope=(),
    allowed_tools=(),
    health_policy="DEFAULT",
    execution_operations=(
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="DETERMINISTIC_WORKER",
    functional_roles=("EVIDENCE",),
)


AGENT_OFFICE_DETERMINISTIC_READONLY_RECORD = CapabilityRecord(
    capability_id="agent-office.deterministic-analysis",
    capability_type="AGENT",
    domain="development",
    implementation=(
        "Agent Office deterministic task-owner repository profiler in a "
        "disposable git worktree"
    ),
    input_contract=(
        "DelegatedTaskLease + exact base SHA + bounded repository read scope"
    ),
    output_contract=(
        "structured repository profile with file/line/size concentration metrics "
        "+ AgentOfficeExecutionResult"
    ),
    requirements=(
        "DeepSeek Harness DEVELOPMENT authorization",
        "Agent Office delegated lease",
        "git worktree support",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=(
        "agent-office", "deterministic", "readonly", "analysis",
        "profiling", "performance", "observability", "architecture",
        "redundancy", "task-owner", "zero-cost",
    ),
    security_boundary=(
        "DeepSeek Harness sole authority; deterministic specialist reads only "
        "the Registry-authorized repository scope in a disposable worktree and "
        "cannot mutate, push, merge, publish, access secrets or change policy."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="DETERMINISTIC_REPOSITORY_PROFILE_WITH_EVIDENCE",
    evidence_contract="app.services.agent_office.contracts.AgentOfficeExecutionResult",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.agent_office_harness_service."
        "execute_authorized_agent_office_specialist"
    ),
    version="1",
    provider_id="internal",
    agent_id="deterministic-analysis",
    side_effects=("ephemeral worktree", "structured runtime artifact"),
    supports_parallelism=True,
    supports_retry=True,
    supports_resume=True,
    supports_review=False,
    side_effect_class="READ_ONLY",
    default_read_scope=(
        "app", "scripts", "tests", ".github/workflows", "config", "integrations"
    ),
    default_write_scope=(),
    allowed_tools=("git",),
    health_policy="DEFAULT",
    execution_operations=(
        CAN_READ_REPOSITORY,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="DETERMINISTIC_ANALYSIS_AGENT",
    functional_roles=("ANALYSIS",),
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

    supports_parallelism=True,
    supports_retry=True,
    supports_resume=True,
    supports_review=False,
    side_effect_class="READ_ONLY",
    default_read_scope=("app", "scripts", "tests", ".github/workflows", "config", "integrations"),
    default_write_scope=(),
    allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
    health_policy="CODEX_AUTH_REQUIRED",
    execution_operations=(
        CAN_SEMANTIC_REASONING,
        CAN_READ_REPOSITORY,
        CAN_RUN_TESTS,
        CAN_RUN_BENCHMARK,
        CAN_REVIEW,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="SEMANTIC_REASONER",
    functional_roles=("ANALYSIS", "DIAGNOSIS", "ROOT_CAUSE", "PROPOSAL"),
)

AGENT_OFFICE_CODEX_INDEPENDENT_REVIEW_RECORD = CapabilityRecord(
    capability_id="agent-office.codex.independent-review",
    capability_type="AGENT",
    domain="development",
    implementation=(
        "Agent Office independent Codex review task-owner in a separate read-only "
        "AgentSession over the same authenticated Codex backend"
    ),
    input_contract=(
        "DelegatedTaskLease + persisted proposal/root-cause/evidence artifact refs + exact base SHA"
    ),
    output_contract="IndependentReviewEvidence + AgentOfficeExecutionResult",
    requirements=(
        "DeepSeek Harness DEVELOPMENT authorization",
        "Agent Office delegated lease",
        "Codex CLI authenticated",
        "separate reviewer AgentSession",
        "disposable git worktree",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=(
        "agent-office", "codex", "independent-review", "readonly",
        "review", "task-owner", "delegated-autonomy",
    ),
    security_boundary=(
        "DeepSeek Harness sole authority; reviewer is read-only, receives only persisted "
        "artifact inputs, cannot mutate repository, push, merge, publish, access secrets "
        "or approve its own proposal."
    ),
    cost_class="BOUNDED_BY_LEASE",
    quota_class="CODEX_ACCOUNT",
    latency_class="MODEL_DEPENDENT",
    quality_class="INDEPENDENT_STRUCTURED_REVIEW_WITH_EVIDENCE",
    evidence_contract="app.services.agent_office.contracts.AgentOfficeExecutionResult",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.agent_office_harness_service.execute_authorized_agent_office_specialist"
    ),
    version="1",
    provider_id="codex",
    agent_id="codex-independent-reviewer",
    side_effects=("ephemeral worktree", "structured runtime artifact"),
    supports_parallelism=True,
    supports_retry=True,
    supports_resume=True,
    supports_review=True,
    side_effect_class="READ_ONLY",
    default_read_scope=("app", "scripts", "tests", ".github/workflows", "config", "integrations"),
    default_write_scope=(),
    allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
    health_policy="CODEX_AUTH_REQUIRED",
    execution_operations=(
        CAN_SEMANTIC_REASONING,
        CAN_READ_REPOSITORY,
        CAN_REVIEW,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="INDEPENDENT_REVIEWER",
    functional_roles=("REVIEW",),
)

SECURITY_REPOSITORY_REVIEW_RECORD = CapabilityRecord(
    capability_id="security.review.repository",
    capability_type="AGENT",
    domain="security",
    implementation=(
        "BR Security Guardian specialization of the proven Agent Office independent Codex "
        "reviewer in a separate read-only AgentSession/disposable workspace"
    ),
    input_contract=(
        "Harness-authorized security review task + exact candidate SHA/tree/diff digest + "
        "sanitized deterministic scanner evidence"
    ),
    output_contract="SecurityFinding/v1 + SecurityReviewReceipt/v1",
    requirements=(
        "DeepSeek Harness REVIEW/DEVELOPMENT authorization",
        "Agent Office delegated independent-review lease",
        "separate reviewer AgentSession",
        "separate worker/authorization identity",
        "disposable read-only worktree",
        "no secret-value or raw-owner-voice access",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT", "REVIEW"),
    policy_tags=(
        "security", "appsec", "supply-chain", "github-actions", "independent-review",
        "readonly", "evidence", "least-privilege",
    ),
    security_boundary=(
        "DeepSeek Harness remains sole authority. Security Guardian observes, audits, "
        "classifies and proposes remediation only; no repository write, push, merge, "
        "publish, deploy, permission mutation, credential mutation, secret-value access "
        "or self-approval."
    ),
    cost_class="BOUNDED_BY_LEASE",
    quota_class="CODEX_ACCOUNT",
    latency_class="MODEL_DEPENDENT",
    quality_class="INDEPENDENT_SECURITY_REVIEW_WITH_DETERMINISTIC_EVIDENCE",
    evidence_contract="app.services.security_guardian_service.SecurityReviewReceipt",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.agent_office_harness_service.execute_authorized_agent_office_specialist"
    ),
    version="1",
    provider_id="codex",
    agent_id="codex-security-reviewer",
    side_effects=("ephemeral read-only worktree", "sanitized structured security artifact"),
    authority="NONE",
    memory_write="NONE",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    supports_parallelism=False,
    supports_retry=True,
    supports_resume=True,
    supports_review=True,
    side_effect_class="READ_ONLY",
    default_read_scope=(
        "app", "scripts", "tests", ".github", "config", "integrations",
        "pyproject.toml", "requirements*.txt", "Dockerfile*", "SECURITY.md",
    ),
    default_write_scope=(),
    allowed_tools=("rg", "cat", "pytest", "security-evidence"),
    health_policy="CODEX_AUTH_REQUIRED",
    execution_operations=(
        CAN_SEMANTIC_REASONING,
        CAN_READ_REPOSITORY,
        CAN_REVIEW,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="INDEPENDENT_REVIEWER",
    functional_roles=(
        "SECURITY_REVIEW",
        "THREAT_ANALYSIS",
        "SECURITY_EVIDENCE",
        "REMEDIATION_PROPOSAL",
    ),
)

if _REGISTRY._by_id.get(SECURITY_REPOSITORY_REVIEW_RECORD.capability_id) is not None:
    raise ValueError("Duplicate security.review.repository Registry record")
_REGISTRY._by_id[SECURITY_REPOSITORY_REVIEW_RECORD.capability_id] = SECURITY_REPOSITORY_REVIEW_RECORD
_REGISTRY._records = tuple(sorted(
    (*_REGISTRY._records, SECURITY_REPOSITORY_REVIEW_RECORD),
    key=lambda item: item.capability_id,
))


SECURITY_SENSOR_RECORDS = (
    CapabilityRecord(
        capability_id="security.scan.github-actions",
        capability_type="TOOL",
        domain="security/github-actions",
        implementation="Deterministic GitHub Actions policy scanner consumed by BR Security Guardian",
        input_contract="candidate SHA/tree + workflow/action text",
        output_contract="SecurityEvidence/v1",
        requirements=("Harness-authorized review context", "repository content treated as untrusted data"),
        maturity=FUNCTIONAL,
        availability=AVAILABLE,
        allowed_actions=("DEVELOPMENT", "REVIEW"),
        policy_tags=("security","github-actions","deterministic","readonly"),
        security_boundary="Read-only deterministic sensor; no secret access, no repository mutation, no policy authority.",
        cost_class="FREE_NO_BILLING",
        quota_class="LOCAL_DETERMINISTIC",
        latency_class="LOCAL",
        quality_class="DETERMINISTIC_FAIL_CLOSED",
        evidence_contract="SecurityEvidence/v1",
        fallback_eligibility=False,
        executor_binding="app.services.security_guardian_service.execute_security_scan_github_actions",
        version="1",
        provider_id="internal",
        authority="NONE", memory_write="NONE", routing_authority="NONE",
        editorial_authority="NONE", publication_authority="NONE",
        supports_resume=True, supports_review=False, side_effect_class="READ_ONLY",
        default_read_scope=(".github/workflows",".github/actions"),
        default_write_scope=(), allowed_tools=(), health_policy="DEFAULT",
        execution_kind="VALIDATOR", functional_roles=("SECURITY_EVIDENCE",),
    ),
    CapabilityRecord(
        capability_id="security.scan.code",
        capability_type="TOOL",
        domain="security/code",
        implementation="Deterministic normalized static-analysis evidence adapter",
        input_contract="candidate SHA/tree + sanitized static-analysis findings",
        output_contract="SecurityEvidence/v1",
        requirements=("Harness-authorized review context", "sanitized scanner evidence"),
        maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("DEVELOPMENT","REVIEW"),
        policy_tags=("security","sast","codeql","deterministic","readonly"),
        security_boundary="Read-only scanner evidence normalization only; no code mutation or secret access.",
        cost_class="FREE_NO_BILLING", quota_class="LOCAL_DETERMINISTIC", latency_class="LOCAL",
        quality_class="DETERMINISTIC_EVIDENCE_ADAPTER", evidence_contract="SecurityEvidence/v1",
        fallback_eligibility=False,
        executor_binding="app.services.security_guardian_service.execute_security_scan_code",
        version="1", provider_id="internal", authority="NONE", memory_write="NONE",
        routing_authority="NONE", editorial_authority="NONE", publication_authority="NONE",
        supports_resume=True, side_effect_class="READ_ONLY",
        default_read_scope=("app","scripts","tests"), default_write_scope=(), allowed_tools=(),
        health_policy="DEFAULT", execution_kind="VALIDATOR", functional_roles=("SECURITY_EVIDENCE",),
    ),
    CapabilityRecord(
        capability_id="security.scan.dependencies",
        capability_type="TOOL",
        domain="security/dependencies",
        implementation="Deterministic normalized OSV/dependency-review evidence adapter",
        input_contract="candidate SHA/tree + sanitized dependency findings",
        output_contract="SecurityEvidence/v1",
        requirements=("Harness-authorized review context", "sanitized dependency scanner evidence"),
        maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("DEVELOPMENT","REVIEW"),
        policy_tags=("security","dependencies","osv","deterministic","readonly"),
        security_boundary="Read-only dependency evidence normalization; no package mutation or network authority.",
        cost_class="FREE_NO_BILLING", quota_class="LOCAL_DETERMINISTIC", latency_class="LOCAL",
        quality_class="DETERMINISTIC_EVIDENCE_ADAPTER", evidence_contract="SecurityEvidence/v1",
        fallback_eligibility=False,
        executor_binding="app.services.security_guardian_service.execute_security_scan_dependencies",
        version="1", provider_id="internal", authority="NONE", memory_write="NONE",
        routing_authority="NONE", editorial_authority="NONE", publication_authority="NONE",
        supports_resume=True, side_effect_class="READ_ONLY",
        default_read_scope=("pyproject.toml","requirements*.txt","package-lock.json","pnpm-lock.yaml","yarn.lock"),
        default_write_scope=(), allowed_tools=(), health_policy="DEFAULT",
        execution_kind="VALIDATOR", functional_roles=("SECURITY_EVIDENCE",),
    ),
    CapabilityRecord(
        capability_id="security.scan.secrets",
        capability_type="TOOL",
        domain="security/secrets",
        implementation="Deterministic secret-pattern scanner with fingerprint-only evidence",
        input_contract="candidate SHA/tree + repository text surfaces",
        output_contract="SecurityEvidence/v1 without secret values",
        requirements=("Harness-authorized review context", "secret values never serialized"),
        maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("DEVELOPMENT","REVIEW"),
        policy_tags=("security","secrets","deterministic","readonly","redacted"),
        security_boundary="Read-only; emits finding type/path/fingerprint only and never secret values.",
        cost_class="FREE_NO_BILLING", quota_class="LOCAL_DETERMINISTIC", latency_class="LOCAL",
        quality_class="DETERMINISTIC_REDACTED_FAIL_CLOSED", evidence_contract="SecurityEvidence/v1",
        fallback_eligibility=False,
        executor_binding="app.services.security_guardian_service.execute_security_scan_secrets",
        version="1", provider_id="internal", authority="NONE", memory_write="NONE",
        routing_authority="NONE", editorial_authority="NONE", publication_authority="NONE",
        supports_resume=True, side_effect_class="READ_ONLY",
        default_read_scope=("repository-candidate-tree",), default_write_scope=(), allowed_tools=(),
        health_policy="DEFAULT", execution_kind="VALIDATOR", functional_roles=("SECURITY_EVIDENCE",),
    ),
    CapabilityRecord(
        capability_id="security.scan.supply-chain",
        capability_type="TOOL",
        domain="security/supply-chain",
        implementation="Deterministic normalized action-pinning/Scorecard/provenance evidence adapter",
        input_contract="candidate SHA/tree + sanitized supply-chain evidence",
        output_contract="SecurityEvidence/v1",
        requirements=("Harness-authorized review context", "content-addressed scanner evidence"),
        maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("DEVELOPMENT","REVIEW"),
        policy_tags=("security","supply-chain","scorecard","provenance","readonly"),
        security_boundary="Read-only supply-chain evidence adapter; no release or deployment authority.",
        cost_class="FREE_NO_BILLING", quota_class="LOCAL_DETERMINISTIC", latency_class="LOCAL",
        quality_class="DETERMINISTIC_EVIDENCE_ADAPTER", evidence_contract="SecurityEvidence/v1",
        fallback_eligibility=False,
        executor_binding="app.services.security_guardian_service.execute_security_scan_supply_chain",
        version="1", provider_id="internal", authority="NONE", memory_write="NONE",
        routing_authority="NONE", editorial_authority="NONE", publication_authority="NONE",
        supports_resume=True, side_effect_class="READ_ONLY",
        default_read_scope=(".github","dependency-manifests","Dockerfile*"), default_write_scope=(),
        allowed_tools=(), health_policy="DEFAULT", execution_kind="VALIDATOR",
        functional_roles=("SECURITY_EVIDENCE",),
    ),
    CapabilityRecord(
        capability_id="security.audit.github-posture",
        capability_type="TOOL",
        domain="security/github-posture",
        implementation="Sanitized deterministic GitHub security-posture evidence adapter",
        input_contract="candidate SHA/tree + sanitized GitHub repository posture metadata",
        output_contract="SecurityEvidence/v1",
        requirements=("Harness-authorized review context", "secret values excluded from API evidence"),
        maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("DEVELOPMENT","REVIEW"),
        policy_tags=("security","github","posture","deterministic","readonly"),
        security_boundary="Consumes sanitized metadata only; cannot modify GitHub settings, permissions, keys, secrets or rulesets.",
        cost_class="FREE_NO_BILLING", quota_class="GITHUB_API_READ", latency_class="REMOTE_READ",
        quality_class="SANITIZED_POSTURE_EVIDENCE", evidence_contract="SecurityEvidence/v1",
        fallback_eligibility=False,
        executor_binding="app.services.security_guardian_service.execute_security_audit_github_posture",
        version="1", provider_id="github", authority="NONE", memory_write="NONE",
        routing_authority="NONE", editorial_authority="NONE", publication_authority="NONE",
        supports_resume=True, side_effect_class="READ_ONLY", default_read_scope=(),
        default_write_scope=(), allowed_tools=(), health_policy="GITHUB_READ_METADATA_REQUIRED",
        execution_kind="VALIDATOR", functional_roles=("SECURITY_EVIDENCE",),
    ),
)

for _security_sensor_record in SECURITY_SENSOR_RECORDS:
    if _REGISTRY._by_id.get(_security_sensor_record.capability_id) is not None:
        raise ValueError(f"Duplicate security sensor Registry record: {_security_sensor_record.capability_id}")
    _REGISTRY._by_id[_security_sensor_record.capability_id] = _security_sensor_record
_REGISTRY._records = tuple(sorted(
    (*_REGISTRY._records, *SECURITY_SENSOR_RECORDS),
    key=lambda item: item.capability_id,
))


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

    supports_parallelism=True,
    supports_retry=True,
    supports_resume=True,
    supports_review=True,
    side_effect_class="BOUNDED_MUTATION",
    default_read_scope=("app", "scripts", "tests", ".github/workflows", "config", "integrations"),
    default_write_scope=("app", "scripts", "tests"),
    allowed_tools=("git", "python", "pytest", "codex", "rg", "cat", "ls", "sed", "head", "wc"),
    health_policy="CODEX_AUTH_REQUIRED",
    execution_operations=(
        CAN_SEMANTIC_REASONING,
        CAN_READ_REPOSITORY,
        CAN_WRITE_REPOSITORY,
        CAN_RUN_TESTS,
        CAN_RUN_BENCHMARK,
        CAN_MUTATE_CANDIDATE,
        CAN_REVIEW,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="MUTATION_EXECUTOR",
    functional_roles=("APPLY",),
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
    side_effect_class="EXTERNAL_SIDE_EFFECT",
    execution_operations=(
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
)

NARRATION_GENERATE_PTBR_RECORD = CapabilityRecord(
    capability_id="narration.generate.pt-BR",
    capability_type="CAPABILITY",
    domain="narration",
    implementation="Harness-governed owner-voice PT-BR narration bundle materialization",
    input_contract="approved PT-BR script sections + BR_OWNER_V1 private identity + exact Harness EXECUTION lineage",
    output_contract="versioned narration-bundle with A1 master, segment manifest, voice identity lineage and QA",
    requirements=(
        "persisted Harness EXECUTION authorization",
        "Harness Routing/Policy decision",
        "BR_OWNER_V1 approved owner consent",
        "private voice runtime + materialized identity profile",
        "FFmpeg/ffprobe master QA",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("narration", "voice", "pt-br", "a1", "cache", "timing", "owner-voice-only"),
    security_boundary=(
        "DeepSeek Harness remains sole authority; narration materializes only the approved script "
        "with BR_OWNER_V1. Legacy Voice B/Edge TTS fallback is forbidden; no editorial or publication authority."
    ),
    cost_class="SELF_HOSTED_COMPUTE",
    quota_class="PRIVATE_VOICE_RUNTIME_BOUNDED",
    latency_class="REMOTE_ASYNC_SEGMENTED",
    quality_class="CONTENT_ADDRESSED_SEGMENTS_MASTER_EBU_R128_QA",
    evidence_contract="narration-manifest.json + narration-qa.json + speech-timing.json + voice identity evidence",
    fallback_eligibility=False,
    executor_binding="app.services.narration_pipeline.execute_narration_capability",
    version="3",
    provider_id="internal-voice-plane",
    agent_id="audiovisual-worker",
    side_effects=("narration bundle artifact", "content-addressed segment cache", "voice identity evidence"),
    health_policy="VOICE_RUNTIME_AND_IDENTITY_REQUIRED",
)

GTA6_KNOWLEDGE_RETRIEVE_RECORD = CapabilityRecord(
    capability_id="gta6.knowledge.retrieve",
    capability_type="CAPABILITY",
    domain="gta6-knowledge",
    implementation=(
        "Harness-governed bounded retrieval over canonical GTA6 claims, "
        "entity graph, source quality, freshness and novelty"
    ),
    input_contract="natural GTA6 query + bounded top-k/context byte budget",
    output_contract="bounded knowledge units + claim/evidence provenance + retrieval scoring evidence",
    requirements=(
        "persisted Harness RESEARCH, EDITORIAL or DECISION authorization",
        "exact Global Capability Registry executor binding",
        "canonical BR SQLite Knowledge Brain",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("RESEARCH", "EDITORIAL", "DECISION"),
    policy_tags=(
        "gta6", "knowledge", "retrieval", "bounded-context", "graph",
        "source-quality", "freshness", "novelty", "zero-cost", "read-only",
    ),
    security_boundary=(
        "Read-only canonical retrieval. DeepSeek Harness remains sole authority; "
        "Hermes and agents may consume only the bounded result through Harness Broker. "
        "No canonical write, policy mutation, Obsidian authority, publication or provider call."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_SQLITE_BOUNDED",
    latency_class="LOCAL",
    quality_class="PROVENANCE_PRESERVING_MULTI_SIGNAL_RANKING",
    evidence_contract="bounded GTA6 knowledge units with claim/evidence/source lineage",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.gta6_knowledge_retrieval_service."
        "execute_gta6_knowledge_retrieval_capability"
    ),
    version="1",
    provider_id="internal",
    agent_id="gta6-knowledge-retriever",
    side_effects=(),
    authority="NONE",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    execution_operations=(
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
)

GTA6_DELTA_RESEARCH_RECORD = CapabilityRecord(
    capability_id="gta6.research.delta",
    capability_type="AGENT",
    domain="gta6",
    implementation=(
        "Harness-governed continuous GTA6 delta research agent with bounded "
        "Knowledge Brain retrieval and source-fingerprint short circuit"
    ),
    input_contract=(
        "topic query + subject + official source URL + goal_id + persisted Harness RESEARCH authorization"
    ),
    output_contract=(
        "KNOWN_STATE vs CURRENT_SOURCE_STATE delta + bounded candidate claims + provenance + source metrics"
    ),
    requirements=(
        "DeepSeek Harness RESEARCH authorization",
        "Global Capability Registry routing",
        "GitHub Actions cloud execution for live network collection",
        "bounded Knowledge Brain retrieval before collection",
        "official Rockstar source for automatic knowledge promotion",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("RESEARCH",),
    policy_tags=(
        "gta6", "research", "delta", "continuous-intelligence", "knowledge",
        "provenance", "memory-retrieval", "zero-cost",
    ),
    security_boundary=(
        "DeepSeek Harness is sole authority. The research agent may read public sources and "
        "operational source fingerprints, but cannot promote canonical knowledge, write Obsidian, "
        "change policy, render media, synthesize voice, upload or publish."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="PUBLIC_WEB_GITHUB_ACTIONS",
    latency_class="DELTA_SHORT_CIRCUIT_OR_REMOTE_WEB",
    quality_class="SOURCE_GROUNDED_PROVENANCE_FIRST",
    evidence_contract="delta research result + official source fingerprint + candidate claim provenance",
    fallback_eligibility=False,
    executor_binding="app.services.continuous_intelligence_service.execute_gta6_delta_research_capability",
    version="1",
    provider_id="internal",
    agent_id="gta6-research-agent",
    side_effects=("continuous_source_state checkpoint update",),
    authority="DELEGATED_ONLY",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
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
    execution_operations=(CAN_PRODUCE_ARTIFACT_REFS,),
)


GTA6_RESEARCH_SEMANTIC_RECORD = CapabilityRecord(
    capability_id="gta6.research.semantic-synthesis",
    capability_type="AGENT",
    domain="research",
    implementation="Harness-subordinated semantic synthesis over persisted GTA6 research artifacts",
    input_contract="direct TaskResultEnvelope research artifacts + objective + persisted Harness RESEARCH authorization",
    output_contract="provider-grounded topic synthesis + findings/risks/evidence refs + task output ref",
    requirements=(
        "persisted Harness RESEARCH authorization",
        "direct dependency TaskResultEnvelope artifact",
        "Harness-selected healthy zero-cost semantic provider",
        "exact Registry executor binding",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("RESEARCH",),
    policy_tags=(
        "gta6", "research", "semantic", "reasoning", "synthesis",
        "evidence", "artifact-lineage", "zero-cost",
    ),
    security_boundary=(
        "DeepSeek Harness is sole authority. This capability may reason only over "
        "persisted dependency research artifacts using the Harness-selected provider; "
        "it cannot collect sources, mutate canonical knowledge, publish, or choose routing."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="HARNESS_AI_PROVIDER_POLICY",
    latency_class="REMOTE_AI",
    quality_class="EVIDENCE_GROUNDED_STRUCTURED_SEMANTIC_SYNTHESIS",
    evidence_contract="semantic research JSON + HarnessAIProviderEvidence + TaskResultEnvelope lineage",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.production_mission_capability_adapters."
        "execute_research_semantic_synthesis_task"
    ),
    version="1",
    provider_id=None,
    agent_id="gta6-research-semantic",
    side_effects=(),
    authority="NONE",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    execution_operations=(
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
)

TELEGRAM_REVIEW_DELIVERY_RECORD = CapabilityRecord(
    capability_id="telegram.review.deliver",
    capability_type="PRESENTATION",
    domain="telegram-outbound",
    implementation="Harness-governed outbound human-review delivery through the canonical Telegram group surface",
    input_contract="persisted direct dependency artifact + genuine editorial lineage + human-readable review sections",
    output_contract="Telegram SENT receipts/message refs with outbound direction evidence",
    requirements=(
        "persisted Harness EXECUTION authorization",
        "direct TaskResultEnvelope dependency artifact",
        "canonical Telegram group human surface",
        "genuine editorial artifact lineage",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=(
        "telegram", "outbound", "human-review", "delivery", "presentation",
        "artifact-lineage", "zero-cost",
    ),
    security_boundary=(
        "Outbound presentation only: Harness -> Telegram -> human. It has no ingress, "
        "memory, routing, editorial, scheduler, promotion, or publication authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="TELEGRAM_API",
    latency_class="REMOTE_API",
    quality_class="HUMAN_READABLE_GENUINE_ARTIFACT_FAIL_CLOSED",
    evidence_contract="Telegram delivery receipts + message artifact refs + TaskResultEnvelope lineage",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.production_mission_capability_adapters."
        "execute_telegram_review_delivery_task"
    ),
    version="1",
    provider_id="telegram-bot-api",
    side_effects=("Telegram human-review messages",),
    side_effect_class="EXTERNAL_SIDE_EFFECT",
    authority="NONE",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    execution_operations=(
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="PRESENTATION",
    functional_roles=("PRESENTATION",),
    execution_effects=(EFFECT_HUMAN_MESSAGE_DELIVERY,),
    execution_surfaces=(SURFACE_TELEGRAM_GROUP,),
    output_contract_ids=(OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1,),
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
    execution_operations=(),
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
    execution_operations=(
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
)

GTA6_BRAIN_DECISION_RECORD = CapabilityRecord(
    capability_id="gta6.brain.decide",
    capability_type="AGENT",
    domain="gta6-decision",
    implementation="Harness-subordinated GTA6 Brain domain decision specialist",
    input_contract=(
        "Harness-owned GTA6DomainProjection/v1 + mission/task/goal lineage"
    ),
    output_contract=(
        "BrainDecision + GTA6 domain projection identity + "
        "AgentInvocationReceipt + canonical Harness evidence"
    ),
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
    version="2",
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

TELEGRAM_OBSIDIAN_ATTACHMENT_RECORD = CapabilityRecord(
    capability_id="telegram.attachment.obsidian.materialize",
    capability_type="EXECUTOR",
    domain="telegram-ingress",
    implementation=(
        "Harness-governed materialization of one remotely verified Telegram "
        "attachment into the configured local Obsidian vault"
    ),
    input_contract=(
        "persisted telegram_user_input identity + staged verified file bytes + "
        "bounded vault target"
    ),
    output_contract=(
        "content-addressed vault attachment + Markdown companion note + "
        "CanonicalExecutionResult"
    ),
    requirements=(
        "persisted Harness EXECUTION authorization",
        "exact Global Capability Registry executor binding",
        "remotely verified Telegram identity",
        "configured local Obsidian vault",
        "bounded staged file <= official Bot API default download limit",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=(
        "telegram", "obsidian", "attachment", "artifact", "provenance", "zero-cost"
    ),
    security_boundary=(
        "DeepSeek Harness remains sole authority. The capability receives staged "
        "file bytes but no transport credential. It may write only content-addressed "
        "attachment bytes and a companion note inside the configured vault. "
        "Owner voice and brand assets are excluded; no canonical memory promotion, "
        "publication, semantic authority or heavy media analysis is granted."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="CONTENT_ADDRESSED_PROVENANCE_FAIL_CLOSED",
    evidence_contract="CanonicalExecutionResult + vault-relative artifact refs",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.telegram_obsidian_attachment_bridge_service."
        "execute_telegram_obsidian_attachment_capability"
    ),
    version="1",
    provider_id="internal",
    agent_id="telegram-obsidian-attachment-bridge",
    side_effects=("bounded Android Obsidian vault artifact write",),
    authority="NONE",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
)

OBSIDIAN_INBOX_RECORD = CapabilityRecord(
    capability_id="memory.obsidian.inbox.ingest",
    capability_type="EXECUTOR",
    domain="human-memory",
    implementation="Harness-governed deterministic Obsidian Inbox human-note ingestion",
    input_contract="small Markdown human_note + explicit target/goal lineage",
    output_contract="canonical HumanDecision + HarnessEpisode + gated MemoryCandidate",
    requirements=(
        "persisted Harness EXECUTION authorization",
        "exact Global Capability Registry executor binding",
        "bounded Markdown input",
        "no Android vault write from cloud",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("memory", "obsidian", "human-note", "learning", "inbox", "zero-cost"),
    security_boundary=(
        "Obsidian is input/projection only. DeepSeek Harness remains sole authority; "
        "ingestion may create a canonical human decision and CANDIDATE memory only, "
        "never ACTIVE memory, model execution, publication, media work or Android vault mutation."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="BOUNDED_MARKDOWN_PROVENANCE_FAIL_CLOSED",
    evidence_contract="HarnessEpisode + CANDIDATE harness_memory + canonical HumanDecision",
    fallback_eligibility=False,
    executor_binding="app.services.obsidian_memory_service.execute_obsidian_inbox_capability",
    version="1",
    provider_id="internal",
    agent_id="obsidian-inbox-ingress",
    side_effects=("canonical Learning Plane append",),
    authority="NONE",
    memory_write="CANDIDATE_ONLY",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
)

OBSIDIAN_EXPORT_RECORD = CapabilityRecord(
    capability_id="memory.obsidian.export",
    capability_type="EXECUTOR",
    domain="human-memory",
    implementation="Deterministic published-memory Markdown projection from canonical BR SQLite",
    input_contract="canonical Learning Plane state + bounded project/system selectors",
    output_contract="small obsidian-memory-export Markdown package + manifest",
    requirements=(
        "persisted Harness EXECUTION authorization",
        "exact Global Capability Registry executor binding",
        "cloud artifact output path",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("EXECUTION",),
    policy_tags=("memory", "obsidian", "projection", "markdown", "zero-cost"),
    security_boundary=(
        "Read-only projection of canonical memory. Cannot write Android storage, promote memory, "
        "change HumanDecision, execute agents, render media or publish externally."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="DETERMINISTIC_HUMAN_READABLE_PROJECTION",
    evidence_contract="obsidian-memory-export/v1 manifest",
    fallback_eligibility=False,
    executor_binding="app.services.obsidian_memory_service.execute_obsidian_export_capability",
    version="1",
    provider_id="internal",
    agent_id="obsidian-memory-publisher",
    side_effects=("workflow artifact Markdown write",),
    authority="NONE",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
)

WEB_SEARCH_DISCOVER_RECORD = CapabilityRecord(
    capability_id="web.search.discover",
    capability_type="CAPABILITY",
    domain="web-acquisition",
    implementation=(
        "Harness-governed generic web discovery capability; initial transport "
        "binding is APILayer Google Search Results API"
    ),
    input_contract="bounded search query under Harness authorization",
    output_contract="normalized URL/title/snippet results + source provenance",
    requirements=("APILAYER_API_KEY for initial transport", "FREE_QUOTA_LIMITED"),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("RESEARCH", "EDITORIAL", "DEVELOPMENT", "DECISION"),
    policy_tags=("web", "search", "research-tool", "apilayer", "zero-cost"),
    security_boundary=(
        "DeepSeek Harness selects and authorizes the generic capability; agents "
        "never receive APILAYER_API_KEY or choose transport credentials."
    ),
    cost_class="FREE_QUOTA_LIMITED",
    quota_class="APILAYER_PRODUCT_FREE_QUOTA",
    latency_class="EXTERNAL_NETWORK",
    quality_class="TRANSPORT_ONLY_SOURCE_AUTHORITY_UNCHANGED",
    evidence_contract="structured web discovery result with original-source provenance",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.web_acquisition_capability_service."
        "execute_web_search_discover"
    ),
    version="1",
    provider_id="apilayer_google_search",
    side_effects=("external network read",),
    side_effect_class="READ_ONLY",
    execution_operations=(CAN_PRODUCE_ARTIFACT_REFS,),
    execution_kind="TOOL",
    functional_roles=("TOOL",),
)

WEB_SOURCE_ACQUIRE_RECORD = CapabilityRecord(
    capability_id="web.source.acquire",
    capability_type="CAPABILITY",
    domain="web-acquisition",
    implementation=(
        "Harness-governed cache/direct-first source acquisition with APILayer "
        "Scraper API Lite only as bounded transport fallback"
    ),
    input_contract="original http(s) source URL",
    output_contract="bounded normalized content + original-source provenance",
    requirements=("direct acquisition first", "APILAYER_API_KEY only for fallback"),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("RESEARCH", "EDITORIAL", "DEVELOPMENT", "DECISION"),
    policy_tags=("web", "source", "acquire", "research-tool", "apilayer", "zero-cost"),
    security_boundary=(
        "Canonical cache and direct fetch run before APILayer; secret remains at "
        "executor boundary and APILayer is transport, never factual authority."
    ),
    cost_class="FREE_QUOTA_LIMITED",
    quota_class="APILAYER_PRODUCT_FREE_QUOTA",
    latency_class="CACHE_DIRECT_THEN_EXTERNAL",
    quality_class="ORIGINAL_SOURCE_PROVENANCE_FAIL_CLOSED",
    evidence_contract="source content hash + transport provenance + quota evidence",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.web_acquisition_capability_service."
        "execute_web_source_acquire"
    ),
    version="1",
    provider_id="apilayer_scraper",
    side_effects=("external network read", "bounded local cache write"),
    side_effect_class="READ_ONLY",
    execution_operations=(CAN_PRODUCE_ARTIFACT_REFS,),
    execution_kind="TOOL",
    functional_roles=("TOOL",),
)

WEB_EVIDENCE_SNAPSHOT_RECORD = CapabilityRecord(
    capability_id="web.evidence.snapshot",
    capability_type="CAPABILITY",
    domain="web-acquisition",
    implementation=(
        "Harness-governed explicit evidence snapshot; initial transport binding "
        "is APILayer URL-to-PDF"
    ),
    input_contract="original http(s) source URL + snapshot_required=true",
    output_contract="bounded PDF snapshot bytes + original-source provenance",
    requirements=("APILAYER_API_KEY", "FREE_QUOTA_LIMITED", "explicit snapshot need"),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("RESEARCH", "EDITORIAL", "DEVELOPMENT", "DECISION"),
    policy_tags=("web", "snapshot", "evidence", "research-tool", "apilayer", "zero-cost"),
    security_boundary=(
        "Explicit bounded snapshot only; agents never receive transport secret; "
        "original source URL remains factual provenance."
    ),
    cost_class="FREE_QUOTA_LIMITED",
    quota_class="APILAYER_PRODUCT_FREE_QUOTA",
    latency_class="EXTERNAL_NETWORK",
    quality_class="BOUNDED_PDF_EVIDENCE_SNAPSHOT",
    evidence_contract="PDF sha256 + original-source provenance + quota evidence",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.web_acquisition_capability_service."
        "execute_web_evidence_snapshot"
    ),
    version="1",
    provider_id="apilayer_url_to_pdf",
    side_effects=("external network read",),
    side_effect_class="READ_ONLY",
    execution_operations=(CAN_PRODUCE_ARTIFACT_REFS,),
    execution_kind="TOOL",
    functional_roles=("TOOL",),
)

_YOUTUBE_DEPARTMENT_RECORDS = youtube_department_records()

for _record in (
    AGENT_OFFICE_RECORD,
    DEVELOPMENT_CHECKPOINT_PERSIST_RECORD,
    HERMES_MULTIAGENT_RUNTIME_RECORD,
    ARTIFACT_EVIDENCE_REUSE_RECORD,
    WEB_SEARCH_DISCOVER_RECORD,
    WEB_SOURCE_ACQUIRE_RECORD,
    WEB_EVIDENCE_SNAPSHOT_RECORD,
    AGENT_OFFICE_DETERMINISTIC_READONLY_RECORD,
    AGENT_OFFICE_CODEX_READONLY_RECORD,
    AGENT_OFFICE_CODEX_INDEPENDENT_REVIEW_RECORD,
    AGENT_OFFICE_CODEX_BOUNDED_DEVELOPMENT_RECORD,
    PHONE_CONTROL_RECORD,
    PRODUCTION_MEDIA_SELECTION_RECORD,
    PRODUCTION_MEDIA_BINDING_RECORD,
    PRODUCTION_BRAND_ASSET_BINDING_RECORD,
    PRODUCTION_RENDER_RECORD,
    NARRATION_GENERATE_PTBR_RECORD,
    GTA6_KNOWLEDGE_RETRIEVE_RECORD,
    GTA6_DELTA_RESEARCH_RECORD,
    FRESH_GTA6_RESEARCH_RECORD,
    GTA6_RESEARCH_SEMANTIC_RECORD,
    TELEGRAM_REVIEW_DELIVERY_RECORD,
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
    TELEGRAM_OBSIDIAN_ATTACHMENT_RECORD,
    OBSIDIAN_INBOX_RECORD,
    OBSIDIAN_EXPORT_RECORD,
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
    "editorial.process": "app.services.production_mission_capability_adapters.execute_editorial_process_task",
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

# Make the production-relevant contracts explicit to the semantic planner.
# This is metadata only: authority and executable identities remain unchanged.
for _capability_id, _metadata in {
    "gta6.research": {
        "implementation": "Harness-governed deterministic current GTA6 collection + Knowledge retrieval + editorial scoring/Goal creation",
        "input_contract": "current GTA6 research intent under persisted Harness RESEARCH authorization",
        "output_contract": "fresh source-grounded research artifact refs + deterministic novelty/editorial evaluation + selected Goal/Idea/queue when approved",
        "execution_operations": (CAN_PRODUCE_ARTIFACT_REFS,),
    },
    "editorial.process": {
        "implementation": "Harness-governed AI-backed targeted editorial queue consumer over persisted research lineage",
        "input_contract": "Harness-selected Goal + direct dependency TaskResultEnvelope + verified research context + dynamic zero-cost semantic provider",
        "output_contract": "natural PT-BR script + ScriptSpec + ContentItem + persisted ProductionPlan artifact refs",
        "execution_operations": (
            CAN_SEMANTIC_REASONING,
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        ),
        "execution_kind": "SEMANTIC_REASONER",
        "functional_roles": ("EDITORIAL_GENERATION",),
        "output_contract_ids": (
            OUTPUT_CONTRACT_EDITORIAL_SCRIPT_BUNDLE_V1,
        ),
    },
    "production.plan": {
        "input_contract": "direct dependency TaskResultEnvelope containing persisted ContentItem",
        "output_contract": "persisted ProductionPlan + production-plan artifact ref + direct input refs",
        "execution_operations": (
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        ),
    },
}.items():
    _existing = _REGISTRY._by_id.get(_capability_id)
    if _existing is None:
        raise ValueError(f"Missing production capability Registry record: {_capability_id}")
    _described = replace(_existing, **_metadata)
    _REGISTRY._by_id[_capability_id] = _described
    _REGISTRY._records = tuple(
        sorted(
            (_described if record.capability_id == _capability_id else record for record in _REGISTRY._records),
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

# Cross-provider fallback eligibility. Runtime health, zero-cost policy and
# current-run/profile proof still decide whether these providers may execute.
for _capability_id in ("ai.provider.tuxevil", "ai.provider.opencode-free"):
    _existing = _REGISTRY._by_id.get(_capability_id)
    if _existing is None:
        raise ValueError(
            f"Missing zero-cost fallback Registry record: {_capability_id}"
        )
    _fallback_enabled = replace(
        _existing,
        fallback_eligibility=True,
    )
    _REGISTRY._by_id[_capability_id] = _fallback_enabled
    _REGISTRY._records = tuple(
        sorted(
            (
                _fallback_enabled
                if record.capability_id == _capability_id
                else record
                for record in _REGISTRY._records
            ),
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


REPOSITORY_READ_SCOPED_RECORD = CapabilityRecord(
    capability_id="repository.read-scoped",
    capability_type="EXECUTOR",
    domain="repository-read",
    implementation=(
        "Harness-governed deterministic bounded repository reader/searcher"
    ),
    input_contract=(
        "Harness-authorized repository_root + task read scope + explicit "
        "paths or search terms"
    ),
    output_contract=(
        "RepositoryReadResult/v1 with bounded content and sha256 evidence"
    ),
    requirements=("DeepSeek Harness DEVELOPMENT authorization",),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=(
        "recovery",
        "repository",
        "read-only",
        "tool",
        "deterministic",
    ),
    security_boundary=(
        "Exact Harness authorization and Registry binding; read-only; "
        "requested paths must remain inside task-scoped read roots; no shell, "
        "repository mutation, secrets, publication, or policy authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="BOUNDED_READ_FAIL_CLOSED",
    evidence_contract=(
        "app.services.recovery_execution_service.RepositoryReadResult/v1"
    ),
    fallback_eligibility=False,
    executor_binding=(
        "app.services.recovery_execution_service."
        "execute_repository_read_scoped"
    ),
    version="1",
    provider_id="internal",
    agent_id="harness-repository-reader",
    side_effects=(),
    supports_parallelism=True,
    supports_retry=False,
    supports_resume=True,
    supports_review=False,
    side_effect_class="READ_ONLY",
    default_read_scope=(
        "app",
        "scripts",
        "tests",
        ".github/workflows",
        "config",
        "integrations",
    ),
    default_write_scope=(),
    allowed_tools=(),
    health_policy="DEFAULT",
    execution_operations=(
        CAN_READ_REPOSITORY,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="TOOL",
    functional_roles=(),
)

RECOVERY_APPLY_LOCAL_RECORD = CapabilityRecord(
    capability_id="harness.recovery.apply-local",
    capability_type="EXECUTOR",
    domain="recovery-execution",
    implementation=(
        "Harness-governed deterministic RecoveryCandidateSpec actuator in a "
        "disposable git worktree"
    ),
    input_contract=(
        "RecoveryCandidateSpec/v1 with ACCEPT review, AUTHORIZED Harness "
        "decision, base SHA, patch hash and path allowlist"
    ),
    output_contract="RecoveryApplyReceipt/v1",
    requirements=(
        "DeepSeek Harness DEVELOPMENT authorization",
        "git worktree support",
        "reviewed patch artifact",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=(
        "recovery",
        "apply",
        "sandbox",
        "deterministic",
        "mutation",
    ),
    security_boundary=(
        "No reasoning or routing authority. Applies only reviewed hashed patch "
        "artifacts to a detached disposable worktree after base-SHA and path "
        "allowlist verification. Never pushes, merges, publishes, or executes "
        "model text as shell."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="SANDBOXED_PATCH_FAIL_CLOSED",
    evidence_contract=(
        "app.services.recovery_execution_service.RecoveryApplyReceipt"
    ),
    fallback_eligibility=False,
    executor_binding=(
        "app.services.recovery_execution_service."
        "execute_recovery_apply_capability"
    ),
    version="1",
    provider_id="internal",
    agent_id="harness-recovery-actuator",
    side_effects=("ephemeral worktree", "local candidate commit"),
    supports_parallelism=False,
    supports_retry=False,
    supports_resume=True,
    supports_review=False,
    side_effect_class="BOUNDED_MUTATION",
    default_read_scope=(
        "app",
        "scripts",
        "tests",
        ".github/workflows",
        "config",
        "integrations",
    ),
    default_write_scope=(
        "app",
        "scripts",
        "tests",
        ".github/workflows",
        "config",
        "integrations",
    ),
    allowed_tools=("git",),
    health_policy="DEFAULT",
    execution_operations=(
        CAN_READ_REPOSITORY,
        CAN_WRITE_REPOSITORY,
        CAN_MUTATE_CANDIDATE,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="MUTATION_EXECUTOR",
    functional_roles=("APPLY",),
)

RECOVERY_VALIDATE_LOCAL_RECORD = CapabilityRecord(
    capability_id="harness.recovery.validate-local",
    capability_type="EXECUTOR",
    domain="recovery-validation",
    implementation=(
        "Harness-governed deterministic candidate validator in a detached "
        "disposable git worktree"
    ),
    input_contract="RecoveryCandidateSpec/v1 + RecoveryApplyReceipt/v1",
    output_contract="RecoveryValidationReceipt/v1",
    requirements=(
        "DeepSeek Harness DEVELOPMENT authorization",
        "git worktree support",
        "pytest",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=(
        "recovery",
        "validation",
        "tests",
        "deterministic",
        "read-only",
    ),
    security_boundary=(
        "No mutation or promotion authority. Executes only argv-validated "
        "python -m pytest -q commands against the detached candidate SHA; "
        "no shell interpolation, push, merge, publication, or policy authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="FOCUSED_TEST_VALIDATION_FAIL_CLOSED",
    evidence_contract=(
        "app.services.recovery_execution_service.RecoveryValidationReceipt"
    ),
    fallback_eligibility=False,
    executor_binding=(
        "app.services.recovery_execution_service."
        "execute_recovery_validate_capability"
    ),
    version="1",
    provider_id="internal",
    agent_id="harness-recovery-validator",
    side_effects=("ephemeral worktree", "test processes"),
    supports_parallelism=False,
    supports_retry=False,
    supports_resume=True,
    supports_review=False,
    side_effect_class="READ_ONLY",
    default_read_scope=(
        "app",
        "scripts",
        "tests",
        ".github/workflows",
        "config",
        "integrations",
    ),
    default_write_scope=(),
    allowed_tools=("git", "python", "pytest"),
    health_policy="DEFAULT",
    execution_operations=(
        CAN_READ_REPOSITORY,
        CAN_RUN_TESTS,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="VALIDATOR",
    functional_roles=("VALIDATE",),
)

for _recovery_record in (
    REPOSITORY_READ_SCOPED_RECORD,
    RECOVERY_APPLY_LOCAL_RECORD,
    RECOVERY_VALIDATE_LOCAL_RECORD,
):
    if _REGISTRY._by_id.get(_recovery_record.capability_id) is not None:
        raise ValueError(
            "Duplicate recovery capability id: "
            + _recovery_record.capability_id
        )
    _REGISTRY._by_id[_recovery_record.capability_id] = _recovery_record

_REGISTRY._records = tuple(
    sorted(
        (
            *_REGISTRY._records,
            REPOSITORY_READ_SCOPED_RECORD,
            RECOVERY_APPLY_LOCAL_RECORD,
            RECOVERY_VALIDATE_LOCAL_RECORD,
        ),
        key=lambda item: item.capability_id,
    )
)

# LTX-2.5 optional visual generation; runtime eligibility is checked at execution time.
LTX_25_VISUAL_RECORD = CapabilityRecord(
    capability_id="visual.generate.transform.ltx-2.5", capability_type="CAPABILITY", domain="audiovisual",
    implementation="Harness-governed LTX-2.5 synthetic visual generation/transform boundary feeding VEdit",
    input_contract="typed synthetic visual requirement + mission/task lineage + optional source asset refs",
    output_contract="GeneratedVisualAsset with typed provenance + visual QA status, or LTX_RUNTIME_UNAVAILABLE",
    requirements=("DeepSeek Harness EXECUTION authorization","eligible CUDA runtime with sufficient VRAM","Python >=3.12","accepted gated LTX-2.5 model access","locally ready official model components; no implicit download"),
    maturity=PARTIAL, availability=AVAILABLE, allowed_actions=("EXECUTION",),
    policy_tags=("visual","generation","transform","ltx-2.5","synthetic","vedit","non-evidence","runtime-gated"),
    security_boundary="Harness-only routing; GENERATED_VISUAL is never factual GTA VI evidence or OFFICIAL/PRIMARY/VERIFIED; no artificial padding, paid fallback, implicit weight download, publication authority, or VEdit replacement.",
    cost_class="FREE_NO_BILLING", quota_class="HARDWARE_GATED", latency_class="GPU_DEPENDENT",
    quality_class="RUNTIME_GATED_SYNTHETIC_VISUAL_QA_REQUIRED",
    evidence_contract="app.services.ltx_visual_capability_service.GeneratedVisualAsset",
    fallback_eligibility=False,
    executor_binding="app.services.ltx_visual_capability_service.execute_ltx_visual_capability",
    version="1", provider_id="lightricks-ltx-2.5", model_id="Lightricks/LTX-2.5",
    side_effects=("generated visual asset",), supports_parallelism=False, supports_retry=False,
    supports_resume=True, supports_review=True, side_effect_class="BOUNDED_MEDIA_GENERATION",
    default_read_scope=("content","artifacts"), default_write_scope=("artifacts/generated-visuals",),
    allowed_tools=("nvidia-smi","ltx-pipelines","ffmpeg"), health_policy="LTX_RUNTIME_ELIGIBILITY_REQUIRED",
    execution_operations=(CAN_CONSUME_ARTIFACT_REFS, CAN_PRODUCE_ARTIFACT_REFS),
    execution_kind="DETERMINISTIC_WORKER", functional_roles=("VISUAL_GENERATION",),
)
if _REGISTRY._by_id.get(LTX_25_VISUAL_RECORD.capability_id) is not None:
    raise ValueError("Duplicate LTX-2.5 capability id")
_REGISTRY._by_id[LTX_25_VISUAL_RECORD.capability_id] = LTX_25_VISUAL_RECORD
_REGISTRY._records = tuple(sorted((*_REGISTRY._records, LTX_25_VISUAL_RECORD), key=lambda item: item.capability_id))


BROWSER_QA_VALIDATE_RECORD = CapabilityRecord(
    capability_id="browser.qa.validate",
    capability_type="EXECUTOR",
    domain="browser-qa",
    implementation="Harness-governed deterministic Playwright real-browser validation executor for local VEdit frontend surfaces",
    input_contract="BrowserQARequest/v1 with loopback authorized_url, bounded scenarios and mission/task/candidate lineage",
    output_contract="BrowserQAReport/v1 plus content-addressed screenshot/trace/report refs",
    requirements=(
        "persisted DeepSeek Harness DEVELOPMENT authorization",
        "exact Global Capability Registry executor binding",
        "isolated Chromium context",
        "pinned Playwright runtime",
        "local VEdit/test fixture only",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=("browser","qa","playwright","frontend","ui","validation","accessibility","aria","visual","trace","read-only"),
    security_boundary="DeepSeek Harness sole authority; loopback-only, read-only, isolated, caller-non-overridable; no personal profile/credentials, unsafe code, arbitrary MCP server, file URL, publication, routing, policy, golden auto-update, or self-approval authority.",
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL_BROWSER",
    quality_class="REAL_BROWSER_DETERMINISTIC_QA_EVIDENCE",
    evidence_contract="app.services.browser_qa_harness_service.BrowserQAReport/v1",
    fallback_eligibility=False,
    executor_binding="app.services.browser_qa_harness_service.execute_browser_qa_capability",
    version="1",
    provider_id="internal",
    agent_id="browser-qa-validator",
    side_effects=("ephemeral isolated browser context","QA evidence artifacts"),
    authority="NONE",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    supports_parallelism=False,
    supports_retry=False,
    supports_resume=False,
    supports_review=False,
    side_effect_class="READ_ONLY",
    default_read_scope=("video-engine/frontend","artifacts/browser-qa"),
    default_write_scope=(),
    allowed_tools=("playwright-test",),
    health_policy="BROWSER_RUNTIME_REQUIRED",
    execution_operations=(CAN_RUN_TESTS,CAN_CONSUME_ARTIFACT_REFS,CAN_PRODUCE_ARTIFACT_REFS),
    execution_kind="TOOL",
    functional_roles=("QA",),
)
if _REGISTRY._by_id.get(BROWSER_QA_VALIDATE_RECORD.capability_id) is not None:
    raise ValueError("Duplicate browser QA capability id")
_REGISTRY._by_id[BROWSER_QA_VALIDATE_RECORD.capability_id] = BROWSER_QA_VALIDATE_RECORD
_REGISTRY._records = tuple(sorted((*_REGISTRY._records, BROWSER_QA_VALIDATE_RECORD), key=lambda item: item.capability_id))


BROWSER_QA_EXPLORE_RECORD = CapabilityRecord(
    capability_id="browser.qa.explore",
    capability_type="EXECUTOR",
    domain="browser-qa",
    implementation=(
        "Harness-governed bounded Playwright MCP explorer for local VEdit "
        "reproduction, observation and regression-test discovery"
    ),
    input_contract=(
        "BrowserExplorationRequest/v1 with loopback origin, exact candidate/"
        "mission/task lineage, explicit safe-tool subset and hard budgets"
    ),
    output_contract=(
        "BrowserExplorationDispatch/v1 followed by BrowserExplorationEvidence/v1 "
        "with content-addressed snapshot/screenshot/console/network evidence"
    ),
    requirements=(
        "persisted DeepSeek Harness DEVELOPMENT authorization",
        "exact Global Capability Registry executor binding",
        "fixed Browser MCP Exploration workflow",
        "pinned @playwright/mcp 0.0.82",
        "isolated Chromium context",
        "local synthetic VEdit fixture only",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("DEVELOPMENT",),
    policy_tags=(
        "browser","qa","playwright","mcp","exploration","diagnosis",
        "observation","frontend","ui","read-only","bounded",
    ),
    security_boundary=(
        "DeepSeek Harness sole authority. Fixed Playwright MCP server/version, "
        "loopback-only origin, isolated profile, hard action/tab/screenshot/"
        "navigation/time budgets and client-side tool allowlist. No unsafe code, "
        "browser_evaluate, WebMCP, arbitrary MCP server/endpoint, file URL, "
        "personal credentials/profile, upload/download, external navigation, "
        "repository mutation, golden update, self-approval or publication authority."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="GITHUB_ACTIONS_BOUNDED",
    latency_class="CLOUD_INTERACTIVE",
    quality_class="BOUNDED_MCP_OBSERVATION_EVIDENCE",
    evidence_contract="BrowserExplorationEvidence/v1",
    fallback_eligibility=False,
    executor_binding=(
        "app.services.browser_mcp_exploration_service."
        "execute_browser_mcp_exploration_capability"
    ),
    version="1",
    provider_id="internal",
    agent_id="browser-qa-explorer",
    side_effects=(
        "fixed GitHub Actions exploration workflow dispatch",
        "ephemeral isolated browser context",
        "synthetic local VEdit fixture interactions",
    ),
    authority="NONE",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    supports_parallelism=False,
    supports_retry=False,
    supports_resume=False,
    supports_review=False,
    side_effect_class="READ_ONLY",
    default_read_scope=("video-engine/frontend","artifacts/browser-qa"),
    default_write_scope=(),
    allowed_tools=(
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_hover",
        "browser_type",
        "browser_press_key",
        "browser_resize",
        "browser_take_screenshot",
        "browser_console_messages",
        "browser_network_requests",
        "browser_wait_for",
        "browser_tabs",
        "browser_close",
    ),
    health_policy="BROWSER_RUNTIME_REQUIRED",
    execution_operations=(
        CAN_RUN_TESTS,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    execution_kind="TOOL",
    functional_roles=("QA","OBSERVATION"),
)
if _REGISTRY._by_id.get(BROWSER_QA_EXPLORE_RECORD.capability_id) is not None:
    raise ValueError("Duplicate browser QA explore capability id")
_REGISTRY._by_id[BROWSER_QA_EXPLORE_RECORD.capability_id] = BROWSER_QA_EXPLORE_RECORD
_REGISTRY._records = tuple(
    sorted(
        (*_REGISTRY._records, BROWSER_QA_EXPLORE_RECORD),
        key=lambda item: item.capability_id,
    )
)




from app.services.youtube_intelligence_capability_bridge import (
    youtube_intelligence_capability_records,
)

_YOUTUBE_INTELLIGENCE_CAPABILITY_RECORDS = youtube_intelligence_capability_records()
for _youtube_intel_record in _YOUTUBE_INTELLIGENCE_CAPABILITY_RECORDS:
    if _REGISTRY._by_id.get(_youtube_intel_record.capability_id) is not None:
        raise ValueError(
            "Duplicate YouTube intelligence capability id: "
            + _youtube_intel_record.capability_id
        )
    _REGISTRY._by_id[_youtube_intel_record.capability_id] = _youtube_intel_record

_REGISTRY._records = tuple(
    sorted(
        (*_REGISTRY._records, *_YOUTUBE_INTELLIGENCE_CAPABILITY_RECORDS),
        key=lambda item: item.capability_id,
    )
)

from app.services.agenttube_capability_bridge import agenttube_capability_records

_AGENTTUBE_CAPABILITY_RECORDS = agenttube_capability_records()
for _agenttube_record in _AGENTTUBE_CAPABILITY_RECORDS:
    if _REGISTRY._by_id.get(_agenttube_record.capability_id) is not None:
        raise ValueError(
            "Duplicate AgentTube capability id: "
            + _agenttube_record.capability_id
        )
    _REGISTRY._by_id[_agenttube_record.capability_id] = _agenttube_record

_REGISTRY._records = tuple(
    sorted(
        (*_REGISTRY._records, *_AGENTTUBE_CAPABILITY_RECORDS),
        key=lambda item: item.capability_id,
    )
)

from app.services.voice_capability_bridge import voice_capability_records

_VOICE_CAPABILITY_RECORDS = voice_capability_records()
for _voice_record in _VOICE_CAPABILITY_RECORDS:
    if _REGISTRY._by_id.get(_voice_record.capability_id) is not None:
        raise ValueError(
            "Duplicate Voice Plane capability id: " + _voice_record.capability_id
        )
    _REGISTRY._by_id[_voice_record.capability_id] = _voice_record

_REGISTRY._records = tuple(
    sorted(
        (*_REGISTRY._records, *_VOICE_CAPABILITY_RECORDS),
        key=lambda item: item.capability_id,
    )
)

_existing_narration_voice = _REGISTRY._by_id.get("narration.generate.pt-BR")
if _existing_narration_voice is None:
    raise ValueError("Missing canonical narration.generate.pt-BR capability")
_hardened_narration_voice = replace(
    _existing_narration_voice,
    authority="NONE",
    memory_write="FORBIDDEN",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    policy_tags=tuple(dict.fromkeys((*_existing_narration_voice.policy_tags, "voice-plane", "provider-neutral-candidate-boundary"))),
    security_boundary=(
        _existing_narration_voice.security_boundary
        + " Voice Plane candidates remain subordinate; BR_OWNER_V1 is the sole production identity, "
        + "must bind only to private Telegram owner references, and has no generic or preset-voice fallback."
    ),
)
_REGISTRY._by_id["narration.generate.pt-BR"] = _hardened_narration_voice
_REGISTRY._records = tuple(
    sorted(
        (
            _hardened_narration_voice
            if record.capability_id == "narration.generate.pt-BR"
            else record
            for record in _REGISTRY._records
        ),
        key=lambda item: item.capability_id,
    )
)

GLOBAL_CAPABILITY_REGISTRY = _REGISTRY

PERSISTENT_RESPONSIBILITY_OBSERVE_RECORD = CapabilityRecord(
    capability_id="persistent.responsibility.observe",
    capability_type="EXECUTOR",
    domain="persistent-intelligence",
    implementation=(
        "Harness-governed deterministic bounded observation evaluator for "
        "PersistentResponsibility/v1"
    ),
    input_contract=(
        "persisted Harness RESEARCH authorization + responsibility_id + "
        "matching event/interval observation"
    ),
    output_contract=(
        "PersistentResponsibilityObservationResult/v1 + bounded wake decision"
    ),
    requirements=(
        "persisted DeepSeek Harness RESEARCH authorization",
        "PersistentResponsibility/v1",
        "ProactiveResearchPolicy/v1",
        "PersistentWorkTimeBudget/v1",
    ),
    maturity=FUNCTIONAL,
    availability=AVAILABLE,
    allowed_actions=("RESEARCH",),
    policy_tags=(
        "persistent-intelligence",
        "responsibility",
        "read-only",
        "event-driven",
        "bounded",
        "harness-subordinate",
    ),
    security_boundary=(
        "DeepSeek Harness remains sole reducer and authorization authority; "
        "this executor only evaluates whether bounded read-only observation work exists; "
        "it cannot create side-effect authority, publish, deploy, push, change permissions, "
        "or mutate external systems."
    ),
    cost_class="FREE_NO_BILLING",
    quota_class="LOCAL_DETERMINISTIC",
    latency_class="LOCAL",
    quality_class="DETERMINISTIC_FAIL_CLOSED",
    evidence_contract=(
        "app.services.persistent_intelligence_contracts.ResponsibilityWakeDecision/v1"
    ),
    fallback_eligibility=False,
    executor_binding=(
        "app.services.persistent_intelligence_force_service."
        "execute_persistent_responsibility_observation_capability"
    ),
    version="1",
    provider_id="internal",
    agent_id="persistent-intelligence-observer",
    side_effects=(),
    supports_parallelism=True,
    supports_retry=False,
    supports_resume=True,
    supports_review=False,
    side_effect_class="LOCAL_STATE_ONLY",
    default_read_scope=(),
    default_write_scope=(),
    allowed_tools=(),
    health_policy="DEFAULT",
)

if _REGISTRY._by_id.get(PERSISTENT_RESPONSIBILITY_OBSERVE_RECORD.capability_id) is not None:
    raise ValueError("Duplicate persistent.responsibility.observe Registry record")
_REGISTRY._by_id[PERSISTENT_RESPONSIBILITY_OBSERVE_RECORD.capability_id] = (
    PERSISTENT_RESPONSIBILITY_OBSERVE_RECORD
)
_REGISTRY._records = tuple(
    sorted(
        (*_REGISTRY._records, PERSISTENT_RESPONSIBILITY_OBSERVE_RECORD),
        key=lambda item: item.capability_id,
    )
)


OPENAI_AGENTS_SESSION_RECORD = CapabilityRecord(
    capability_id="openai.agents.session",
    capability_type="EXECUTOR",
    domain="agent-runtime",
    implementation="OpenAI Agents API durable session adapter subordinate to DeepSeek Harness",
    input_contract=(
        "fresh Harness authorization + bounded task/lease + model profile + "
        "environment lease + topology assessment"
    ),
    output_contract="OpenAIAgentSessionReceipt/v1 + typed artifacts + trace refs",
    requirements=(
        "OpenAI API project service account with least-privilege Agents API/model access",
        "api.agents.read",
        "api.agents.write",
        "api.responses.write",
        "workload identity or equivalent short-lived project authentication",
        "live canary proof before routing eligibility",
    ),
    maturity=UNPROVEN,
    availability=UNKNOWN,
    allowed_actions=("EXECUTION",),
    policy_tags=("openai","agents-api","durable-session","harness-subordinate","live-proof-required"),
    security_boundary=(
        "DeepSeek Harness is sole reducer/authority; OpenAI root agent and subagents are "
        "execution workers only. Session completion never equals BR task success. "
        "No secret enters model-visible content or receipts."
    ),
    cost_class="API_METERED_BOUNDED_BY_TASK",
    quota_class="OPENAI_PROJECT_LIMITS",
    latency_class="ASYNC_DURABLE",
    quality_class="LIVE_CANARY_REQUIRED",
    evidence_contract="OpenAIAgentSessionReceipt/v1",
    fallback_eligibility=False,
    executor_binding="app.services.openai_agents_runtime_service.execute_openai_agents_session",
    version="1",
    provider_id="openai",
    model_binding_policy="HARNESS_SELECTED_MODEL_PROFILE",
    agent_id="openai-agents-root",
    side_effects=(),
    authority="NONE",
    memory_write="NONE",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    supports_parallelism=True,
    supports_retry=True,
    supports_resume=True,
    supports_review=False,
    side_effect_class="READ_ONLY",
    default_read_scope=(),
    default_write_scope=(),
    allowed_tools=(),
    health_policy="LIVE_CANARY_REQUIRED",
)

OPENAI_COMPUTER_USE_RECORD = CapabilityRecord(
    capability_id="openai.computer-use",
    capability_type="TOOL",
    domain="computer-use",
    implementation="Bounded OpenAI Agents API computer-use capability",
    input_contract=(
        "fresh Harness task lease + approved AgentEnvironmentLease/v1 + allowed domain/app + "
        "time budget + approval policy"
    ),
    output_contract="screenshot/activity evidence + verified bounded result",
    requirements=(
        "approved environment",
        "allowed domains/apps",
        "fresh task authorization",
        "screenshot/activity evidence",
        "same-session recovery",
    ),
    maturity=UNPROVEN,
    availability=UNKNOWN,
    allowed_actions=("EXECUTION",),
    policy_tags=("openai","computer-use","bounded-external","approval-required"),
    security_boundary=(
        "No unrestricted computer authority. Origin/app/task/time bounds are mandatory; "
        "external content is untrusted and cannot grant permission; consequential actions "
        "remain subject to Harness/human approval."
    ),
    cost_class="API_TOOL_METERED",
    quota_class="OPENAI_PROJECT_LIMITS",
    latency_class="INTERACTIVE",
    quality_class="LIVE_CANARY_REQUIRED",
    evidence_contract="OpenAIComputerUseDecision/v1",
    fallback_eligibility=False,
    executor_binding=None,
    version="1",
    provider_id="openai",
    side_effects=("bounded browser/computer activity",),
    authority="NONE",
    memory_write="NONE",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    supports_parallelism=False,
    supports_retry=False,
    supports_resume=True,
    supports_review=False,
    side_effect_class="BOUNDED_EXTERNAL",
    default_read_scope=(),
    default_write_scope=(),
    allowed_tools=("computer_use",),
    health_policy="LIVE_CANARY_REQUIRED",
)

OPENAI_GPT_6_1_SOL_RECORD = CapabilityRecord(
    capability_id="ai.provider.openai-gpt-6.1-sol",
    capability_type="PROVIDER",
    domain="semantic-reasoning",
    implementation="OpenAI GPT-6.1 Sol via Harness-selected OpenAI runtime",
    input_contract="TaskCognitiveProfile/v1 + CognitiveBudgetPlan/v1 + fresh Harness authorization",
    output_contract="typed provider result bound to task evidence",
    requirements=(
        "OpenAI project model access",
        "live structured reasoning canary",
        "live tool-call canary",
        "live code canary",
        "live artifact-producing canary",
    ),
    maturity=UNPROVEN,
    availability=UNKNOWN,
    allowed_actions=("RESEARCH","DEVELOPMENT","DECISION","REVIEW"),
    policy_tags=("openai","gpt-6.1-sol","semantic-provider","live-proof-required"),
    security_boundary=(
        "No brand-based routing and no global default. Harness hard eligibility, health, "
        "competence, cost, latency and independence requirements decide selection."
    ),
    cost_class="API_METERED",
    quota_class="OPENAI_PROJECT_LIMITS",
    latency_class="MODEL_DEPENDENT",
    quality_class="UNPROVEN_UNTIL_LIVE_CANARY",
    evidence_contract="OpenAIAgentSessionReceipt/v1",
    fallback_eligibility=False,
    executor_binding=None,
    version="1",
    provider_id="openai",
    model_id="gpt-6.1-sol",
    model_binding_policy="HARNESS_COGNITIVE_BUDGET",
    authority="NONE",
    memory_write="NONE",
    routing_authority="NONE",
    editorial_authority="NONE",
    publication_authority="NONE",
    supports_parallelism=True,
    supports_retry=True,
    supports_resume=True,
    supports_review=True,
    side_effect_class="READ_ONLY",
    health_policy="LIVE_CANARY_REQUIRED",
)


for _record in (
    OPENAI_AGENTS_SESSION_RECORD,
    OPENAI_COMPUTER_USE_RECORD,
    OPENAI_GPT_6_1_SOL_RECORD,
):
    if _REGISTRY._by_id.get(_record.capability_id) is not None:
        raise ValueError(f"Duplicate DD2 capability record: {_record.capability_id}")
    _REGISTRY._by_id[_record.capability_id] = _record
_REGISTRY._records = tuple(sorted(
    (*_REGISTRY._records,
     OPENAI_AGENTS_SESSION_RECORD,
     OPENAI_COMPUTER_USE_RECORD,
     OPENAI_GPT_6_1_SOL_RECORD,
     ),
    key=lambda item: item.capability_id,
))


# BR reverse-engineering capabilities are specialist sensors, never a new authority.
# The sole invocation path remains persisted Harness authorization + routing.
REVERSE_ENGINEERING_RECORDS = (
    CapabilityRecord(
        capability_id="reverse-engineering.media.observe",
        capability_type="TOOL",
        domain="audiovisual-analysis",
        implementation="Harness-scoped deterministic audio/video/script forensic measurement",
        input_contract="fresh Harness RESEARCH authorization with allowed_media_roots lineage; absolute authorized media path and declared usage rights",
        output_contract="BRHarnessReverseEngineeringResult/v1 with BRAudiovisualForensics/v2 source hashes and measured metrics",
        requirements=("ffprobe and ffmpeg installed", "local owned/licensed or observation-only source", "persisted authorization and routing", "read-only workspace"),
        maturity=FUNCTIONAL, availability=AVAILABLE,
        allowed_actions=("RESEARCH",),
        policy_tags=("reverse-engineering", "audio", "video", "narrative", "forensics", "deterministic", "evidence", "readonly", "zero-cost"),
        security_boundary="DeepSeek Harness sole authority. Local source must be within persisted root scope. No private owner-voice inputs, no cloud upload, publication, memory writes, synthesis, DRM circumvention, or authority grants.",
        cost_class="FREE_NO_BILLING", quota_class="LOCAL_FFMPEG_CPU",
        latency_class="BOUNDED_ASYNC", quality_class="ACTUAL_MEASUREMENT_ONLY",
        evidence_contract="BRHarnessReverseEngineeringResult/v1",
        fallback_eligibility=False,
        executor_binding="app.services.reverse_engineering_harness_service.execute_authorized_media_observation",
        version="3", provider_id="ffmpeg-local", agent_id="harness-reverse-engineering-specialist",
        authority="NONE", memory_write="NONE", routing_authority="NONE",
        editorial_authority="NONE", publication_authority="NONE",
        supports_parallelism=False, supports_retry=False, supports_resume=False,
        supports_review=False, side_effect_class="READ_ONLY",
        default_read_scope=(), default_write_scope=(),
        allowed_tools=("ffmpeg", "ffprobe"), health_policy="DEFAULT",
        execution_kind="DETERMINISTIC_ANALYSIS_AGENT", functional_roles=("MEDIA_FORENSIC_EVIDENCE",),
    ),
    CapabilityRecord(
        capability_id="reverse-engineering.software.rea-static",
        capability_type="TOOL",
        domain="software-investigation",
        implementation="Harness-scoped REA 6.0.0 static JS application evidence-digest inspection",
        input_contract="fresh Harness RESEARCH authorization, absolute JS directory in allowed_media_roots, owned/licensed or observation-only",
        output_contract="BRHarnessReverseEngineeringResult/v1 with provenance, REA version and sanitized evidence digest",
        requirements=("rea-agents@6.0.0 installed into private BR_REA_INSTALL_PREFIX", "Node 24.11+", "static JS target", "persisted Harness read scope"),
        maturity=FUNCTIONAL, availability=AVAILABLE,
        allowed_actions=("RESEARCH",),
        policy_tags=("reverse-engineering", "rea", "javascript", "software", "static-analysis", "deterministic", "readonly", "zero-cost"),
        security_boundary="DeepSeek Harness sole authority. Static JS only; no debugger, native decompiler, network discovery, process launch, browser, agent registration, secrets, media publication or persistent runtime modification.",
        cost_class="FREE_NO_BILLING", quota_class="LOCAL_NODE_CPU",
        latency_class="BOUNDED_ASYNC", quality_class="STATIC_DIGEST_NOT_ORIGINAL_SOURCE",
        evidence_contract="BRHarnessReverseEngineeringResult/v1",
        fallback_eligibility=False,
        executor_binding="app.services.reverse_engineering_harness_service.execute_authorized_software_observation",
        version="1", provider_id="rea-pinned", agent_id="harness-reverse-engineering-specialist",
        authority="NONE", memory_write="NONE", routing_authority="NONE",
        editorial_authority="NONE", publication_authority="NONE",
        supports_parallelism=False, supports_retry=False, supports_resume=False,
        supports_review=False, side_effect_class="READ_ONLY",
        default_read_scope=(), default_write_scope=(),
        allowed_tools=("rea",), health_policy="DEFAULT",
        execution_kind="DETERMINISTIC_ANALYSIS_AGENT", functional_roles=("SOFTWARE_FORENSIC_EVIDENCE",),
    ),
)
for _reverse_engineering_record in REVERSE_ENGINEERING_RECORDS:
    if _REGISTRY._by_id.get(_reverse_engineering_record.capability_id) is not None:
        raise ValueError("Duplicate reverse-engineering capability")
    _REGISTRY._by_id[_reverse_engineering_record.capability_id] = _reverse_engineering_record
_REGISTRY._records = tuple(sorted(
    (*_REGISTRY._records, *REVERSE_ENGINEERING_RECORDS),
    key=lambda item: item.capability_id,
))


# Offline web behavior evidence extends the existing Harness registry; no browser access.
WEB_REVERSE_ENGINEERING_RECORD = CapabilityRecord(
    capability_id="reverse-engineering.web.har-observe",
    capability_type="TOOL", domain="website-observation",
    implementation="Offline HAR v1.2 request/timing metadata anonymization under Harness authorization",
    input_contract="persisted RESEARCH capability authorization + bounded local authorized HAR 1.2 and declared rights",
    output_contract="BRHarnessReverseEngineeringResult/v1 containing BROfflineWebHARObservation/v1",
    requirements=("local approved HAR", "persisted allowed_media_roots", "no live browser/network"),
    maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("RESEARCH",),
    policy_tags=("reverse-engineering", "web", "website", "har", "privacy", "deterministic", "readonly", "zero-cost"),
    security_boundary="DeepSeek Harness sole authority. No requests, cookies, URLs, origins, payloads or HAR bodies are leaked to agent responses; no live network, browser, publication or memory mutation.",
    cost_class="FREE_NO_BILLING", quota_class="LOCAL_PYTHON_CPU",
    latency_class="LOCAL", quality_class="OFFLINE_MEASURED_HAR_ONLY",
    evidence_contract="BRHarnessReverseEngineeringResult/v1",
    fallback_eligibility=False,
    executor_binding="app.services.reverse_engineering_harness_service.execute_authorized_web_har_observation",
    version="1", provider_id="internal", agent_id="harness-reverse-engineering-specialist",
    authority="NONE", memory_write="NONE", routing_authority="NONE",
    editorial_authority="NONE", publication_authority="NONE",
    supports_parallelism=False, supports_retry=False, supports_resume=False,
    supports_review=False, side_effect_class="READ_ONLY",
    default_read_scope=(), default_write_scope=(),
    allowed_tools=(), health_policy="DEFAULT",
    execution_kind="DETERMINISTIC_ANALYSIS_AGENT",
    functional_roles=("WEBSITE_BEHAVIOR_EVIDENCE",),
)
if _REGISTRY._by_id.get(WEB_REVERSE_ENGINEERING_RECORD.capability_id) is not None:
    raise ValueError("Duplicate reverse-engineering HAR capability")
_REGISTRY._by_id[WEB_REVERSE_ENGINEERING_RECORD.capability_id] = WEB_REVERSE_ENGINEERING_RECORD
_REGISTRY._records = tuple(sorted(
    (*_REGISTRY._records, WEB_REVERSE_ENGINEERING_RECORD),
    key=lambda item: item.capability_id,
))


# Experiment intelligence is a subordinate evidence assessor, not a policy learner.
REVERSE_ENGINEERING_EXPERIMENT_RECORD = CapabilityRecord(
    capability_id="reverse-engineering.experiment.assess",
    capability_type="TOOL", domain="experiment-intelligence",
    implementation="Exact-bound paired development/holdout comparison with sign-test and failure taxonomy",
    input_contract="Harness persisted RESEARCH authorization pinned to dataset digest/domain/task and an exact technique ID allowlist; numeric evidence cases only",
    output_contract="BRHarnessReverseEngineeringResult/v1 + BRTechniqueExperimentAssessment/v1",
    requirements=("pre-registered paired dataset", "complete technique case coverage",
                  "provenance hashes", "pre-registered tolerances and hard cost/safety gates"),
    maturity=FUNCTIONAL, availability=AVAILABLE, allowed_actions=("RESEARCH",),
    policy_tags=("reverse-engineering", "evals", "paired", "heldout", "experiment",
                 "measurement", "statistical", "readonly", "harness-subordinate"),
    security_boundary="Only DeepSeek Harness can issue persisted dataset-scoped authorization. Evaluation makes review proposals only; no routing changes, memory writes, model training, publication, spend, unreviewed policy update or owner voice access.",
    cost_class="FREE_NO_BILLING", quota_class="LOCAL_PYTHON_CPU",
    latency_class="LOCAL", quality_class="EVIDENCE_PROPOSAL_NOT_INDEPENDENT_ATTESTATION",
    evidence_contract="BRHarnessReverseEngineeringResult/v1",
    fallback_eligibility=False,
    executor_binding="app.services.reverse_engineering_harness_service.execute_authorized_experiment_assessment",
    version="1", provider_id="internal", agent_id="harness-reverse-engineering-specialist",
    authority="NONE", memory_write="NONE", routing_authority="NONE",
    editorial_authority="NONE", publication_authority="NONE",
    supports_parallelism=False, supports_retry=False, supports_resume=False,
    supports_review=False, side_effect_class="READ_ONLY",
    default_read_scope=(), default_write_scope=(), allowed_tools=(),
    health_policy="DEFAULT", execution_kind="VALIDATOR",
    functional_roles=("EXPERIMENT_ASSESSMENT_EVIDENCE",),
)
if _REGISTRY._by_id.get(REVERSE_ENGINEERING_EXPERIMENT_RECORD.capability_id) is not None:
    raise ValueError("Duplicate experiment-intelligence capability")
_REGISTRY._by_id[REVERSE_ENGINEERING_EXPERIMENT_RECORD.capability_id] = REVERSE_ENGINEERING_EXPERIMENT_RECORD
_REGISTRY._records = tuple(sorted(
    (*_REGISTRY._records, REVERSE_ENGINEERING_EXPERIMENT_RECORD),
    key=lambda item: item.capability_id,
))
