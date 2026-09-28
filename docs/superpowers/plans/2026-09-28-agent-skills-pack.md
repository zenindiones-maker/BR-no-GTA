# Agent Skills Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install Superpowers, TDD, Teach, Caveman, Handoff, and Video Edit as a pinned, auditable skill pack for BR-no-GTA while keeping DeepSeek Harness as the single authority/control plane.

**Architecture:** Keep third-party skills out of the executable capability plane unless a separate Harness capability explicitly wraps them. Vendor the five requested standalone skills into the repository with pinned provenance, install the pinned Superpowers DSH provider through a deterministic bootstrap, and extend inventory/proofs so discovery, provenance, bootstrap policy, and authority boundaries are machine-checkable.

**Tech Stack:** Python 3.12, pytest, Bash, Node.js 24, DeepSeek Harness `@deepseek-ai/dsh@0.1.7-rc.2`, GitHub Actions, JSON manifests, DSH project skills.

**Spec:** `docs/superpowers/specs/2026-09-28-agent-skills-pack-design.md`

## Global Constraints

- DeepSeek Harness remains the sole routing, authorization, policy, execution, and publication authority.
- All imported skills have `authority=NONE`, `routing_authority=NONE`, `policy_authority=NONE`, and `publication_authority=NONE`.
- `SUPERPOWERS_BOOTSTRAP_GLOBAL=OFF`.
- No imported skill may directly perform external side effects or repository mutation outside an existing Harness authorization.
- Caveman is the output-style skill only; do not install its proxy/runtime/middleware.
- Video Edit is advisory/procedural; do not authorize RunComfy login, token use, billing, upload, or network execution in this change.
- Teach and Handoff remain explicit/user-directed by default.
- Existing GTA6 domain skills and `human.presentation.action-first` remain unchanged.
- No Production run is part of this rollout.
- No Termux installation is part of this rollout.
- Existing unrelated CI failures are not to be hidden or reclassified as success.

## Review Focus

- A source pin exists but local vendored bytes drift: verification must fail closed before the skill is accepted.
- A skill name collides with an existing project skill: discovery must reject ambiguity instead of silently choosing one.
- Superpowers plugin loads but global bootstrap is accidentally enabled: proof must fail even if the provider itself is healthy.
- An imported skill advertises or acquires Harness authority/external side effects: inventory and contract tests must fail.
- Video Edit or Teach attempts an execution/write path without an authorized capability: negative tests must prove the operation is not granted by installation.

---

### Task 1: Canonical skill-pack manifest and offline verifier

**Files:**
- Create: `config/agent_skill_pack_v1.json`
- Create: `scripts/agent-tooling/agent_skill_pack.py`
- Create: `tests/test_agent_skill_pack_contracts.py`

**Interfaces:**
- Consumes: repository root plus `config/agent_skill_pack_v1.json`.
- Produces: `load_agent_skill_pack(root: Path) -> AgentSkillPack`, `verify_agent_skill_pack(root: Path) -> SkillPackVerification`, and stable manifest metadata used by later tasks.

- [ ] **Step 1: Write failing manifest-contract tests**

Add tests named:

`test_skill_pack_manifest_has_exact_requested_skills`
- assert requested ids are exactly `{"superpowers","tdd","teach","caveman","handoff","video-edit"}`.

`test_skill_pack_sources_are_full_commit_pins`
- assert every source commit matches `[0-9a-f]{40}`.
- assert no source uses `latest`, a branch name, or an unpinned URL.

`test_skill_pack_authority_is_none_and_bootstrap_is_off`
- assert all skill authority fields are `NONE`.
- assert pack-level `superpowers_bootstrap_global` is false.
- assert direct external side effects are false.

`test_skill_pack_rejects_duplicate_exposed_ids`
- mutate a fixture manifest to duplicate an id and assert validation fails.

- [ ] **Step 2: Run the tests and verify RED**

