# Implementation Plan: Munder Difflin Agent Office

## Overview

Add a fail-closed, headless Agent Office capability beneath the DeepSeek Harness. The upstream Munder Difflin repository is pinned for reproducibility, while the BR adapter owns the stable contract and excludes Electron UI, autonomous triggers, canonical memory, publication, and secret handling.

## Architecture Decisions

- DeepSeek Harness remains the only authority; the office coordinator receives one persisted, bounded authorization.
- The stable Python adapter uses Munder's documented hive/mailbox/worktree concepts because upstream has no supported standalone headless runtime.
- Every editing worker receives a distinct git worktree. The canary is read-only and deterministic.
- Munder memory is mission scratch only. Results return through Harness evidence toward the existing Knowledge Brain boundary.
- Codex/Addy remains the existing registered engine; the Agent Office never launches arbitrary caller-provided commands.

## Task List

1. Pin upstream source and policy.
2. Add execution/result contracts and negative tests.
3. Add the headless adapter, service, evidence, Registry record, and Harness dispatch.
4. Add preflight, canary, and GitHub Actions workflows.
5. Run review, full validation, publish, and dispatch the canary.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---:|---|
| Upstream Electron coupling | High | Keep Electron optional and use only pinned core semantics in the adapter. |
| Parallel agents overwrite files | High | One worktree per worker plus post-run path enforcement. |
| Agent output escalates authority | High | Treat output as untrusted evidence; no direct decisions or publishing. |
| Autonomous upstream triggers run | High | Fail-closed policy disables scheduler, heartbeat, Slack, webhooks, auto mode, and publishing. |
| Secret leakage | High | No secrets in worker payload/evidence; recursive evidence redaction tests. |

## Open Questions

- Optional desktop-office visualization remains future work and is not part of the cloud worker.
