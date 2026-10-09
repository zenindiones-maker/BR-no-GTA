# BR-no-GTA — source of truth and deletion integrity

Status: binding development governance when referenced from `AGENTS.md`.
This is not an independent agent, promotion executor or secondary authority.

## Authority and precedence

The current owner's explicit instructions and the existing repository `AGENTS.md`
govern work. DeepSeek Harness remains the sole operational task authorizer and
reducer, subject to human approval and existing security/release boundaries.
This policy refines evidence handling; it grants no write, deployment, model,
credential, private-owner-voice or publication permissions.

For every change, resolve the **actual remote repository identity**, branch
ref, commit SHA, tree SHA, worktree status and appropriate Harness authorization
before changing files. Do not treat a branch name, historical planning note,
model response, cache, image, backup or unverified receipt as current truth.
Pinned Git objects and fresh remote readback are evidence, not authorization.

## History, deletion, and stale architecture

1. A deletion, replacement or intentional deprecation in a newer authorized
   lineage must be respected; older branches are historical evidence only.
2. Before restoring a missing component, inspect its last authorized Git
   history, deletion commit, reason, current code references, tests and owner
   direction. Do not infer that a missing file is an accidental loss.
3. Restoring a deliberately removed agent, workflow, service, credential path,
   dependency, model fallback or obsolete architecture requires fresh explicit
   authorization, review and regression tests. No automatic restoration.
4. Reject phantom imports, references to nonexistent active files and stale
   source-of-truth links. Do not quietly create placeholders to satisfy tests.
5. Preserve uncommitted work, durable checkpoints, recovery branches, receipts
   and owner assets. No reset --hard, blind force push, destructive checkout,
   unauthorized promotion, or deletion of unverified WIP.
6. Use exact-SHA diff, artifact identity, readback and fail-closed tests to
   reconcile changes. Security findings and human rejections remain blockers;
   a CI label or AI-created receipt cannot replace independent verification.

## CI/CD and branch governance

Development CI may run read-only checks, lint, safe builds and deterministic
tests. Conditional jobs must aggregate failures in an always-running required
check; skipped optional checks must not be individually required in GitHub.
Require valid checks from the intended GitHub App, bound to the reviewed
candidate SHA, prior to accepting a PR.

Repository rulesets are enforced by GitHub itself, not by prose or a Python
simulation. No workflow may assert that a ruleset is active until GET readback
confirms exact target branch, enforcement, rule set and check names.
For V24 setup see `docs/governance/v24-required-status-checks.md`.

## Protected domains

The owner voice `BR_OWNER_V1`, Telegram private material, A15 control-plane-only
rule, REA containment, SLM shadow evaluations and all publication/promotions
retain their existing explicit human and Harness authorization gates.
Do not route heavy computation, training, local inference or private artifacts
through the A15; no paid fallback, accidental publication or automatic merge.

## Acceptance evidence

Report separately (a) file/commit created, (b) tests and CodeQL on current
head, (c) actual GitHub ruleset activation, (d) owner review/approval,
and (e) authorized canonical promotion or publication. Unverified = pending.