Run:
`pytest -q tests/test_agent_skill_pack_contracts.py`

Expected: FAIL because the manifest/parser do not exist.

- [ ] **Step 3: Implement the canonical manifest**

Create `config/agent_skill_pack_v1.json` with schema version 1 and these pinned sources:

- Superpowers DSH adapter: `LayneChai/superpowers-dsh@0b660254ab93b592e9810b493ccd63ecdf1a4663`
- Superpowers methodology reference: `obra/superpowers@8ca22dba9a94f28898bbce59f2537ff4d87c747d`
- TDD/Teach/Handoff: `mattpocock/skills@c55ee46073ed923f86ce59a5eb3b6d895095d1b7`
- Caveman: `JuliusBrussee/caveman@2fd153c67988e980fb0b2455c90832159a6a5a25`
- Video Edit: `genmedia-labs/skills@c163a9fd3ab3c36193f634445592586df5b64f1e`

For each exposed skill include source path, license, authority metadata, invocation policy, local path/provider id, and allowed side-effect class.

- [ ] **Step 4: Implement `agent_skill_pack.py`**

Define immutable dataclasses `AgentSkillSource`, `AgentSkillEntry`, `AgentSkillPack`, and `SkillPackVerification`.

`load_agent_skill_pack(root: Path) -> AgentSkillPack` must:
- parse the JSON;
- reject unknown schema versions;
- reject duplicate exposed ids;
- reject non-40-character lowercase SHA pins;
- reject any authority other than `NONE`;
- reject `superpowers_bootstrap_global=true`.

`verify_agent_skill_pack(root: Path) -> SkillPackVerification` must later validate vendored paths/digests but may report them as not-yet-materialized until Task 2.

- [ ] **Step 5: Run tests and verify GREEN**

Run:
`pytest -q tests/test_agent_skill_pack_contracts.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add config/agent_skill_pack_v1.json scripts/agent-tooling/agent_skill_pack.py tests/test_agent_skill_pack_contracts.py
git commit -m "feat(skills): define governed agent skill pack"
```

---

### Task 2: Vendor the five standalone skills with pinned provenance

**Files:**
- Create: `.dsh/skills/tdd/**`
- Create: `.dsh/skills/teach/**`
- Create: `.dsh/skills/handoff/**`
- Create: `.dsh/skills/caveman/**`
- Create: `.dsh/skills/video-edit/**`
- Create: `scripts/agent-tooling/sync_agent_skill_pack.py`
- Modify: `config/agent_skill_pack_v1.json`
- Modify: `tests/test_agent_skill_pack_contracts.py`

**Interfaces:**
- Consumes: Task 1 manifest and exact pinned upstream commits.
- Produces: repository-controlled DSH skill bundles plus SHA-256 content digests recorded in the manifest.

- [ ] **Step 1: Add failing vendored-content tests**

Add:

`test_vendored_skill_files_exist_and_are_non_empty`
- assert each local skill path contains `SKILL.md`.

`test_vendored_skill_digests_match_manifest`
- compute a deterministic tree digest over relative path + bytes for each vendored bundle.
- assert exact equality with `content_digest` in the manifest.

`test_existing_project_skills_are_not_overwritten`
- assert the pre-existing GTA6 skill ids and `human.presentation.action-first` remain outside the imported-id set.

`test_teach_and_handoff_remain_explicit`
- assert their upstream frontmatter contains `disable-model-invocation: true` or the manifest enforces equivalent explicit invocation.

- [ ] **Step 2: Verify RED**

Run:
`pytest -q tests/test_agent_skill_pack_contracts.py`

Expected: FAIL because vendored bundles and digests are absent.

- [ ] **Step 3: Implement the sync/import script**

Implement:

`sync_skill(source_repo: str, source_commit: str, source_path: str, destination: Path) -> str`

