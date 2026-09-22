from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


AVAILABLE = "AVAILABLE"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN/UNPROVEN"

PROVEN = "PROVEN"
FUNCTIONAL = "FUNCTIONAL"
PARTIAL = "PARTIAL"
UNPROVEN = "UNKNOWN/UNPROVEN"

CAPABILITY_TYPES = {"CAPABILITY", "AGENT", "SKILL", "PRESENTATION", "PROVIDER", "EXECUTOR", "TOOL"}
AVAILABILITY_STATES = {AVAILABLE, BLOCKED, UNKNOWN}
MATURITY_STATES = {PROVEN, FUNCTIONAL, PARTIAL, UNPROVEN}


@dataclass(frozen=True)
class CapabilityRecord:
    capability_id: str
    capability_type: str
    domain: str
    implementation: str
    input_contract: str
    output_contract: str
    requirements: tuple[str, ...]
    maturity: str
    availability: str
    allowed_actions: tuple[str, ...]
    policy_tags: tuple[str, ...]
    security_boundary: str
    cost_class: str
    quota_class: str
    latency_class: str
    quality_class: str
    evidence_contract: str | None
    fallback_eligibility: bool
    executor_binding: str | None
    version: str
    provider_id: str | None = None
    model_id: str | None = None
    model_binding_policy: str = "STATIC_REGISTRY"
    agent_id: str | None = None
    skill_id: str | None = None
    side_effects: tuple[str, ...] = ()
    instruction_path: str | None = None
    authority: str = "INHERITED"
    memory_write: str = "INHERITED"
    routing_authority: str = "INHERITED"
    editorial_authority: str = "INHERITED"
    publication_authority: str = "INHERITED"
    supports_parallelism: bool = True
    supports_retry: bool = True
    supports_resume: bool = False
    supports_review: bool = False
    side_effect_class: str = "READ_ONLY"
    default_read_scope: tuple[str, ...] = ()
    default_write_scope: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    health_policy: str = "DEFAULT"

    @property
    def provider(self) -> str:
        if self.executor_binding and "codex_addy_capability_executor" in self.executor_binding:
            return "addy-agent-skills"
        return self.provider_id or self.agent_id or "native"

    @property
    def execution_kind(self) -> str:
        if self.executor_binding and "codex_addy_capability_executor" in self.executor_binding:
            return "codex_native_skill"
        if self.provider_id == "higgsfield":
            return "higgsfield_cli"
        return "registered_executor"

    @property
    def tags(self) -> tuple[str, ...]:
        return self.policy_tags

    @property
    def boundary(self) -> str:
        return self.security_boundary

    @property
    def available(self) -> bool:
        return self.availability == AVAILABLE

    @property
    def execution_enabled(self) -> bool:
        return self.available and self.executor_binding is not None

    @property
    def status(self) -> str:
        if self.availability == BLOCKED:
            return BLOCKED
        if self.availability == UNKNOWN:
            return UNKNOWN
        return self.maturity

    def metadata(self) -> dict[str, object]:
        data = asdict(self)
        data["available"] = self.available
        data["execution_enabled"] = self.execution_enabled
        data["status"] = self.status
        return data


