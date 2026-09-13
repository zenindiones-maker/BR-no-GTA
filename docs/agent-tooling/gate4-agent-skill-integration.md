# Gate 4 — Governed Agent / Skill Integration

DeepSeek Harness remains the sole authority. The Global Capability Registry is metadata-only; Harness Routing/Policy selects one eligible implementation before HarnessAuthorization is issued.

## Active-baseline inventory

| Agent/skill | Type | Capability | Actions | Executor | Status |
|---|---|---|---|---|---|
| gta6-research | SKILL | gta6.research | RESEARCH | gta6_research_pipeline.run_gta6_research | FUNCTIONAL |
| gta6-editorial | SKILL | editorial.process | EDITORIAL | editorial_queue_consumer.process_next_editorial_queue_item | FUNCTIONAL |
| gta6-fact-check | SKILL | gta6.fact-check | RESEARCH, EDITORIAL | none | UNKNOWN/UNPROVEN |
| gta6-production | SKILL | production.plan | EXECUTION | production_plan_service | FUNCTIONAL |
| gta6-youtube | SKILL | youtube.upload-private | YOUTUBE | youtube_publication_orchestration | FUNCTIONAL |
| gta6-youtube | SKILL | youtube.publish-public | PUBLICATION | make_youtube_publication_public | PROVEN |
| Codex + Addy (24 pinned skills) | SKILL | addy:<skill> | DEVELOPMENT | execute_codex_addy_capability | FUNCTIONAL / bounded |
| Higgsfield selected capabilities | PROVIDER metadata | higgsfield-* | varies | none | BLOCKED — unattended authentication not proven |
| TUBEGENT | AGENT metadata | tubegent | none | none | UNKNOWN/UNPROVEN — absent from active baseline integration |

Only the selected Addy skill identifier is passed into the disposable read-only Codex snapshot. Skill bodies are not injected by Registry discovery or routing metadata.

## Routing and authorization

1. Harness receives intent/requested action.
2. Global Capability Registry supplies compact metadata.
3. Harness Routing/Policy filters availability, action, domain, security and executor requirements and selects exactly one capability implementation.
4. Only then does the Harness issue persisted HarnessAuthorization for `capability:<id>`.
5. The bounded executor validates the selected capability/action/executor binding and returns existing CapabilityEvidence.
6. No eligible implementation fails closed. BLOCKED/UNKNOWN records are never auto-promoted. Fallback remains policy-explicit and observable.

## Side-effect matrix

| Side effect | Agent/skill | Required action | Authorization boundary | Result/evidence |
|---|---|---|---|---|
| Research persistence | gta6-research | RESEARCH | Harness action/capability path | research result + source lineage |
| Editorial state mutation | gta6-editorial | EDITORIAL | Harness-routed provider + official consumer | editorial consumer result |
| Script persistence | native production services | EDITORIAL / EXECUTION | official production boundary | script/content lineage |
| Production-plan persistence | gta6-production | EXECUTION | Harness execution flow | ProductionPlan lineage |
| Filesystem/subprocess in development | selected Addy skill | DEVELOPMENT | disposable tracked-files-only read-only Codex snapshot | CapabilityEvidence |
| External visual generation | Higgsfield | EXECUTION/YOUTUBE/EDITORIAL | unavailable until unattended auth is proven | BLOCKED routing evidence |
| Render dispatch/state transition | native render executor | EXECUTION | persisted Gate-1 EXECUTION authorization | RenderExecutionResult + job provenance |
| GitHub Actions dispatch | cloud executor | EXECUTION / DEVELOPMENT | Harness-governed dispatch provenance | workflow run identity/status/artifact |
| YouTube private upload | gta6-youtube | YOUTUBE | upload remains subordinate to Harness flow | publication record/provider result |
| YouTube public publication | gta6-youtube | PUBLICATION | explicit Gate-1 PUBLICATION authorization | publication state + Harness provenance |

## Guards

- GTA6 Brain remains recommendation/intelligence only.
- GTA6MasterAgent requires a Harness-routed provider and HarnessAuthorization for side effects.
- GTA6ActionDispatcher requires persisted HarnessAuthorization and does not fabricate IDs.
- Addy has no swarm or lateral agent autonomy.
- Higgsfield is not automatically selectable while BLOCKED.
- TUBEGENT remote history is not imported, merged or cherry-picked in Gate 4.
- Job18 is outside Gate 4 and must remain untouched.