The script must:
- clone/fetch into an external tooling/cache directory, never into Termux-specific paths;
- checkout the exact detached commit;
- copy only the manifest-approved bundle;
- preserve relative support files needed by that skill;
- refuse a dirty source checkout;
- calculate and print the deterministic SHA-256 tree digest;
- never run third-party install hooks or executables.

Import exact pinned bundles:
- `mattpocock/skills/skills/engineering/tdd` -> `.dsh/skills/tdd`
- `mattpocock/skills/skills/productivity/teach` -> `.dsh/skills/teach`
- `mattpocock/skills/skills/productivity/handoff` -> `.dsh/skills/handoff`
- `JuliusBrussee/caveman/skills/caveman` -> `.dsh/skills/caveman`
- `genmedia-labs/skills/video-edit` -> `.dsh/skills/video-edit`

Do not import Caveman proxy/runtime directories.

- [ ] **Step 4: Record exact local digests in the manifest**

Update only `content_digest` and materialized file-set metadata after the pinned import.

- [ ] **Step 5: Verify GREEN**

Run:
`pytest -q tests/test_agent_skill_pack_contracts.py`

Expected: PASS including digest verification.

- [ ] **Step 6: Commit**

```bash
git add .dsh/skills/tdd .dsh/skills/teach .dsh/skills/handoff .dsh/skills/caveman .dsh/skills/video-edit config/agent_skill_pack_v1.json scripts/agent-tooling/sync_agent_skill_pack.py tests/test_agent_skill_pack_contracts.py
git commit -m "feat(skills): vendor pinned requested skill bundles"
```

---

### Task 3: Add the pinned Superpowers DSH provider without global bootstrap

**Files:**
- Create: `scripts/agent-tooling/bootstrap_dsh_skill_pack.sh`
- Create: `scripts/agent-tooling/prove_superpowers_provider.mjs`
- Modify: `.github/workflows/deepseek-harness.yml`
- Modify: `tests/test_agent_skill_pack_contracts.py`

**Interfaces:**
- Consumes: Task 1 manifest, DSH `0.1.7-rc.2`, and pinned `LayneChai/superpowers-dsh`.
- Produces: a headless-profile provider installation plus proof JSON under `runtime/deepseek-harness-native/skill-pack/`.

- [ ] **Step 1: Add failing bootstrap/provider tests**

Add static tests asserting:
- bootstrap reads the pin from the manifest rather than a floating branch;
- bootstrap never installs Caveman proxy/runtime;
- no command enables a global Superpowers bootstrap;
- DeepSeek workflow includes the deterministic skill-pack bootstrap before resolved-config proof.

- [ ] **Step 2: Verify RED**

Run:
`pytest -q tests/test_agent_skill_pack_contracts.py`

Expected: FAIL because bootstrap/provider proof do not exist.

- [ ] **Step 3: Implement `bootstrap_dsh_skill_pack.sh`**

The script must:
- run only on Linux cloud/CI, not Termux;
- clone/fetch `LayneChai/superpowers-dsh` at the exact manifest SHA into the external tooling root;
- verify detached HEAD equals the pin and checkout is clean;
- install that local pinned checkout with the current DSH profile using `dsh plugin --profile <profile> add <local-path>`;
- never use `latest` or an unpinned npm package;
- never inject a session-start/global bootstrap;
- print `SUPERPOWERS_PROVIDER_INSTALL=PASS` only after plugin listing confirms it.

- [ ] **Step 4: Implement provider proof**

`prove_superpowers_provider.mjs` must import the pinned local provider module, register it into a minimal captured `ctx.skills.registerProvider` test context, and assert that the standard Superpowers skill catalog is non-empty and contains at least:

`using-superpowers`, `brainstorming`, `writing-plans`, `executing-plans`, `test-driven-development`, `systematic-debugging`, and `verification-before-completion`.

Write proof fields:
- provider_id
- source_commit
- discovered_skill_ids
- bootstrap_global=false
- authority=NONE
- status=PASS

