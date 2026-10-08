# Source of truth and deletion integrity — BR-no-GTA

This policy is subordinate to the existing authority map in `AGENTS.md`. The DeepSeek Harness remains the **sole** execution and promotion authority; agents, GitHub, CI, Sprites and skills do not gain independent authority from this document.

## Authorized state

The only current source tree for an operation is the explicitly authorized **immutable commit SHA and Git tree SHA** from the approved branch or worktree, verified again immediately before execution. A newer or older branch, a cached workspace, historical CI success, an archived document or a deleted source file **never substitutes for these exact objects**. Disagreement, unavailable objects, missing required paths, or dirty mutable state blocks the affected operation.

## Deletion and retirement

Intentional deletions are durable decisions, not an invitation to restore from Git history. Record confirmed retired paths in `config/source-of-truth-policy.json` under `tombstones` with the deletion boundary commit, review rationale and associated change authorization. CI rejects any tracked reintroduction of a tombstoned path. Never restore merely because an old branch, commit, backup, generated test, agent memory, or external recommendation still mentions it. Historical evidence may remain read-only but has no live execution authority.

**Exceptional restoration:** require explicit owner approval, precise path and old/new SHAs, written purpose, independent security review when required, scoped tests, and a fresh authorized candidate tree before any change. A JSON assertion inside the candidate branch does not constitute independent approval. Changes to the tombstone registry require a separate, independently protected review; bypassing the guard by deleting an entry is not an approved exception. No force push or canonical promotion.

## Evidence and CI

`scripts/source_of_truth_guard.py` validates the exact HEAD and tree, required active files, registered tombstones and explicitly registered machine-readable evidence against commit/tree lineage. It rejects references to retired branches in active receipts. Historical files, unregistered evidence and free-form prose are **not** automatically assumed valid or exhaustively covered by this initial gate.

The governance workflow checks out the event SHA with full history and runs the guard against the Git objects resolved at the start of the job. It does not permit dirty working trees. Pull requests must additionally receive independent review and branch protection; self-reported test receipts cannot serve as an independent approval. This workflow is additive to the existing CI and does not change the Harness promotion or owner-voice boundaries.

## Work in progress

Before updating refs, commit legitimate changes to an authorized development branch or checkpoint WIP durably in an isolated environment. Stop on uncommitted content; do not discard, reset, stash-and-forget, checkout-overwrite or silently merge it. Document the base SHA, target SHA, diff, tests and reviewer evidence.

## Policy registry limitations

The initial `retired_branches`, `tombstones` and `evidence_files` registries are deliberately empty until an authorized, evidence-backed baseline is populated. An empty registry does **not** prove that old branches or deleted components are safe; it means such inventory is not yet enforced by the registry. Governance policy changes need independent review; CI passing alone is not permission to reintroduce removed architecture.

If `SOURCE_OF_TRUTH_AND_DELETION_POLICY.md` becomes available as an authorized current source, reconcile it without introducing another authority or restoring deleted files. This document does not assert that file exists.
