# BR-no-GTA — Experiment Intelligence Plane V4

**Status:** isolated candidate, NOT promoted. **Authority:** DeepSeek Harness only.
**Cost:** zero-cost only. **Owner Voice:** BR_OWNER_V1 protected; Vice City = "vaicy siti".

## Why this exists

The V3 reverse-engineering services measure audio, scene cuts, script timing, browser HAR statistics and software structure. None of those measurements alone establishes that a creative technique is better. V4 adds fair, reproducible experimental comparisons to help the existing Harness decide what deserves further testing.

This is a **governed assessment capability**, NOT a new scheduler, autonomous learning system, model trainer, memory writer, vocal identity provider or publisher.

## Research and engineering basis

- OpenAI evaluation best practices and grader reward hacking: https://developers.openai.com/api/docs/guides/evaluation-best-practices and https://developers.openai.com/api/docs/guides/graders
- Offline, benchmark and pairwise approaches: https://docs.langchain.com/langsmith/evaluation-types
- NIST Measure playbook: https://airc.nist.gov/airmf-resources/playbook/measure/
- GenAI tracing and privacy: https://opentelemetry.io/docs/specs/semconv/gen-ai/
- Local optional experiment tracking: https://mlflow.org/docs/latest/tracking

External services are references, not new paid or authorized providers. The core engine is standard-library Python and remains operational without an external evaluation SaaS.

## Canonical V4 contract

Capability ID: reverse-engineering.experiment.assess
Domain: experiment-intelligence
Action: RESEARCH
Binding: app.services.reverse_engineering_harness_service.execute_authorized_experiment_assessment
Output: BRTechniqueExperimentAssessment/v1 inside BRHarnessReverseEngineeringResult/v1.

The Harness must issue a persisted, exact-bound authorization containing:
- allowed_technique_ids: exact list of 1–8 approved technique IDs;
- experiment_dataset_sha256: hash of a frozen benchmark dataset;
- experiment_domain and experiment_task_class matching that dataset.

The existing CapabilityAdapter and global capability registry govern execution. Caller-controlled authority, unknown fields, wrong action, mismatched route, revoked authorization and dataset substitution fail closed.

## Scientific protocol

1. Before viewing candidate outputs, freeze a benchmark version, selected metric/direction/target/tolerance/method, zero-cost requirement and case identifiers. Divide cases into development and untouched holdout subsets.
2. Generate genuinely original candidate artifacts under **separately** Harness-authorized production tasks. V4 cannot execute generators or alter the editorial workflow.
3. Use the identical pinned measurement method to assess candidate and baseline on every same case. Include artifact SHA-256 and measurement receipt hashes; forbid different baselines across techniques.
4. Score outcomes as wins/ties/losses against the fixed baseline. A failed, skipped, critical-regression or charged trial blocks the technique regardless of scores.
5. Require at least six development and six heldout cases, positive development direction and one-sided exact sign-test p <= 0.05 on heldout wins vs losses. Small samples remain insufficient even with apparently favorable scores.
6. REVIEW_CANDIDATE means statistical evidence in a specific controlled test, not generalization, verified artistry or permission to route to production. Dataset contamination, multiple comparisons, resampling after failed tests, observer bias and fabricated SHA receipts must still be audited by an independent reviewer.
7. Optionally propose an eligible technique for the **next preregistered benchmark**. It is never an execution order. V4 does not write or update canonical memory.
8. Only after persisted real Harness episodes and human/editorial security review may the existing Harness learning reducer independently create a SYSTEM_IMPROVEMENT/ROUTING_POLICY_CHANGE candidate. The present V4 code deliberately does not call its writer.

## Failure taxonomy

- CRITICAL_REGRESSION: block despite apparent numerical success.
- PAID_OR_UNKNOWN_COST: block any fee or unknown costs under the zero-cost contract.
- TRIAL_FAILED / TRIAL_SKIPPED: incomplete measurement, block.
- MEASURABLE_QUALITY_REGRESSION: candidate performed worse beyond tolerance.
- INCOMPLETE_PAIRED_CASES, METHOD_DRIFT, BASELINE_REFERENCE_MISMATCH: reject the entire experiment.
- INSUFFICIENT_EVIDENCE: too few paired observations on development or holdout.
- NO_DEMONSTRATED_IMPROVEMENT: do not change baseline or routing.
- REVIEW_CANDIDATE: consider independent evaluation. Never automatic promotion.

## Application across the system

- Voice: PT-BR phoneme errors and alignment timing, after a private-only speaker identity gate in BR_OWNER_V1; no voice cloning through V4.
- Mix/master: LUFS targeting only against an explicitly chosen platform specification, loudness range, true-peak ceiling, intelligibility and human listening.
- Video/animation: frame corruption, cut recall vs human ground truth, camera-motion false positives, visual continuity and story pacing.
- Roteiros: source-cited factual errors, repetition and human narrative QA; word count alone is not semantic quality.
- REA/software: tested reproduction of owned app behavior with pinned runtime, exact executable/provider readiness.
- Websites: replayable owned UI behavior in separately authorized Playwright sessions and offline HAR summaries, with secrets excluded.

The current test fixtures are synthetic and validate the mechanism, not a real creative quality win. A one-case real-media smoke test validates data wiring but deliberately returns INSUFFICIENT_EVIDENCE.

## Acceptance boundary

Exact-head CI, adversarial authorization tests, a genuine media-derived observation, independent security review, privately documented real benchmark (>=12 paired diverse cases per technique), human adjudication, a production-like 20–25 minute episode, and owner approval must all be satisfied before promotion.

REA native provider diagnostics are not accepted as PASS when rea doctor exits with code 1. This development branch must not modify BR_OWNER_V1, Telegram review, main or the canonical learning branch.