- [ ] **Step 5: Wire the native DSH workflow**

In `.github/workflows/deepseek-harness.yml`:
- add the skill-pack manifest/scripts/skills to path triggers;
- run `bootstrap_dsh_skill_pack.sh headless` after DSH/pnpm setup;
- run `prove_superpowers_provider.mjs`;
- require `superpowers-dsh` in plugin list/resolved config;
- emit `SUPERPOWERS_PROVIDER_LOADED=PASS` and `SUPERPOWERS_BOOTSTRAP_GLOBAL=OFF`;
- upload skill-pack proof with existing native Harness evidence.

- [ ] **Step 6: Run focused tests**

Run:
`pytest -q tests/test_agent_skill_pack_contracts.py tests/test_deepseek_harness.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/agent-tooling/bootstrap_dsh_skill_pack.sh scripts/agent-tooling/prove_superpowers_provider.mjs .github/workflows/deepseek-harness.yml tests/test_agent_skill_pack_contracts.py
git commit -m "feat(dsh): load pinned superpowers skill provider"
```

---

### Task 4: Inventory the skill pack without promoting skills to capabilities

**Files:**
- Modify: `scripts/audit_harness_ecosystem.py`
- Modify: `.github/workflows/system-agent-inventory.yml`
- Modify: `tests/test_harness_ecosystem_inventory.py`
- Modify: `tests/test_agent_skill_pack_contracts.py`

**Interfaces:**
- Consumes: Task 1 manifest and Task 2/3 local/provider discovery evidence.
- Produces: skill identities in the ecosystem inventory with `ROLE=SKILL` or `SUPPORT_COMPONENT`, authority NONE, and no additional control plane.

- [ ] **Step 1: Add failing inventory tests**

Add assertions that:
- the six requested ids are present in a dedicated `agent_skill_pack` inventory section;
- every imported skill has authority `NONE`;
- no imported skill appears as an executable CapabilityRecord solely because it is installed;
- `CONTROL_PLANE_COUNT == 1`;
- `CONTROL_PLANE_IDS == ["deepseek-harness"]`;
- existing native DSH agent count remains unchanged.

- [ ] **Step 2: Verify RED**

Run:
`pytest -q tests/test_harness_ecosystem_inventory.py tests/test_agent_skill_pack_contracts.py`

Expected: FAIL because inventory has no skill-pack section.

- [ ] **Step 3: Extend ecosystem audit**

Read the canonical manifest and add a separate skill/provider-support identity section. Do not register these rows into `GLOBAL_CAPABILITY_REGISTRY`.

Each identity must report:
- skill id
- kind
- source repo/commit/path
- content digest or provider id
- authority NONE
- direct_external_side_effects false
- bootstrap policy
- discoverability/provenance status.

- [ ] **Step 4: Extend System Agent Inventory workflow**

Add path triggers for:
- `config/agent_skill_pack_v1.json`
- `.dsh/skills/tdd/**`
- `.dsh/skills/teach/**`
- `.dsh/skills/handoff/**`
- `.dsh/skills/caveman/**`
- `.dsh/skills/video-edit/**`
- `scripts/agent-tooling/agent_skill_pack.py`

Add fail-closed assertions for:
- `REQUESTED_SKILLS_DISCOVERED=PASS`
- `HARNESS_AUTHORITY_PRESERVED=PASS`
- `CONTROL_PLANE_COUNT=1`
- `NO_DIRECT_EXECUTION_BYPASS=PASS`
- `PINNED_PROVENANCE=PASS`
- `CONTENT_DIGEST_VERIFIED=PASS`.

- [ ] **Step 5: Verify GREEN**

Run:
`pytest -q tests/test_harness_ecosystem_inventory.py tests/test_agent_skill_pack_contracts.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/audit_harness_ecosystem.py .github/workflows/system-agent-inventory.yml tests/test_harness_ecosystem_inventory.py tests/test_agent_skill_pack_contracts.py
git commit -m "feat(harness): inventory governed external skills"
```

