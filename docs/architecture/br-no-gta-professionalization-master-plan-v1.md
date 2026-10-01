# BR-no-GTA Professionalization Master Plan v1
**Version:** 1.0 — 2026-09-30
**Status:** Normative design supplement; the Operational Readiness Standard v1 remains certification authority.
**Authority:** Human owner → DeepSeek Harness sole system authority.
**Owner cost policy:** OpenAI Platform API inference spend is dormant/forbidden until explicit owner reauthorization; active OpenAI development path uses ChatGPT-plan Codex/Work allowance only.

## North-star
Maximize sustainable expected YouTube profit and audience value over time, subject to truth, YouTube policy, originality, advertiser friendliness, brand integrity, rights/provenance, evidence and final human publication authority. Do not optimize agent count, CTR, views, duration, RPM or upload volume in isolation.

## Current snapshot
- Canonical branch: `work/gate6f-analytics-learning`
- Canonical remote HEAD at document creation: `8f9869a0181a1b9fefe8865d5ce4e35f2d77de4a`
- `ACTIVE_RUNS=0`, `QUEUED_RUNS=0`
- Staging Block A: `staging/block-a-live-20260930` @ `edaf8fec7af8e217288a752d0d1ebb718f41ca61`
- Block A Sprites preserved; do not restart or discard legitimate newer work.

## Layer map
- **L0 — Governance & Operational Readiness:** Authority, cost policy, risk policy, publication authority, G0–G14 certification Primary output: Operational Standard + Certification. Build order: Always active.
- **L1 — Agent Execution Foundation:** Real Codex/worker execution in bounded compute with typed result and Harness reduction Primary output: AgentEnvironmentLease, TaskResultEnvelope. Build order: CURRENT.
- **L2 — Task Excellence Plane:** Compile atomic tasks; choose topology, worker, context, Skills, tools and budget from evidence Primary output: TaskCognitiveProfile, TaskExecutionBlueprint, TaskContextManifest, ProgressLedger. Build order: CURRENT.
- **L3 — Source / Build / Supply Chain:** Root suite, reproducibility, immutable CI dependencies, provenance, branch/HEAD integrity Primary output: G0 evidence package. Build order: NEXT.
- **L4 — Control / Durable / Provider / Observability:** Mission semantics, Durable V3, claims/fencing, outbox, wait/requeue, unified traces Primary output: Mission/Task/Attempt trace + provider recovery proof. Build order: After L3.
- **L5 — Human Operator Surface:** Telegram owner commands, private review, privileged approvals, no parallel authority Primary output: OwnerCommandEnvelope, receipts. Build order: After L4.
- **L6 — Market / Audience / Opportunity:** Find high-value video opportunities before spending script/edit capacity Primary output: OpportunityBrief, AudienceIntentMap, CompetitiveEvidence. Build order: Content wave.
- **L7 — GTA VI Evidence & Knowledge:** Official/primary/secondary evidence, scene/timecode observables, rumor status, provenance Primary output: EvidenceUnit, ClaimLedger, EvidenceMap. Build order: Content wave.
- **L8 — Script / Story / Retention Engine:** Turn evidence + opportunity into original long-form narrative optimized for appeal/engagement/satisfaction Primary output: ViewerPromise, StoryArchitecture, RetentionBlueprint, ScriptQA. Build order: Core creative.
- **L9 — Packaging Engine:** Truthful title/thumbnail hypotheses bound to script promise and audience intent Primary output: PackagingHypothesis, PromiseMatch. Build order: Parallel with script late stage.
- **L10 — Voice / Audio Production:** Human-approved owner voice, pronunciation, mix/master, music/SFX policy Primary output: VoiceTakeSet, AudioQA. Build order: Production.
- **L11 — Visual Assets / Editing / Render:** Rights-aware asset plan, edit intent, rough/final cut, motion/sound, deterministic render Primary output: AssetProvenance, VisualCoverageMap, EditPlan, RenderManifest. Build order: Production.
- **L12 — Policy / Monetization / Product QA:** Originality, reused/inauthentic risk, advertiser friendliness, AI disclosure, final technical gates Primary output: PolicySnapshot, MonetizationReadiness, MasterQA. Build order: Pre-publication hard gate.
- **L13 — Private Publishing / Distribution:** YouTube PRIVATE HD review transport, Telegram delivery, owner approval; later public only on explicit authority Primary output: PublicationPlan, PrivateReviewReceipt. Build order: Human gate.
- **L14 — Analytics / Revenue / Experimentation / Learning:** Appeal-engagement-satisfaction-revenue learning, A/B experiments, postmortems, competence/memory Primary output: VideoBusinessOutcome, Experiment, LearningEpisode. Build order: Continuous.
- **L15 — Natural Swarm End-to-End Certification:** One literal human goal traverses the entire system with fresh lineage to PRIVATE review Primary output: BRNoGTAOperationalReadinessCertification/v1. Build order: LAST.

