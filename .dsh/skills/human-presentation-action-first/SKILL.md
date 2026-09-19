---
name: human.presentation.action-first
description: Deterministic human-facing presentation policy adapted from ayghri/i-have-adhd, pinned at b15d0be58f55b33972ba3e39709e0e5208ef30cb.
license: MIT
source: ayghri/i-have-adhd
source_version: 0.3.0
source_commit: b15d0be58f55b33972ba3e39709e0e5208ef30cb
upstream_skill_blob_sha: 9138ae4af11065b7971eea17edc48a2498c1af35
capability_type: PRESENTATION
authority: NONE
side_effects: NONE
memory_write: FORBIDDEN
routing_authority: NONE
editorial_authority: NONE
publication_authority: NONE
supported_surfaces: [telegram, work, codex, termux, admin]
presentation_modes: [NORMAL, ACTION_FIRST, TECHNICAL_FULL, MACHINE_READABLE]
---

# human.presentation.action-first

Presentation only. The DeepSeek Harness has already produced the canonical result before this skill is applied.

Rules:

1. Put the conclusion or next user action first.
2. Keep visible steps bounded and concrete.
3. Remove internal telemetry from the default human reply.
4. For failures, show FAIL plus an observed cause when one exists and a supported recovery action when one exists. Never invent a cause.
5. Preserve material warnings and uncertainty. INSUFFICIENT_EVIDENCE, CONTRADICTED, BLOCKED and FAIL may never be softened into PASS.
6. Never mutate the canonical result. ResearchDossier, ClaimLedger, FactCheckResult, artifacts, traces and machine-readable payloads remain complete.
7. Telegram defaults to ACTION_FIRST. TECHNICAL_FULL and MACHINE_READABLE remain available for audit/debug surfaces.
8. This skill has no memory write, routing, editorial, production or publication authority.

The upstream project also recommends action-first structure, short working sets, no tangents and matter-of-fact errors. Its always-on hooks and session-global injection are intentionally not used here because the BR-no-GTA Harness remains the sole authority.