---

### Task 5: Negative authority/side-effect gates and branch-level verification

**Files:**
- Modify: `tests/test_agent_skill_pack_contracts.py`
- Modify: `.github/workflows/deepseek-harness.yml`
- Modify: `.github/workflows/system-agent-inventory.yml`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: final acceptance proof for the isolated integration branch.

- [ ] **Step 1: Add negative tests**

Add:

`test_video_edit_installation_grants_no_external_execution`
- assert installation alone creates no executable capability/provider route for RunComfy.

`test_teach_installation_grants_no_workspace_write`
- assert Teach has no write scope or Harness authorization merely from discovery.

`test_caveman_cannot_transform_canonical_artifacts`
- assert Caveman is not on any canonical result/receipt serialization path and has no executable capability registration.

`test_handoff_is_not_a_durable_checkpoint_capability`
- assert Handoff does not appear as a durable state/checkpoint executor.

`test_imported_skills_cannot_claim_harness_authority`
- mutate fixture authority to `DEEPSEEK_HARNESS` and assert validation fails.

`test_unpinned_or_drifted_source_fails_closed`
- mutate source pin/digest and assert verification fails.

- [ ] **Step 2: Run the negative tests**

Run:
`pytest -q tests/test_agent_skill_pack_contracts.py`

Expected: PASS only after Tasks 1-4 are complete.

- [ ] **Step 3: Run the focused integration matrix**

Run:
```bash
pytest -q   tests/test_agent_skill_pack_contracts.py   tests/test_harness_ecosystem_inventory.py   tests/test_deepseek_harness.py   tests/test_native_capability_boundaries.py   tests/test_system_synergy_service.py
```

Expected: PASS.

- [ ] **Step 4: Run existing inventory and DSH proof workflows on the isolated branch**

Dispatch or push the isolated branch with workflow triggers adjusted for branch testing, without dispatching Production.

Acceptance evidence must include:
- `SUPERPOWERS_PROVIDER_LOADED=PASS`
- `REQUESTED_SKILLS_DISCOVERED=PASS`
- `TDD_DISCOVERED=PASS`
- `TEACH_DISCOVERED=PASS`
- `CAVEMAN_DISCOVERED=PASS`
- `HANDOFF_DISCOVERED=PASS`
- `VIDEO_EDIT_DISCOVERED=PASS`
- `SUPERPOWERS_BOOTSTRAP_GLOBAL=OFF`
- `HARNESS_AUTHORITY_PRESERVED=PASS`
- `CONTROL_PLANE_COUNT=1`
- `NO_DIRECT_EXECUTION_BYPASS=PASS`
- `NO_DIRECT_EXTERNAL_SIDE_EFFECT=PASS`
- `PINNED_PROVENANCE=PASS`
- `CONTENT_DIGEST_VERIFIED=PASS`
- `SYSTEM_AGENT_INVENTORY_COHERENT=PASS`
- `EXISTING_DSH_SKILLS_UNCHANGED=PASS`.

- [ ] **Step 5: Compare against the target branch**

Verify the integration branch changes only the skill-pack scope plus its proofs/docs. Record any pre-existing CI failure separately; do not claim the whole repository is green if unrelated CI remains failing.

- [ ] **Step 6: Commit final proof adjustments if needed**

```bash
git add tests/test_agent_skill_pack_contracts.py .github/workflows/deepseek-harness.yml .github/workflows/system-agent-inventory.yml
git commit -m "test(skills): prove governed skill pack boundaries"
```

- [ ] **Step 7: Integration gate**

Only after all focused acceptance proofs are green:
- fast-forward/rebase safely onto the refreshed `work/gate6f-analytics-learning` HEAD if needed;
- preserve concurrent legitimate work;
- no reset;
- no force-push;
- do not dispatch Production as part of this integration.