## Development continuity foundation

Before Wave B feature work, every long-running development mission uses Development Continuity & Recovery Plane v1: isolated workspace, optional execution snapshot, forward-only recovery/dev/** journal, DevelopmentProgressLedger/v1, shadow-index checkpointing, remote readback verification, optimistic writer fencing and fail-closed canonical promotion. Sprite state is acceleration only, never the sole system of record. Development checkpoint resume cannot replay external side effects.

## Build waves
- **Wave A — Execution substrate (L1 + L2):** Prove one real Codex worker, atomic task compiler, context/Skill routing, independent review, durable resume, eval foundation. No DD3 yet.
- **Wave B — Integrity (L3):** Resolve/classify root-suite failures; full-SHA Actions; reproducibility; secret/supply-chain controls; close G0.
- **Wave C — Control reliability (L4 + L5):** Fresh Durable V3 conformance; provider wait/recovery; unified traces; Telegram privileged surface. Only then enable persistent production specialists.
- **Wave D — Content engine (L6 + L7 + L8 + L9):** Opportunity → evidence → script/retention → packaging. These become the strategic core of the channel.
- **Wave E — Production engine (L10 + L11 + L12):** Owner voice/audio → visual/edit/render → policy/monetization/master QA.
- **Wave F — Business loop (L13 + L14):** PRIVATE review → explicit publish authority → official A/B when eligible → analytics/revenue → experiments → learning.
- **Wave G — Certification (L15):** Natural human goal end-to-end. Only fresh evidence on one lineage can certify operation.

## Task Excellence Plane
Human goal → MissionPlan/DAG → typed/atomic task → TaskCognitiveProfile → TaskTopologyAssessment → hard eligibility → confidence-aware competence → minimum sufficient coalition → context/Skills/tools/environment/budget → TaskExecutionBlueprint → execute → verify → Harness reduce → learn.

Required new/standardized contracts:
- **Execution/Task:** TaskCognitiveProfile/v1; TaskExecutionBlueprint/v1; TaskContextManifest/v1; TaskProgressLedger/v1; SkillSelectionReceipt/v1; AgentTaskEvalCase/Suite/Trial; LayerCertification/v1.
- **Market/Audience:** YouTubeOpportunityBrief/v1; AudienceIntentMap/v1; CompetitiveEvidence/v1; PortfolioPolicy/v1.
- **Evidence/Editorial:** EvidenceUnit/v1; ClaimLedger/v1; EvidenceMap/v1; EditorialEvidenceBudget/v1.
- **Script:** ViewerPromise/v1; StoryArchitecture/v1; RetentionBlueprint/v1; ScriptSection/v1; ScriptDraft/v1; ScriptQA/v1.
- **Packaging:** PackagingHypothesis/v1; PromiseMatch/v1; PackagingExperimentPlan/v1.
- **Voice/Audio:** VoiceReferenceSet/v1; VoiceTakeSet/v1; PronunciationQA/v1; AudioMasterQA/v1.
- **Visual/Edit:** AssetProvenance/v1; VisualCoverageMap/v1; EditIntent/v1; EditPlan/v1; RenderManifest/v1; MasterQA/v1.
- **Policy/Monetization:** YouTubePolicySnapshot/v1; OriginalityContract/v1; AdvertiserFriendlyReview/v1; SyntheticMediaDisclosureDecision/v1; MonetizationReadiness/v1.
- **Publishing/Business:** PublicationPlan/v1; PrivateReviewReceipt/v1; VideoBusinessOutcome/v1; Experiment/v1; Postmortem/v1; PortfolioLearning/v1.

## Topology policy
- SINGLE_AGENT for one coherent low-coupling outcome.
- SEQUENTIAL for dependency chains/shared mutable state/write overlap.
- PARALLEL_INDEPENDENT only for independent read-only branches.
- PARALLEL_WITH_REDUCTION for independent evidence/hypotheses with Harness fan-in.
- MAKER_CHECKER for mutation + independent verification.
- HYBRID for parallel analysis → serial mutation → independent review.
- HIERARCHICAL for durable multi-stage coordination; authority remains Harness.

## YouTube content/business system
### Market & audience
Every expensive video begins with `YouTubeOpportunityBrief/v1`, `AudienceIntentMap/v1`, `CompetitiveEvidence/v1`, and `PortfolioPolicy/v1`. Public competitor evidence is allowed; private competitor CTR/retention/RPM/revenue must remain UNKNOWN unless legitimately supplied.

### GTA VI evidence
Preserve OFFICIAL / PRIMARY / SECONDARY / RUMOR / UNVERIFIED / CONTRADICTED. Use `EvidenceUnit/v1`, `ClaimLedger/v1`, `EvidenceMap/v1`, `EditorialEvidenceBudget/v1`. Unsupported factual claims cannot enter an approved script.

### Script / Story / Retention
Script is a first-class strategic subsystem. Flow: Opportunity → Evidence → Story Architect → Retention Architect → Lead Scriptwriter → independent fact check → advertiser/originality review → independent editorial review → Script QA.
Hard gates: `UNSUPPORTED_CLAIMS=0`, supported editorial duration ≥20 min, no artificial padding, promise match, novelty, repetition pass, originality/transformative value, advertiser safety, visual bindability, pronunciation readiness.

### Packaging
Generate truthful `PackagingHypothesis/v1` candidates bound to the `ViewerPromise` digest. CTR is diagnostic, not the objective. Official YouTube A/B may test up to 3 title/thumbnail variants and selects by watch time, but private videos are not eligible; only run after explicit public authorization.

### Production
Use `AssetProvenance/v1`, `VisualCoverageMap/v1`, `EditIntent/v1`, `EditPlan/v1`, `RenderManifest/v1`, `MasterQA/v1`. Agent decides semantic edit intent; VEdit/FFmpeg executes deterministically. Final master: 1920×1080, 30 fps, H.264 yuv420p High, AAC, ≥20 min, structural/debug overlays OFF, burned/open subtitles OFF, owner-voice QA PASS.

### Policy / monetization
Every publication binds a fresh `YouTubePolicySnapshot/v1`; enforce `OriginalityContract/v1`, `AdvertiserFriendlyReview/v1`, `SyntheticMediaDisclosureDecision/v1`, `MonetizationReadiness/v1`. Never exploit stale policy assumptions.

### Publishing
MASTER_FINAL QA → YouTube PRIVATE → processing/HD verification → Telegram private link/receipt → `HUMAN_REVIEW=PENDING`. PUBLIC/UNLISTED remain forbidden until a fresh explicit owner order.

### Analytics / revenue / learning
Use `VideoBusinessOutcome/v1` around appeal, engagement, satisfaction, revenue/RPM, audience segments and production context; experiments must have hypotheses, guardrails and confidence; no causal claim from correlation alone.

## Immediate roadmap
1. Finish preserved L1/L2 Block A without restart; prove real Codex/ChatGPT-plan worker + Blueprint/context/Skill routing + review + resume + evals.
2. Execute L3 Source/Build/G0: root suite, full-SHA critical Actions, reproducibility/provenance.
3. Execute L4 control/durable/provider/observability fresh.
4. Only then start DD3 persistent specialists.
5. Behind stable interfaces, prototype L6–L9 content contracts in isolated Sprites.
6. Build L10–L12 production and policy QA, then L13 PRIVATE review, L14 learning and L15 end-to-end certification.

## References
- **[BR1] BR-no-GTA Operational Readiness Standard v1 (internal normative source)** — Library file BR-no-GTA_Operational_Readiness_Standard_v1.html — G0–G14, fail-closed certification, Harness authority, YouTube PRIVATE review, testing ladder.
- **[A1] OpenAI — Harness engineering: leveraging Codex in an agent-first world** — https://openai.com/index/harness-engineering/ — Depth-first blocks; environments/feedback loops; repository knowledge as system of record; short AGENTS.md.
- **[A2] OpenAI Developers — Skills** — https://developers.openai.com/api/docs/guides/tools-skills — Skill discovery, SKILL.md, supporting resources, capability directories, progressive loading.
- **[A3] OpenAI Developers — Rethinking skills and prompts for GPT-6 Astra** — https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra — Avoid bloated context; make instructions contextual; revisit AGENTS.md/Skills.
- **[A4] OpenAI Developers — Testing Agent Skills Systematically with Evals** — https://developers.openai.com/blog/eval-skills — Representative activation/output tests; skill descriptions drive invocation.
- **[A5] OpenAI Help — ChatGPT Work and Codex / Astra usage** — https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex — Plus includes Astra in Work/Codex; current CLI eligibility notes.
- **[G1] Google Research — Towards a science of scaling agent systems** — https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/ — 180 configurations; parallel vs sequential scaling; centralized error containment.
- **[H1] Anthropic — Building Effective Agents** — https://www.anthropic.com/engineering/building-effective-agents — Prompt chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer.
- **[H2] Anthropic — Effective harnesses for long-running agents** — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents — Incremental work, persistent progress state, startup orientation, end-to-end verification.
- **[H3] Anthropic — Demystifying evals for AI agents** — https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents — Agent eval design; representative tasks; deterministic/semantic graders.
- **[Y1] YouTube Help — Recommendation system** — https://support.google.com/youtube/answer/16533387?hl=pt-BR — Long-term satisfaction objective; audience/performance framing.
- **[Y2] YouTube Help — Understand content performance for recommendations** — https://support.google.com/youtube/answer/16559650?hl=en — Appeal / engagement / satisfaction performance buckets.
- **[Y3] YouTube Help — Impressions and CTR FAQ** — https://support.google.com/youtube/answer/7628154?hl=pt-BR — CTR context; clickbait warning; relevance + average view duration.
- **[Y4] YouTube Help — New, casual and regular viewers** — https://support.google.com/youtube/answer/10246996?hl=pt-BR — Audience segmentation for content strategy.
- **[Y5] YouTube Help — How YouTube Search works** — https://support.google.com/youtube/answer/16090438?hl=pt-BR — Search ranking: relevance, engagement, quality.
- **[Y6] YouTube Help — Key moments for audience retention** — https://support.google.com/youtube/answer/9314415?hl=pt — 30s intro, top moments, spikes, dips.
- **[Y7] YouTube Help — A/B test titles and thumbnails** — https://support.google.com/youtube/answer/16391400?hl=pt-BR — Up to 3 title/thumbnail variants; watch-time winner; private-video ineligibility.
- **[Y8] YouTube Help — Channel monetization policies** — https://support.google.com/youtube/answer/1311392?hl=pt-BR — Inauthentic/mass-produced content and reused content.
- **[Y9] YouTube Help — Generative AI disclosure** — https://support.google.com/youtube/answer/14328491?hl=pt-BR_ALL — Disclosure for significantly altered/generated realistic content.
- **[Y10] YouTube Help — Advertising guideline updates** — https://support.google.com/youtube/answer/9725604?hl=pt-br — Sep 2026 gaming violence timing update and other current advertiser policy changes.
- **[Y11] YouTube Help — Gaming and monetization** — https://support.google.com/youtube/answer/10291745?hl=pt-BR — Gaming profanity/violence ad-suitability guidance.
- **[Y12] YouTube Help — Mid-roll ads** — https://support.google.com/youtube/answer/6175006?hl=pt-BR — Mid-roll eligibility for monetized videos ≥8 minutes.
- **[Y13] YouTube Help — Understand YouTube revenue** — https://support.google.com/youtube/answer/9314488?hl=pt-BR — Revenue by content/source and RPM reporting.
- **[Y14] YouTube Help — Ad revenue analytics / RPM** — https://support.google.com/youtube/answer/9314357?hl=pt — RPM definition and monetization interpretation.
- **[S1] GitHub Docs — Secure use reference** — https://docs.github.com/en/actions/reference/security/secure-use — Full-length SHA pinning; action supply-chain hardening.
- **[S2] GitHub Docs — Artifact attestations** — https://docs.github.com/en/actions/concepts/security/artifact-attestations — Build provenance and integrity claims.
- **[S3] GitHub Docs — Security hardening deployments / OIDC** — https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments — Short-lived cloud authentication and deployment hardening.
- **[T1] OpenTelemetry — GenAI semantic conventions** — https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/ — Agent/model/tool/usage naming; sensitive-content warnings.
- **[O1] OWASP GenAI — Agentic Applications 2026 crosswalk** — https://genai.owasp.org/resource/aiuc-1-crosswalks-owasp-top-10-for-agentic-applications/ — Goal hijacking, tool misuse, identity abuse, memory poisoning, inter-agent and cascading risks.
