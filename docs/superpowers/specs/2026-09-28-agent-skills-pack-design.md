# Agent Skills Pack Design

Date: 2026-09-28
Repository: zenindiones-maker/BR-no-GTA
Integration branch: work/superpowers-skill-pack
Target branch after approval: work/gate6f-analytics-learning

## Intent

Install a governed development/media skill pack for BR-no-GTA without creating a second control plane, hidden execution path, or unbounded prompt injection.

Requested skills:

- Superpowers
- TDD
- Teach
- Caveman
- Handoff
- Video Edit

DeepSeek Harness remains the sole routing, authorization, policy, execution and publication authority.

## Sources and pins

### Superpowers for DSH
Source: LayneChai/superpowers-dsh
Pinned commit: 0b660254ab93b592e9810b493ccd63ecdf1a4663
Role: DeepSeek Harness skill-provider adapter for the obra/superpowers methodology.
Upstream methodology: obra/superpowers.
Current upstream reference observed during design: 8ca22dba9a94f28898bbce59f2537ff4d87c747d.
License: MIT.

### TDD
Source: mattpocock/skills
Pinned commit: c55ee46073ed923f86ce59a5eb3b6d895095d1b7
Source path: skills/engineering/tdd/
Exposed skill id: tdd
License: MIT.

### Teach
Source: mattpocock/skills
Pinned commit: c55ee46073ed923f86ce59a5eb3b6d895095d1b7
Source path: skills/productivity/teach/
Exposed skill id: teach
License: MIT.
Invocation policy: explicit/user-directed by default.

### Handoff
Source: mattpocock/skills
Pinned commit: c55ee46073ed923f86ce59a5eb3b6d895095d1b7
Source path: skills/productivity/handoff/
Exposed skill id: handoff
License: MIT.
Invocation policy: explicit/user-directed by default.

### Caveman
Source: JuliusBrussee/caveman
Pinned commit: 2fd153c67988e980fb0b2455c90832159a6a5a25
Source path: skills/caveman/
Exposed skill id: caveman
Scope: output-style/token-efficiency skill only.
Do not install or authorize the Caveman proxy/runtime/middleware as part of this change.
Reason: the user requested the skill, while the proxy/runtime has a wider execution and licensing/security surface.

### Video Edit
Source: genmedia-labs/skills
Pinned commit: c163a9fd3ab3c36193f634445592586df5b64f1e
Source path: video-edit/
Exposed skill id: video-edit
License: MIT.
Scope: procedural/model-routing knowledge only.
The skill MUST NOT directly invoke RunComfy or any other external service outside Harness authorization.

## Architecture

The pack is a subordinate skill layer:

external pinned skill sources
  -> deterministic import/provider layer
  -> DSH skill discovery
  -> Harness task/capability selection
  -> Harness authorization
  -> subordinate agent/runtime
  -> canonical result/evidence/episode

Skills do not become agents, control planes, providers, publication actors, or authorization authorities merely by being installed.

## Authority contract

Every imported skill is classified as:

- authority: NONE
- routing_authority: NONE
- policy_authority: NONE
- publication_authority: NONE
- memory_write: FORBIDDEN unless a separate Harness capability explicitly authorizes a bounded write
- direct_external_side_effects: FORBIDDEN
- direct_repository_mutation: FORBIDDEN unless execution occurs under an already-authorized DEVELOPMENT capability
- control_plane: DEEPSEEK_HARNESS

A skill may shape methodology, reasoning procedure, output structure, or tool-selection advice. It may not grant itself permission to execute side effects.

## Installation model

Use a repository-pinned, deterministic installation rather than a floating latest dependency.

Preferred implementation:

1. Add a canonical skill-pack manifest containing source repository, pinned commit, source path, license, exposed id and authority metadata.
2. Materialize the approved skill content/provider into repository-controlled DSH skill/plugin surfaces.
3. Verify content digest/provenance during CI.
4. Expose only the requested skill ids plus the Superpowers provider's standard development skills.
5. Keep automatic global bootstrap disabled by default for BR-no-GTA production/research sessions.
6. Allow Superpowers process skills to be invoked for DEVELOPMENT/system-improvement workflows where their contract matches the task.
7. Preserve existing .dsh/skills domain skills and human.presentation.action-first unchanged.

## Bootstrap policy

SUPERPOWERS_BOOTSTRAP_GLOBAL=OFF by default.

Reason:

- the project is actively optimizing prompt size and semantic planner latency;
- production/editorial missions should not receive development methodology instructions unless needed;
- globally injecting the bootstrap would make every session pay the context cost;
- DeepSeek Harness must retain explicit routing control.

Development-specific sessions may load Superpowers explicitly through the skill registry.

## TDD policy

Both the Superpowers test-driven-development methodology and the explicitly requested mattpocock tdd skill may coexist, but they must not create ambiguous routing.

Canonical exposed aliases:

- superpowers.test-driven-development -> Superpowers process skill
- tdd -> mattpocock behavioral seam-oriented TDD skill

