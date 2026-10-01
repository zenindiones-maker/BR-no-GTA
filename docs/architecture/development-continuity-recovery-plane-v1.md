# Development Continuity & Recovery Plane v1

**Status:** Normative architecture contract
**Authority:** Human owner → DeepSeek Harness sole authority
**Scope:** Active development WIP, progress, handoff and deterministic resume. It does not replace Durable V3 operational side-effect recovery.

## Purpose

Long-running development must survive process, worktree, Sprite and prior-chat loss. A Sprite is disposable compute/cache. A local commit, local tag, service log or agent statement is not durable development progress. DEVELOPMENT_PROGRESS_DURABLE=PASS requires a remote recovery commit plus independent remote readback verification.

The three planes remain distinct: execution snapshot for fast environment recovery; development remote journal under recovery/dev/<mission-id>; and DevelopmentProgressLedger/v1 for compact durable progress.

br_checkpoint_save.py remains the certified operational/human milestone checkpoint. continuous_state_checkpoint.py remains continuous operation-state transport. This plane is development WIP continuity.

## Objectives

- DEVELOPMENT_RPO_TARGET_SECONDS=300
- DEVELOPMENT_RPO_HARD_MAX_SECONDS=600
- DEVELOPMENT_RESUME_RTO_TARGET_SECONDS=600
- HEARTBEAT_INTERVAL_SECONDS=90 by default; liveness only.
- Semantic checkpoint events are primary; timer is only an RPO watchdog.

Heartbeat never runs tests, creates commits, restarts services, or implies durability.

## Contracts

DevelopmentProgressLedger/v1 contains mission/goal identity, canonical branch/base, recovery ref, verified checkpoint identity and sequence, plan/completed/current/next steps, blockers, decisions, rejected directions, known failures, validation/test state, evidence/artifact refs, do_not_repeat, side-effect reconciliation state and timestamp. It is not a chat transcript.

DevelopmentRecoveryCheckpoint/v1 is the externally verified envelope binding checkpoint/mission/task identity, sequence/kind, canonical base, recovery ref, previous remote OID, recovery commit/tree OIDs, workspace/runtime/agent/authorization identity, path set, content/checkpoint/ledger digests, step/test/failure/evidence state, remote write/readback result and resume instructions.

The Git tree stores DevelopmentRecoveryCheckpointCore/v1. recovery_commit_sha is an external readback property because a commit cannot contain its own SHA without self-reference. Verified readback upgrades the core to DevelopmentRecoveryCheckpoint/v1.

## Checkpoint classes and state machine

RECOVERY may contain incomplete or RED work and cannot promote. MILESTONE is a coherent handoff boundary. PROMOTION belongs to the separate canonical authority path and is rejected by the development checkpoint service. AUTO_CHECKPOINT=ALLOWED; AUTO_PROMOTION=FORBIDDEN.

DIRTY_LOCAL → LOCAL_SNAPSHOT_AVAILABLE → REMOTE_CHECKPOINT_PENDING → REMOTE_WRITE_COMPLETE → REMOTE_READBACK_VERIFIED → DURABLE. Only verified remote OID/tree plus ledger/core digests can produce durable PASS.

## Git transaction and writer fencing

Snapshots use a temporary GIT_INDEX_FILE: read the prior verified tree, materialize governed paths into the shadow index, write-tree, commit-tree, then push without force. Active index and source worktree semantics remain unchanged.

Every continuation writer binds EXPECTED_PREVIOUS_REMOTE_OID. A mismatch produces RECOVERY_REF_CONFLICT and requires fetch/inspect/reconcile. Last-writer-wins and force push are forbidden.

Crash recovery selects either the previous verified remote checkpoint or a new checkpoint independently validated from remote bytes. Fresh resume never trusts local confirmation state.

## Security, privacy and large evidence

Recoverable state includes source, tests, versioned config, schemas, architecture docs and small structured evidence. Private/credential paths and secret-like content fail closed as BLOCKED_SECRET_RISK. Essential source cannot be silently omitted while claiming success.

Large logs, traces, databases, coverage, archives and media are not committed merely as backup. Checkpoint state retains locator/provenance, SHA-256, size and retention/rematerialization policy. GitHub Actions artifact existence alone is not canonical durable state.

## Workflow and side-effect isolation

recovery/dev/** is noncanonical and must not trigger production, publication, deployment, provider spend, Telegram delivery, YouTube upload or autonomous mutation. Resume never replays external effects. Unknown effect state returns SIDE_EFFECT_RECONCILIATION_REQUIRED and delegates to Durable V3 operation-ledger reconciliation.

## Harness authority

Workers may request development.checkpoint.persist. Registry authority is NONE, publication authority NONE, and write scope is only recovery/dev/**. Persisted authorization must be exact for DEVELOPMENT and subject development.checkpoint.persist.

## Resume protocol

A fresh executor loads AGENTS.md and normative docs, resolves mission/ref, fetches latest recovery commit, validates schemas/digests/tree, compares canonical HEAD/base, checks unknown effects, reconstructs completed/current/next/blockers/do_not_repeat and continues the first incomplete authorized step.

Explicit outcomes: RESUME_READY, RECONCILIATION_REQUIRED, CHECKPOINT_CORRUPT, CHECKPOINT_STALE, SIDE_EFFECT_RECONCILIATION_REQUIRED, NO_RECOVERY_STATE.

## Retention

ACTIVE → PROMOTED → RETENTION_WINDOW → GC_ELIGIBLE → DELETED. GC requires verified canonical promotion, current-head verification, resolvable retained evidence and elapsed retention policy.

## Promotion boundary

Recovery commits are evidence, never mechanically merged. Final promotion derives a clean validated change set from canonical base and creates coherent canonical history. CHECKPOINT_HISTORY_IN_CANONICAL=0.