class GlobalCapabilityRegistry:
    """Deterministic metadata registry. It never authorizes or executes."""

    def __init__(self, records: Iterable[CapabilityRecord]):
        by_id: dict[str, CapabilityRecord] = {}
        for record in records:
            if record.capability_type not in CAPABILITY_TYPES:
                raise ValueError(
                    f"Invalid capability_type for {record.capability_id}: "
                    f"{record.capability_type}"
                )
            if record.availability not in AVAILABILITY_STATES:
                raise ValueError(
                    f"Invalid availability for {record.capability_id}: "
                    f"{record.availability}"
                )
            if record.maturity not in MATURITY_STATES:
                raise ValueError(
                    f"Invalid maturity for {record.capability_id}: "
                    f"{record.maturity}"
                )
            if record.capability_id in by_id:
                raise ValueError(
                    f"Duplicate capability_id: {record.capability_id}"
                )
            if record.available and record.executor_binding is None:
                raise ValueError(
                    "AVAILABLE capability requires executor_binding: "
                    f"{record.capability_id}"
                )
            if record.execution_enabled and not record.evidence_contract:
                raise ValueError(
                    "Executable capability requires evidence_contract: "
                    f"{record.capability_id}"
                )
            by_id[record.capability_id] = record
        self._by_id = by_id
        self._records = tuple(
            sorted(by_id.values(), key=lambda item: item.capability_id)
        )

    def get(self, capability_id: str) -> CapabilityRecord | None:
        return self._by_id.get(capability_id)

    def all(self) -> tuple[CapabilityRecord, ...]:
        return self._records

    def discover(
        self,
        *,
        intent: str,
        authorized_action: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        if limit < 1:
            raise ValueError("limit must be positive")

        terms = tuple(
            term
            for term in intent.lower().replace("_", "-").split()
            if term
        )
        if not terms:
            return []

        ranked: list[tuple[int, str, CapabilityRecord]] = []
        for record in self._records:
            if not record.available:
                continue
            if (
                authorized_action
                and authorized_action not in record.allowed_actions
            ):
                continue

            values = (
                record.capability_id.lower(),
                record.capability_type.lower(),
                record.domain.lower(),
                record.implementation.lower(),
                record.provider_id.lower() if record.provider_id else "",
                record.agent_id.lower() if record.agent_id else "",
                record.skill_id.lower() if record.skill_id else "",
                *(tag.lower() for tag in record.policy_tags),
            )
            score = sum(
                1
                for term in terms
                if any(term in value for value in values)
            )
            if score:
                ranked.append((-score, record.capability_id, record))

        ranked.sort(key=lambda item: (item[0], item[1]))
        return [
            record.metadata()
            for _, _, record in ranked[:limit]
        ]


ADDY_SKILLS = (
    "api-and-interface-design",
    "ci-cd-and-automation",
    "code-review-and-quality",
    "code-simplification",
    "constraint-driven-development",
    "context-engineering",
    "debugging-and-error-recovery",
    "deprecation-and-migration",
    "documentation-and-adrs",
    "doubt-driven-development",
    "frontend-ui-engineering",
    "git-workflow-and-versioning",
    "idea-refine",
    "incremental-implementation",
    "interview-me",
    "observability-and-instrumentation",
    "performance-optimization",
    "planning-and-task-breakdown",
    "security-and-hardening",
    "shipping-and-launch",
    "source-driven-development",
    "spec-driven-development",
    "test-driven-development",
    "using-agent-skills",
)


HIGGSFIELD_AUTH_BOUNDARY = (
    "interactive_browser_only_confirmed; unattended ephemeral-runner auth "
    "not officially confirmed"
)


def _record(
    *,
    capability_id: str,
    capability_type: str,
    domain: str,
    implementation: str,
    input_contract: str,
    output_contract: str,
    requirements: tuple[str, ...],
    maturity: str,
    availability: str,
    allowed_actions: tuple[str, ...],
    policy_tags: tuple[str, ...],
    security_boundary: str,
    executor_binding: str | None,
    evidence_contract: str | None,
    provider_id: str | None = None,
    model_id: str | None = None,
    model_binding_policy: str = "STATIC_REGISTRY",
    agent_id: str | None = None,
    skill_id: str | None = None,
    side_effects: tuple[str, ...] = (),
    instruction_path: str | None = None,
    cost_class: str = "UNKNOWN",
    quota_class: str = "UNKNOWN",
    latency_class: str = "UNKNOWN",
    quality_class: str = "UNKNOWN",
    fallback_eligibility: bool = False,
    version: str = "1",
    supports_parallelism: bool = True,
    supports_retry: bool = True,
    supports_resume: bool = False,
    supports_review: bool = False,
    side_effect_class: str = "READ_ONLY",
    default_read_scope: tuple[str, ...] = (),
    default_write_scope: tuple[str, ...] = (),
    allowed_tools: tuple[str, ...] = (),
    health_policy: str = "DEFAULT",
) -> CapabilityRecord:
    return CapabilityRecord(
        capability_id=capability_id,
        capability_type=capability_type,
        domain=domain,
        implementation=implementation,
        input_contract=input_contract,
        output_contract=output_contract,
        requirements=requirements,
        maturity=maturity,
        availability=availability,
        allowed_actions=allowed_actions,
        policy_tags=policy_tags,
        security_boundary=security_boundary,
        cost_class=cost_class,
        quota_class=quota_class,
        latency_class=latency_class,
        quality_class=quality_class,
        evidence_contract=evidence_contract,
        fallback_eligibility=fallback_eligibility,
        executor_binding=executor_binding,
        version=version,
        provider_id=provider_id,
        model_id=model_id,
        model_binding_policy=model_binding_policy,
        agent_id=agent_id,
        skill_id=skill_id,
        side_effects=side_effects,
        instruction_path=instruction_path,
        supports_parallelism=supports_parallelism,
        supports_retry=supports_retry,
        supports_resume=supports_resume,
        supports_review=supports_review,
        side_effect_class=side_effect_class,
        default_read_scope=default_read_scope,
        default_write_scope=default_write_scope,
        allowed_tools=allowed_tools,
        health_policy=health_policy,
    )


def _addy_records() -> tuple[CapabilityRecord, ...]:
    return tuple(
        _record(
            capability_id=f"addy:{name}",
            capability_type="SKILL",
            domain="development",
            implementation=(
                "Pinned Addy Agent Skill executed through the DeepSeek Harness "
                "semantic-provider boundary"
            ),
            input_contract="bounded development task + optional JSON context + evidence refs",
            output_contract="bounded semantic skill result + provider evidence + live receipt",
            requirements=(
                "pinned Addy source checkout",
                "materialized compatibility skill view",
                "Harness-authorized ai.reasoning.text provider",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("DEVELOPMENT",),
            policy_tags=("development", "semantic-skill", *tuple(name.split("-"))),
            security_boundary=(
                "HarnessAuthorization + exact pinned Addy skill identity + "
                "Harness-selected zero-cost semantic provider; no autonomous routing, "
                "repository mutation, deployment, publication, or silent fallback"
            ),
            executor_binding=(
                "app.services.addy_harness_service."
                "execute_authorized_addy_skill"
            ),
            evidence_contract=(
                "CapabilityEvidence + AgentInvocationReceipt + HarnessAIProviderEvidence"
            ),
            provider_id=None,
            agent_id="addy-agent-skills",
            skill_id=name,
            instruction_path=f"tooling/agent-skills/skills/{name}/SKILL.md",
            cost_class="FREE_NO_BILLING",
            quota_class="HARNESS_PROVIDER_POLICY",
            latency_class="EXTERNAL_EPHEMERAL",
            quality_class="SKILL_AND_PROVIDER_DEPENDENT",
            health_policy="OPENCODE_REQUIRED",
        )
        for name in ADDY_SKILLS
    )


def _higgsfield_records() -> tuple[CapabilityRecord, ...]:
    specs = (
        (
            "higgsfield-generate",
            ("EXECUTION",),
            ("visual", "image", "video", "generation"),
        ),
        (
            "higgsfield-youtube-thumbnail",
            ("YOUTUBE",),
            ("youtube", "thumbnail", "image"),
        ),
        (
            "higgsfield-brandkit",
            ("EDITORIAL", "EXECUTION"),
            ("brand", "creative", "design"),
        ),
        (
            "higgsfield-video-explainer",
            ("EXECUTION",),
            ("video", "explainer", "creative"),
        ),
    )
    return tuple(
        _record(
            capability_id=capability_id,
            capability_type="PROVIDER",
            domain="visual-generation",
            implementation="Higgsfield CLI capability",
            input_contract="selected Higgsfield capability payload",
            output_contract="Higgsfield generation result",
            requirements=("Higgsfield CLI", "unattended authentication"),
            maturity=PARTIAL,
            availability=BLOCKED,
            allowed_actions=actions,
            policy_tags=tags,
            security_boundary=HIGGSFIELD_AUTH_BOUNDARY,
            executor_binding=None,
            evidence_contract=(
                "app.services.harness_capability_service.CapabilityEvidence"
            ),
            provider_id="higgsfield",
            side_effects=("external generation",),
            cost_class="EXTERNAL_GENERATION",
            quota_class="HIGGSFIELD_ACCOUNT",
            latency_class="EXTERNAL",
            quality_class="UNPROVEN_IN_RUNNER",
        )
        for capability_id, actions, tags in specs
    )


def _native_records() -> tuple[CapabilityRecord, ...]:
    return (
        _record(capability_id="video.generate.image-to-video",capability_type="CAPABILITY",domain="video",implementation="Harness-governed HunyuanVideo-I2V generated video asset",input_contract="IMAGE reference + TEXT prompt -> VIDEO asset",output_contract="validated generated video artifact + GenerativeMediaEvidence",requirements=("isolated Linux/NVIDIA GPU runtime","Tencent-Hunyuan/HunyuanVideo-I2V@c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949","pinned Hugging Face model snapshot revision required before execution","ffprobe"),maturity=UNPROVEN,availability=UNKNOWN,allowed_actions=("EXECUTION",),policy_tags=("generative-media","image-to-video","image","text","video","runtime-unavailable"),security_boundary="DeepSeek Harness authorization + exact routed provider/model/executor; external isolated GPU runtime; generated asset only; no publish/schedule",executor_binding="app.services.generative_media_service.execute_hunyuan_video_i2v",evidence_contract="app.services.generative_media_service.GenerativeMediaEvidence",side_effects=("generated video asset",),cost_class="GPU_HEAVY",quota_class="EXTERNAL_GPU_RUNTIME",latency_class="OFFLINE_GENERATION",quality_class="UNPROVEN",fallback_eligibility=False,version="c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949"),
        _record(capability_id="provider.hunyuanvideo-i2v",capability_type="PROVIDER",domain="video",implementation="Isolated HunyuanVideo-I2V runtime",input_contract="routed image-to-video generation request",output_contract="generated video asset",requirements=("runtime unavailable until GPU executor and model snapshot are proven",),maturity=UNPROVEN,availability=UNKNOWN,allowed_actions=("EXECUTION",),policy_tags=("generative-media","hunyuanvideo-i2v","video","runtime-unavailable"),security_boundary="Harness-selected concrete model snapshot and executor only; no autonomous model/provider fallback",executor_binding="app.services.generative_media_service.execute_hunyuan_video_i2v",evidence_contract="app.services.generative_media_service.GenerativeMediaEvidence",provider_id="hunyuanvideo_i2v",model_id=None,side_effects=("generated video asset",),cost_class="GPU_HEAVY",quota_class="EXTERNAL_GPU_RUNTIME",latency_class="OFFLINE_GENERATION",quality_class="UNPROVEN",fallback_eligibility=False,version="c8bba70b9517f08d770a9a2a3d1e93cc6d5b7949"),
        _record(capability_id="audio.generate.music",capability_type="CAPABILITY",domain="audio",implementation="Harness-governed ACE-Step 1.5 generated music asset",input_contract="TEXT / LYRICS -> AUDIO asset; reference audio optional only when routed",output_contract="validated generated audio artifact + GenerativeMediaEvidence",requirements=("isolated ACE-Step 1.5 runtime","ace-step/ACE-Step-1.5@v0.1.8","code revision dce621408bee8c31b4fcf4811682eb9359e1bc94","pinned Hugging Face model snapshot revision required before execution","ffprobe"),maturity=UNPROVEN,availability=UNKNOWN,allowed_actions=("EXECUTION",),policy_tags=("generative-media","text-to-music","lyrics","audio","music","runtime-unavailable"),security_boundary="DeepSeek Harness authorization + exact routed provider/model/executor; external isolated runtime; generated asset only; no publish/schedule",executor_binding="app.services.generative_media_service.execute_ace_step_music",evidence_contract="app.services.generative_media_service.GenerativeMediaEvidence",side_effects=("generated audio asset",),cost_class="GPU_EXTERNAL",quota_class="EXTERNAL_GPU_RUNTIME",latency_class="OFFLINE_GENERATION",quality_class="UNPROVEN",fallback_eligibility=False,version="dce621408bee8c31b4fcf4811682eb9359e1bc94"),
        _record(capability_id="provider.ace-step",capability_type="PROVIDER",domain="audio",implementation="Isolated ACE-Step 1.5 runtime",input_contract="routed text/lyrics-to-music generation request",output_contract="generated audio asset",requirements=("runtime unavailable until isolated executor and model snapshot are proven",),maturity=UNPROVEN,availability=UNKNOWN,allowed_actions=("EXECUTION",),policy_tags=("generative-media","ace-step","audio","music","runtime-unavailable"),security_boundary="Harness-selected concrete model snapshot and executor only; no autonomous model/provider fallback",executor_binding="app.services.generative_media_service.execute_ace_step_music",evidence_contract="app.services.generative_media_service.GenerativeMediaEvidence",provider_id="ace_step",model_id=None,side_effects=("generated audio asset",),cost_class="GPU_EXTERNAL",quota_class="EXTERNAL_GPU_RUNTIME",latency_class="OFFLINE_GENERATION",quality_class="UNPROVEN",fallback_eligibility=False,version="dce621408bee8c31b4fcf4811682eb9359e1bc94"),
        _record(
            capability_id="ai.provider.gateway",
            capability_type="CAPABILITY",
            domain="ai",
            implementation="Harness AI provider policy/selection boundary",
            input_contract="provider name + prompt + HarnessAuthorization",
            output_contract="HarnessAIProviderEvidence",
            requirements=("persisted HarnessAuthorization", "allowed provider"),
            maturity=PROVEN,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION"),
            policy_tags=("ai", "provider", "gateway", "policy"),
            security_boundary=(
                "Harness provider subject/action binding; selector cannot escape policy"
            ),
            executor_binding=(
                "app.services.harness_ai_provider_service.execute_harness_ai_generation"
            ),
            evidence_contract=(
                "app.services.harness_ai_provider_service.HarnessAIProviderEvidence"
            ),
            cost_class="PROVIDER_DEPENDENT",
            quota_class="PROVIDER_DEPENDENT",
            latency_class="PROVIDER_DEPENDENT",
            quality_class="PROVIDER_DEPENDENT",
        ),
        _record(
            capability_id="ai.reasoning.text",
            capability_type="CAPABILITY",
            domain="ai",
            implementation="Harness-governed AI provider gateway",
            input_contract="prompt text",
            output_contract="normalized AI response",
            requirements=("Harness provider policy", "provider prerequisites"),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION", "YOUTUBE"),
            policy_tags=("ai", "reasoning", "text", "provider-gateway"),
            security_boundary=(
                "Provider/model execution remains behind Harness authorization "
                "and provider policy"
            ),
            executor_binding=(
                "app.services.harness_ai_provider_service.execute_harness_ai_generation"
            ),
            evidence_contract=(
                "app.services.harness_ai_provider_service.HarnessAIProviderEvidence"
            ),
            cost_class="PROVIDER_DEPENDENT",
            quota_class="PROVIDER_DEPENDENT",
            latency_class="PROVIDER_DEPENDENT",
            quality_class="PROVIDER_DEPENDENT",
        ),
        _record(
            capability_id="ai.provider.tuxevil",
            capability_type="PROVIDER",
            domain="ai",
            implementation="TuxevilAIProvider via official AI provider factory",
            input_contract="prompt text",
            output_contract="AIResponse",
            requirements=(
                "Tuxevil Rotator",
                "Antigravity ACCOUNT_AUTH runtime evidence",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION"),
            policy_tags=(
                "ai", "provider", "tuxevil", "text",
                "model-capability:reasoning",
                "model-capability:semantic_planning",
                "model-capability:structured_output",
                "model-capability:tool_use",
            ),
            security_boundary="Official BR AI provider factory boundary",
            executor_binding="app.services.ai_provider_factory.create_ai_provider",
            evidence_contract="app.services.ai_provider.AIResponse",
            provider_id="tuxevil",
            model_binding_policy="CURRENT_RUN_RUNTIME_PROOF",
            cost_class="EXTERNAL_MODEL",
            quota_class="ROTATOR_MANAGED",
            latency_class="EXTERNAL",
            quality_class="PROVIDER_DEPENDENT",
        ),
        _record(
            capability_id="ai.provider.ollama-local-qwen3-4b",
            capability_type="PROVIDER",
            domain="ai",
            implementation=(
                "Ollama 0.34.2 loopback-only local inference with "
                "qwen3:4b-instruct exact proven model digest"
            ),
            input_contract="Harness-selected prompt + exact local model identity",
            output_contract="HarnessAIProviderEvidence",
            requirements=(
                "standard public GitHub Actions runner",
                "Ollama 0.34.2",
                "qwen3:4b-instruct@0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0",
                "loopback-only runtime",
                "ZERO_COST_OPERATION",
                "no external provider credentials",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=(
                "RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT",
                "DECISION", "YOUTUBE",
            ),
            policy_tags=(
                "ai", "provider", "ollama", "local", "open-weight",
                "qwen3", "zero-cost", "no-external-billing",
                "model-capability:reasoning",
                "model-capability:semantic_planning",
                "model-capability:structured_output",
            ),
            security_boundary=(
                "DeepSeek Harness exact provider/model authorization; local Ollama "
                "must bind loopback only; qwen3:4b-instruct digest is pinned; no "
                "external provider credential or autonomous fallback is permitted."
            ),
            executor_binding=(
                "app.services.local_openweight_ai_provider.OllamaLocalAIProvider"
            ),
            evidence_contract=(
                "app.services.harness_ai_provider_service.HarnessAIProviderEvidence"
            ),
            provider_id="ollama_local",
            model_id="qwen3:4b-instruct",
            side_effects=("local model load",),
            cost_class="FREE_NO_BILLING",
            quota_class="PUBLIC_STANDARD_GITHUB_ACTIONS_LOCAL_RUNTIME",
            latency_class="LOCAL_CPU",
            quality_class="QWEN3_4B_INSTRUCT_PROVEN_RUNTIME",
            fallback_eligibility=False,
            version="ollama-0.34.2-qwen3-4b-instruct-0edcdef34593",
        ),
        _record(
            capability_id="ai.provider.opencode-free",
            capability_type="PROVIDER",
            domain="ai",
            implementation=(
                "Harness-governed versioned OpenCode executor profile; "
                "v1 records the disproven OmniRoute HTTP path and v2 resolves "
                "the official OpenCode CLI only after governed promotion"
            ),
            input_contract="explicit Harness-selected prompt/provider/model + active executable profile",
            output_contract="HarnessAIProviderEvidence with executor-profile lineage",
            requirements=(
                "persisted HarnessAuthorization",
                "explicit provider/model identity",
                "active Learning Plane executor profile",
                "ZERO_COST_OPERATION",
                "no silent fallback",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION", "YOUTUBE"),
            policy_tags=(
                "ai", "provider", "opencode", "free", "zero-cost",
                "learning", "versioned-executor", "no-fallback",
            ),
            security_boundary=(
                "DeepSeek Harness selects provider/model and the promoted Learning Plane "
                "profile resolves the executable binding; v1 fails closed from observed "
                "HTTP 403 evidence and v2 may execute only after governed promotion."
            ),
            executor_binding=(
                "app.services.opencode_executor_profile_service."
                "create_opencode_provider_for_active_profile"
            ),
            evidence_contract=(
                "app.services.harness_ai_provider_service.HarnessAIProviderEvidence"
            ),
            provider_id="opencode",
            model_id="oc/big-pickle",
            cost_class="FREE_NO_BILLING",
            quota_class="PUBLIC_NO_AUTH_UPSTREAM_POLICY",
            latency_class="EXTERNAL_EPHEMERAL",
            quality_class="LEARNING_GOVERNED",
            fallback_eligibility=False,
            version="learning-profile-v1",
        ),
        _record(
            capability_id="executor.omniroute-gateway",
            capability_type="EXECUTOR",
            domain="ai",
            implementation="OmniRoute 3.8.50 bounded gateway on standard GitHub Actions runner",
            input_contract="Harness-selected provider/model + persisted HarnessAuthorization",
            output_contract="OmniRouteGatewayEvidence",
            requirements=("public repository", "standard ubuntu-latest runner", "OmniRoute 3.8.50"),
            maturity=UNPROVEN,
            availability=UNKNOWN,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION"),
            policy_tags=("executor", "gateway", "omniroute", "zero-cost", "ephemeral"),
            security_boundary="Subordinate executor only; dedicated provider route; no autonomous fallback, scheduler, DB, publish, or authority",
            executor_binding="app.services.omniroute_gateway_service.execute_omniroute_gateway",
            evidence_contract="app.services.omniroute_gateway_service.OmniRouteGatewayEvidence",
            cost_class="FREE_NO_BILLING",
            quota_class="PUBLIC_STANDARD_GITHUB_ACTIONS",
            latency_class="EPHEMERAL",
            quality_class="UNPROVEN",
            fallback_eligibility=False,
            version="3.8.50",
        ),
        _record(
            capability_id="ai.provider.nvidia-nim.glm-5-3",
            capability_type="PROVIDER",
            domain="ai",
            implementation=(
                "Generic NvidiaNimProviderAdapter; DeepSeek Harness supplies "
                "the selected Registry model_id dynamically"
            ),
            input_contract="Harness-selected prompt + Registry-selected NVIDIA model_id",
            output_contract="HarnessAIProviderEvidence",
            requirements=(
                "NVIDIA_API_KEY",
                "https://integrate.api.nvidia.com/v1",
                "billing-mode:NVIDIA_FREE_ENDPOINT",
                "paid-api-billing:NO",
                "rate-limit-or-quota:POSSIBLE",
                "unlimited:UNPROVEN",
                "context-window:1048576",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION"),
            policy_tags=(
                "ai", "provider", "nvidia", "nim", "multi-model",
                "model-capability:reasoning",
                "model-capability:planning",
                "model-capability:semantic_planning",
                "model-capability:tool_use",
                "model-capability:long_context",
                "model-capability:structured_output",
            ),
            security_boundary=(
                "DeepSeek Harness is sole routing/policy/authorization authority; "
                "one generic NVIDIA adapter receives only the Harness-selected model; "
                "no model self-selection, secret persistence, paid fallback or parallel router."
            ),
            executor_binding=(
                "app.services.harness_ai_provider_service.execute_harness_ai_generation"
            ),
            evidence_contract=(
                "app.services.harness_ai_provider_service.HarnessAIProviderEvidence"
            ),
            provider_id="nvidia_nim",
            model_id="z-ai/glm-5.3",
            cost_class="FREE_ENDPOINT",
            quota_class="NVIDIA_FREE_ENDPOINT_RATE_LIMIT_OR_QUOTA_POSSIBLE",
            latency_class="EXTERNAL_MODEL_DEPENDENT",
            quality_class="FRONTIER_REASONING_AGENTIC",
            fallback_eligibility=False,
            supports_review=True,
            health_policy="PROVIDER_AND_MODEL_RUNTIME_HEALTH",
        ),
        _record(
            capability_id="ai.provider.nvidia-nim.kimi-k3",
            capability_type="PROVIDER",
            domain="ai",
            implementation=(
                "Generic NvidiaNimProviderAdapter; DeepSeek Harness supplies "
                "the selected Registry model_id dynamically"
            ),
            input_contract="Harness-selected prompt + Registry-selected NVIDIA model_id",
            output_contract="HarnessAIProviderEvidence",
            requirements=(
                "NVIDIA_API_KEY",
                "https://integrate.api.nvidia.com/v1",
                "billing-mode:NVIDIA_FREE_ENDPOINT",
                "paid-api-billing:NO",
                "rate-limit-or-quota:POSSIBLE",
                "unlimited:UNPROVEN",
                "context-window:1048576",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION"),
            policy_tags=(
                "ai", "provider", "nvidia", "nim", "multi-model",
                "model-capability:reasoning",
                "model-capability:coding",
                "model-capability:semantic_planning",
                "model-capability:agentic_tool_use",
                "model-capability:tool_use",
                "model-capability:long_horizon",
                "model-capability:multimodal",
                "model-capability:long_context",
                "model-capability:structured_output",
            ),
            security_boundary=(
                "DeepSeek Harness is sole routing/policy/authorization authority; "
                "one generic NVIDIA adapter receives only the Harness-selected model; "
                "no model self-selection, secret persistence, paid fallback or parallel router."
            ),
            executor_binding=(
                "app.services.harness_ai_provider_service.execute_harness_ai_generation"
            ),
            evidence_contract=(
                "app.services.harness_ai_provider_service.HarnessAIProviderEvidence"
            ),
            provider_id="nvidia_nim",
            model_id="moonshotai/kimi-k3",
            cost_class="FREE_ENDPOINT",
            quota_class="NVIDIA_FREE_ENDPOINT_RATE_LIMIT_OR_QUOTA_POSSIBLE",
            latency_class="EXTERNAL_MODEL_DEPENDENT",
            quality_class="FRONTIER_MULTIMODAL_AGENTIC",
            fallback_eligibility=False,
            supports_review=True,
            health_policy="PROVIDER_AND_MODEL_RUNTIME_HEALTH",
        ),
        _record(
            capability_id="ai.provider.nvidia-nim.nemotron-3-ultra",
            capability_type="PROVIDER",
            domain="ai",
            implementation=(
                "Generic NvidiaNimProviderAdapter; DeepSeek Harness supplies "
                "the selected Registry model_id dynamically"
            ),
            input_contract="Harness-selected prompt + Registry-selected NVIDIA model_id",
            output_contract="HarnessAIProviderEvidence",
            requirements=(
                "NVIDIA_API_KEY",
                "https://integrate.api.nvidia.com/v1",
                "billing-mode:NVIDIA_FREE_ENDPOINT",
                "paid-api-billing:NO",
                "rate-limit-or-quota:POSSIBLE",
                "unlimited:UNPROVEN",
                "context-window:1048576",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION"),
            policy_tags=(
                "ai", "provider", "nvidia", "nim", "multi-model",
                "model-capability:reasoning",
                "model-capability:coding",
                "model-capability:planning",
                "model-capability:semantic_planning",
                "model-capability:tool_use",
                "model-capability:long_context",
                "model-capability:structured_output",
            ),
            security_boundary=(
                "DeepSeek Harness is sole routing/policy/authorization authority; "
                "one generic NVIDIA adapter receives only the Harness-selected model; "
                "no model self-selection, secret persistence, paid fallback or parallel router."
            ),
            executor_binding=(
                "app.services.harness_ai_provider_service.execute_harness_ai_generation"
            ),
            evidence_contract=(
                "app.services.harness_ai_provider_service.HarnessAIProviderEvidence"
            ),
            provider_id="nvidia_nim",
            model_id="nvidia/nemotron-3-ultra-550b-a55b",
            cost_class="FREE_ENDPOINT",
            quota_class="NVIDIA_FREE_ENDPOINT_RATE_LIMIT_OR_QUOTA_POSSIBLE",
            latency_class="EXTERNAL_MODEL_DEPENDENT",
            quality_class="FRONTIER_REASONING_AGENTIC",
            fallback_eligibility=False,
            supports_review=True,
            health_policy="PROVIDER_AND_MODEL_RUNTIME_HEALTH",
        ),
        _record(
            capability_id="ai.provider.nvidia-nim.laguna-xs-2-1",
            capability_type="PROVIDER",
            domain="ai",
            implementation=(
                "Generic NvidiaNimProviderAdapter; DeepSeek Harness supplies "
                "the selected Registry model_id dynamically"
            ),
            input_contract="Harness-selected prompt + Registry-selected NVIDIA model_id",
            output_contract="HarnessAIProviderEvidence",
            requirements=(
                "NVIDIA_API_KEY",
                "https://integrate.api.nvidia.com/v1",
                "billing-mode:NVIDIA_FREE_ENDPOINT",
                "paid-api-billing:NO",
                "rate-limit-or-quota:POSSIBLE",
                "unlimited:UNPROVEN",
                "context-window:262144",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION"),
            policy_tags=(
                "ai", "provider", "nvidia", "nim", "multi-model",
                "model-capability:coding",
                "model-capability:terminal",
                "model-capability:agentic_coding",
                "model-capability:agentic_tool_use",
                "model-capability:tool_use",
            ),
            security_boundary=(
                "DeepSeek Harness is sole routing/policy/authorization authority; "
                "one generic NVIDIA adapter receives only the Harness-selected model; "
                "no model self-selection, secret persistence, paid fallback or parallel router."
            ),
            executor_binding=(
                "app.services.harness_ai_provider_service.execute_harness_ai_generation"
            ),
            evidence_contract=(
                "app.services.harness_ai_provider_service.HarnessAIProviderEvidence"
            ),
            provider_id="nvidia_nim",
            model_id="poolside/laguna-xs-2.1",
            cost_class="FREE_ENDPOINT",
            quota_class="NVIDIA_FREE_ENDPOINT_RATE_LIMIT_OR_QUOTA_POSSIBLE",
            latency_class="EXTERNAL_MODEL_DEPENDENT",
            quality_class="AGENTIC_CODING_SPECIALIST",
            fallback_eligibility=False,
            supports_review=True,
            health_policy="PROVIDER_AND_MODEL_RUNTIME_HEALTH",
        ),
        _record(
            capability_id="ai.provider.nvidia-nim.nemotron-3-5-lightning",
            capability_type="PROVIDER",
            domain="ai",
            implementation=(
                "Generic NvidiaNimProviderAdapter; DeepSeek Harness supplies "
                "the selected Registry model_id dynamically"
            ),
            input_contract="Harness-selected prompt + Registry-selected NVIDIA model_id",
            output_contract="HarnessAIProviderEvidence",
            requirements=(
                "NVIDIA_API_KEY",
                "https://integrate.api.nvidia.com/v1",
                "billing-mode:NVIDIA_FREE_ENDPOINT",
                "paid-api-billing:NO",
                "rate-limit-or-quota:POSSIBLE",
                "unlimited:UNPROVEN",
                "context-window:1048576",
            ),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL", "EXECUTION", "DEVELOPMENT", "DECISION"),
            policy_tags=(
                "ai", "provider", "nvidia", "nim", "multi-model",
                "model-capability:fast_reasoning",
                "model-capability:reasoning",
                "model-capability:semantic_planning",
                "model-capability:agentic_tasks",
                "model-capability:tool_use",
                "model-capability:long_context",
                "model-capability:structured_output",
            ),
            security_boundary=(
                "DeepSeek Harness is sole routing/policy/authorization authority; "
                "one generic NVIDIA adapter receives only the Harness-selected model; "
                "no model self-selection, secret persistence, paid fallback or parallel router."
            ),
            executor_binding=(
                "app.services.harness_ai_provider_service.execute_harness_ai_generation"
            ),
            evidence_contract=(
                "app.services.harness_ai_provider_service.HarnessAIProviderEvidence"
            ),
            provider_id="nvidia_nim",
            model_id="nvidia/nemotron-3.5-lightning-30b-a3b",
            cost_class="FREE_ENDPOINT",
            quota_class="NVIDIA_FREE_ENDPOINT_RATE_LIMIT_OR_QUOTA_POSSIBLE",
            latency_class="EXTERNAL_MODEL_DEPENDENT",
            quality_class="FAST_AGENTIC_REASONING",
            fallback_eligibility=False,
            supports_review=True,
            health_policy="PROVIDER_AND_MODEL_RUNTIME_HEALTH",
        ),
        _record(
            capability_id="ai.provider.gemini",
            capability_type="PROVIDER",
            domain="ai",
            implementation="GeminiAIProvider adapter",
            input_contract="prompt text",
            output_contract="AIResponse",
            requirements=("GEMINI_API_KEY", "Harness provider policy integration"),
            maturity=PARTIAL,
            availability=UNKNOWN,
            allowed_actions=("RESEARCH", "EDITORIAL"),
            policy_tags=("ai", "provider", "gemini", "text"),
            security_boundary=(
                "Adapter exists but Harness provider-policy integration is unproven"
            ),
            executor_binding=None,
            evidence_contract="app.services.ai_provider.AIResponse",
            provider_id="gemini",
            model_id="gemini-2.5-flash",
            cost_class="EXTERNAL_MODEL",
            quota_class="GEMINI_API",
            latency_class="EXTERNAL",
            quality_class="UNPROVEN_UNDER_HARNESS",
        ),
        _record(
            capability_id="gta6.research",
            capability_type="SKILL",
            domain="research",
            implementation="GTA6 research pipeline",
            input_contract="Harness research trigger",
            output_contract="persisted research result",
            requirements=("research sources", "central SQLite"),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH",),
            policy_tags=("gta6", "research", "sources", "fact"),
            security_boundary="Harness MCP delegates to official research service",
            executor_binding="app.services.gta6_research_pipeline.run_gta6_research",
            evidence_contract="research pipeline result with source lineage",
            skill_id="gta6-research",
            instruction_path=".dsh/skills/gta6-research/SKILL.md",
            side_effects=("persist research",),
        ),
        _record(
            capability_id="gta6.fact-check",
            capability_type="SKILL",
            domain="research",
            implementation="native GTA6 fact-check skill metadata",
            input_contract="claim + evidence context",
            output_contract="fact-check assessment",
            requirements=("selected evidence context",),
            maturity=PARTIAL,
            availability=UNKNOWN,
            allowed_actions=("RESEARCH", "EDITORIAL"),
            policy_tags=("gta6", "fact", "check", "evidence"),
            security_boundary="Skill exists; bounded runtime binding not proven",
            executor_binding=None,
            evidence_contract="fact-check evidence",
            skill_id="gta6-fact-check",
            instruction_path=".dsh/skills/gta6-fact-check/SKILL.md",
        ),
        _record(
            capability_id="knowledge.retrieve",
            capability_type="CAPABILITY",
            domain="knowledge",
            implementation="GTA6 Knowledge Brain query service",
            input_contract="knowledge query",
            output_contract="knowledge context with confidence and lineage",
            requirements=("persisted GTA6 knowledge",),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("RESEARCH", "EDITORIAL"),
            policy_tags=("knowledge", "memory", "retrieval", "gta6"),
            security_boundary="read-only Harness knowledge query",
            executor_binding=(
                "app.services.gta6_knowledge_query_service."
                "query_gta6_knowledge_context"
            ),
            evidence_contract="GTA6 knowledge context with evidence lineage",
        ),
        _record(
            capability_id="editorial.process",
            capability_type="SKILL",
            domain="editorial",
            implementation="editorial queue consumer",
            input_contract="queued editorial item + AI provider",
            output_contract="editorial production-chain result",
            requirements=("queued editorial work", "official AI provider"),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EDITORIAL",),
            policy_tags=("editorial", "queue", "gta6"),
            security_boundary="Harness MCP delegates to official editorial consumer",
            executor_binding=(
                "app.services.editorial_queue_consumer."
                "process_next_editorial_queue_item"
            ),
            evidence_contract="editorial consumer result",
            skill_id="gta6-editorial",
            instruction_path=".dsh/skills/gta6-editorial/SKILL.md",
            side_effects=("persist editorial state",),
        ),
        _record(
            capability_id="script.generate",
            capability_type="CAPABILITY",
            domain="production",
            implementation="script generator service",
            input_contract="editorial/content context",
            output_contract="script",
            requirements=("content/editorial state",),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EDITORIAL", "EXECUTION"),
            policy_tags=("script", "writing", "production"),
            security_boundary="official production service boundary",
            executor_binding="app.services.script_generator_service.generate_and_save_script",
            evidence_contract="persisted script/content lineage",
            side_effects=("persist script",),
        ),
        _record(
            capability_id="production.plan",
            capability_type="SKILL",
            domain="production",
            implementation="production plan service",
            input_contract="content + script + production requirements",
            output_contract="ProductionPlan",
            requirements=("content item", "script"),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EDITORIAL", "EXECUTION"),
            policy_tags=("production", "plan", "scenes"),
            security_boundary="official production-plan service boundary",
            executor_binding="app.services.production_plan_service.create_production_plan",
            evidence_contract="ProductionPlan lineage",
            skill_id="gta6-production",
            instruction_path=".dsh/skills/gta6-production/SKILL.md",
            side_effects=("persist production plan",),
        ),
        _record(
            capability_id="media.discovery",
            capability_type="CAPABILITY",
            domain="media",
            implementation="GTA6 media discovery/catalog services",
            input_contract="media discovery request",
            output_contract="catalogued media candidates",
            requirements=("media sources",),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("media", "discovery", "catalog", "gta6"),
            security_boundary="official media discovery/catalog boundary",
            executor_binding="app.services.gta6_media_discovery_service.discover_gta6_media_candidates",
            evidence_contract="media candidate/source lineage",
            side_effects=("persist media catalog",),
        ),
        _record(
            capability_id="speech.transcription.whisperx",
            capability_type="PROVIDER",
            domain="media-analysis",
            implementation="WhisperX speech provider",
            input_contract="audio/media input",
            output_contract="speech analysis/transcript",
            requirements=("WhisperX runtime", "media input"),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("speech", "transcription", "whisperx", "audio"),
            security_boundary="speech provider/service boundary",
            executor_binding="app.services.speech.whisperx_provider",
            evidence_contract="speech provider analysis result",
            provider_id="whisperx",
        ),
        _record(
            capability_id="media.technical-analysis",
            capability_type="CAPABILITY",
            domain="media-analysis",
            implementation="MediaKnowledge/media analysis services",
            input_contract="media asset",
            output_contract="structured technical media evidence",
            requirements=("media asset",),
            maturity=PARTIAL,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("media", "analysis", "knowledge", "technical"),
            security_boundary="media analysis services + central persistence",
            executor_binding="app.services.media_analysis.analyze_media_technical",
            evidence_contract="MediaKnowledge structured evidence",
        ),
        _record(
            capability_id="media.select",
            capability_type="CAPABILITY",
            domain="media",
            implementation="media selection service",
            input_contract="production intent + media candidates",
            output_contract="selected media references",
            requirements=("production plan", "media candidates"),
            maturity=PARTIAL,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("media", "selection", "production"),
            security_boundary="official media-selection service boundary",
            executor_binding="app.services.media_selection_service.select_media_segments",
            evidence_contract="selected media/source lineage",
        ),
        _record(
            capability_id="video.edit.vedit",
            capability_type="EXECUTOR",
            domain="audiovisual",
            implementation="VEdit service",
            input_contract="authorized production intent + media evidence",
            output_contract="EditPlan/audiovisual specification",
            requirements=("production plan", "media references"),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("video", "edit", "vedit", "audiovisual"),
            security_boundary="VEdit consumes Harness-authorized production context",
            executor_binding="app.services.vedit_service.create_edit_plan",
            evidence_contract="EditPlan + source/scene lineage",
            provider_id="vedit",
        ),
        _record(
            capability_id="video.render",
            capability_type="EXECUTOR",
            domain="audiovisual",
            implementation="render orchestration/service",
            input_contract="authorized render job + executable edit plan",
            output_contract="render artifact/result",
            requirements=("Harness EXECUTION authorization", "render job"),
            maturity=PROVEN,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("video", "render", "artifact"),
            security_boundary="Gate-1 queued->running fail-closed render boundary",
            executor_binding="app.services.render_orchestration_service.execute_render_job",
            evidence_contract="RenderExecutionResult + job provenance",
            side_effects=("render job state transition", "render artifact"),
        ),
        _record(
            capability_id="media.ffmpeg",
            capability_type="TOOL",
            domain="audiovisual",
            implementation="Internal FFmpeg tool used only through authorized render workers",
            input_contract="validated render-worker executable media plan",
            output_contract="processed/rendered media artifact inside parent render evidence",
            requirements=("FFmpeg", "authorized parent render capability"),
            maturity=FUNCTIONAL,
            availability=UNKNOWN,
            allowed_actions=(),
            policy_tags=("ffmpeg", "media", "render", "processing", "support"),
            security_boundary="support tool only; never independently routed or caller-parameterized by the Harness",
            executor_binding=None,
            evidence_contract="parent production.render.execute / video.render artifact evidence",
            side_effects=("media artifact through authorized parent render",),
        ),
        _record(
            capability_id="cloud.github-actions",
            capability_type="TOOL",
            domain="cloud-execution",
            implementation="Internal GitHub Actions transport used by bounded workflow-specific dispatchers",
            input_contract="workflow-specific authorized dispatch from a parent capability",
            output_contract="workflow execution identity/status/artifact",
            requirements=("GitHub Actions", "workflow-specific Harness boundary"),
            maturity=PROVEN,
            availability=UNKNOWN,
            allowed_actions=(),
            policy_tags=("cloud", "github", "actions", "worker", "support"),
            security_boundary="support transport only; arbitrary workflow dispatch is never exposed as a generic Harness capability",
            executor_binding=None,
            evidence_contract="parent capability workflow run identity/status/artifact evidence",
            provider_id="github-actions",
            side_effects=("workflow dispatch through authorized parent capability",),
        ),
        _record(
            capability_id="qa.preflight",
            capability_type="CAPABILITY",
            domain="qa",
            implementation="render/VEdit/speech QA and artifact validation",
            input_contract="planned/executed media artifact",
            output_contract="validation/QA evidence",
            requirements=("artifact or executable plan",),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("qa", "preflight", "validation", "safety"),
            security_boundary="validation-only; no authority grant",
            executor_binding="app.services.render_artifact_validator.validate_render_artifact",
            evidence_contract="validation/QA result",
        ),
        _record(
            capability_id="youtube.upload-private",
            capability_type="EXECUTOR",
            domain="publication",
            implementation="Harness-governed GitHub Actions private-upload dispatcher/reconciler",
            input_contract="exact pending publication + QA-proven GitHub media artifact locator",
            output_contract="cloud execution identity then private uploaded YouTube publication",
            requirements=("YouTube OAuth secrets in GitHub Actions", "QA-proven render artifact", "canonical SQLite publication"),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("YOUTUBE",),
            policy_tags=("youtube", "upload", "private", "publication", "cloud", "targeted"),
            security_boundary="Harness routes exact publication; canonical DB claims before cloud dispatch; worker verifies artifact hash/QA/lineage and cannot publish public",
            executor_binding="app.services.youtube_cloud_upload_service.dispatch_targeted_private_upload",
            evidence_contract="persisted cloud execution + YouTube identity + render artifact evidence",
            provider_id="youtube",
            skill_id="gta6-youtube",
            instruction_path=".dsh/skills/gta6-youtube/SKILL.md",
            side_effects=("YouTube upload", "persist publication state"),
        ),
        _record(
            capability_id="youtube.publish-public",
            capability_type="EXECUTOR",
            domain="publication",
            implementation="YouTube public publication orchestration",
            input_contract="uploaded publication + PUBLICATION HarnessAuthorization",
            output_contract="published YouTube publication",
            requirements=("persisted PUBLICATION authorization", "uploaded publication"),
            maturity=PROVEN,
            availability=AVAILABLE,
            allowed_actions=("PUBLICATION",),
            policy_tags=("youtube", "publish", "public", "publication"),
            security_boundary="Gate-1 explicit PUBLICATION authorization boundary",
            executor_binding=(
                "app.services.youtube_publication_orchestration."
                "make_youtube_publication_public"
            ),
            evidence_contract="YouTube publication state + Harness provenance",
            provider_id="youtube",
            skill_id="gta6-youtube",
            instruction_path=".dsh/skills/gta6-youtube/SKILL.md",
            side_effects=("public YouTube publication",),
        ),
        _record(
            capability_id="analytics.learning",
            capability_type="CAPABILITY",
            domain="analytics",
            implementation="no proven active analytics/learning service in baseline",
            input_contract="outcome/analytics evidence",
            output_contract="learning evidence",
            requirements=("future proven analytics integration",),
            maturity=UNPROVEN,
            availability=UNKNOWN,
            allowed_actions=(),
            policy_tags=("analytics", "learning", "feedback"),
            security_boundary="not executable until a real integration is proven",
            executor_binding=None,
            evidence_contract=None,
        ),
        _record(
            capability_id="tubegent",
            capability_type="AGENT",
            domain="unknown",
            implementation="not present/proven in the active baseline",
            input_contract="unknown",
            output_contract="unknown",
            requirements=("future proven integration",),
            maturity=UNPROVEN,
            availability=UNKNOWN,
            allowed_actions=(),
            policy_tags=("tubegent", "agent"),
            security_boundary="not integrated; no execution binding",
            executor_binding=None,
            evidence_contract=None,
            agent_id="tubegent",
        ),
    )


GLOBAL_CAPABILITY_REGISTRY = GlobalCapabilityRegistry(
    (*_native_records(), *_addy_records(), *_higgsfield_records())
)