The Harness/task protocol decides which one is selected. Selection must be observable in evidence.

## Teach policy

Teach is a human-learning/workspace methodology, not production authority.

It must not silently create or mutate persistent teaching files in BR-no-GTA during ordinary missions.
Any workspace writes require an explicitly authorized DEVELOPMENT/HUMAN_WORKSPACE task with bounded write scope.

## Caveman policy

Only the small output-style skill is in scope.

Caveman may shorten explanatory prose but MUST NOT:

- compress or rewrite canonical machine-readable artifacts;
- alter exact commands, file paths, hashes, error messages, receipts, evidence or contracts;
- soften FAIL/BLOCKED/INSUFFICIENT_EVIDENCE states;
- modify Harness inputs or user prompts;
- install its proxy, middleware or background runtime;
- become a production semantic transformation layer.

human.presentation.action-first retains precedence on human-facing project surfaces.

## Handoff policy

Handoff may create a compact continuation artifact only when explicitly requested or routed.

It must:

- reference canonical artifacts instead of duplicating them;
- redact secrets;
- preserve mission_id, goal_id, task_id, HEAD SHA and relevant evidence refs;
- never declare mission completion;
- never become a durable mission checkpoint substitute.

The Harness durable state remains canonical.

## Video-edit policy

The imported video-edit skill is advisory/procedural.

It may describe or recommend a model/edit route, but actual media execution must map to an existing or newly reviewed Harness capability with:

- typed input/output contract;
- provider route;
- explicit authorization;
- bounded side-effect class;
- evidence receipt;
- episode capture.

No RunComfy token, CLI login, network call or third-party media upload is enabled by this skill-pack installation alone.

Existing BR-no-GTA video policies remain authoritative, including master format, branding, subtitle policy, voice policy, human review gates and publication gate.

## Provenance and integrity

The implementation must produce a machine-readable manifest and verification receipt containing at minimum:

- skill_id
- source_repository
- source_commit
- source_path
- license
- local_materialized_path or provider id
- content_digest
- authority
- bootstrap_policy
- imported_at
- verifier_version

CI must fail closed if an imported skill differs from its pinned source without an intentional manifest update.

## Registry / inventory treatment

Skills are not automatically promoted to executable capabilities.

System Agent Inventory must distinguish:

- AGENT
- EXECUTOR
- SKILL
- PROVIDER
- SUPPORT_COMPONENT

and show these imported items as SKILL/provider-support identities with authority NONE unless a separate CapabilityRecord explicitly wraps them.

No imported skill may make CONTROL_PLANE_COUNT exceed 1.

## Tests

Required focused proofs:

1. SUPERPOWERS_PROVIDER_LOADED=PASS
2. REQUESTED_SKILLS_DISCOVERED=PASS
3. TDD_DISCOVERED=PASS
4. TEACH_DISCOVERED=PASS
5. CAVEMAN_DISCOVERED=PASS
6. HANDOFF_DISCOVERED=PASS
7. VIDEO_EDIT_DISCOVERED=PASS
8. SUPERPOWERS_BOOTSTRAP_GLOBAL=OFF
9. HARNESS_AUTHORITY_PRESERVED=PASS
10. CONTROL_PLANE_COUNT=1
11. NO_DIRECT_EXECUTION_BYPASS=PASS
12. NO_DIRECT_EXTERNAL_SIDE_EFFECT=PASS
13. PINNED_PROVENANCE=PASS
14. CONTENT_DIGEST_VERIFIED=PASS
15. SYSTEM_AGENT_INVENTORY_COHERENT=PASS
16. EXISTING_DSH_SKILLS_UNCHANGED=PASS

Negative tests:

- video-edit cannot perform an external call without Harness authorization;
- teach cannot silently write a teaching workspace during an unrelated mission;
- caveman cannot modify canonical receipts/contracts/errors;
- handoff cannot replace durable checkpoint state;
- imported skills cannot claim DEEPSEEK_HARNESS authority;
- a floating/unpinned source is rejected.

## Non-goals

This change does NOT:

- install anything in Termux;
- enable Caveman proxy/runtime;
- authorize RunComfy billing or media uploads;
- replace existing GTA6 domain skills;
- replace Harness task verification;
- alter publication policy;
- alter Voice B or final-video requirements;
- start a Production run;
- resolve unrelated current CI failures.

## Rollout

Phase 1: manifest + provenance + deterministic materialization/provider.
Phase 2: discovery and authority tests.
Phase 3: System Agent Inventory integration.
Phase 4: isolated DSH proof.
Phase 5: merge/fast-forward into work/gate6f-analytics-learning only after focused tests and review.

No Production run is part of this rollout.

## Acceptance

Installation is accepted only when the requested skill pack is discoverable from the Harness development surface, provenance is pinned and verified, no hidden side-effect path exists, global bootstrap remains off, and DeepSeek Harness remains the single authority/control plane.
