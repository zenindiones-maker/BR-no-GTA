# Hermes Agent upstream boundary

HERMES_UPSTREAM_REPOSITORY=https://github.com/NousResearch/hermes-agent

HERMES_UPSTREAM_COMMIT=9eca7f388f71755293343dddd6ec4d9111d68fc4

HERMES_UPSTREAM_VERSION=0.21.3

HERMES_CORE_LICENSE=MIT

## Integration decision

BR-no-GTA does not vendor the Hermes repository. GitHub Actions resolves the exact commit from `UPSTREAM.lock`, uses a bounded sparse checkout/cache for the Kanban/profile runtime surfaces, and rejects a moving `main`.

Only the MIT-licensed core collaboration runtime is integrated. No optional Hermes skill, provider plugin, messaging gateway, scheduler, memory system, or bundled third-party skill is copied into BR-no-GTA. Any future optional module requires a separate license/security review before it can become reachable.

## Authority boundary

Hermes is a durable collaboration runtime **under** the DeepSeek Harness.

```
Human / Telegram
  -> DeepSeek Harness
  -> Routing / Policy / Authorization
  -> CollaborationPlan
  -> Hermes board / profiles / handoffs / review lifecycle
  -> structured evidence
  -> DeepSeek Harness CanonicalExecutionResult
  -> Learning Plane
```

Hermes is never a second Harness, Brain, Global Capability Registry, Learning Plane, canonical memory, sovereign scheduler, publisher, or policy authority.

AUTHORITY=DELEGATED_ONLY

The BR registry remains canonical for capability, agent, skill, action, security boundary, executor binding, and evidence contract. Hermes profile identities are projections of already-routed collaboration tasks, not a second capability catalog.

## Runtime boundary

Default Hermes workers receive only:

- Kanban coordination state;
- bounded mission/task context;
- BR Harness request/status/evidence tools.

They do **not** receive direct authority to invoke GitHub mutation, shell, filesystem mutation, credentials, public YouTube publication, rendering, providers, or BR database mutation. Where BR already has a Harness boundary, a Hermes worker requests that boundary instead of calling the executor directly.

The mission-level deny set always includes:

- push;
- merge;
- canonical_branch_write;
- policy_mutation;
- authority_mutation;
- secret_access;
- credential_access;
- youtube_publish_public;
- external_paid_action.

Public publication remains gated by `br_youtube_pode_postar` and explicit human authority.

## Coexistence

Agent Office / Munder remains the bounded DEVELOPMENT runtime for Codex/worktree engineering. Hermes coordinates cross-domain missions; engineering tasks that need Agent Office are routed back through the Harness.

TelegramConversationState, Knowledge Brain, Learning Plane, and Hermes Kanban state are distinct layers. Hermes board state is disposable/subordinate execution state; canonical evidence is exported back into BR-no-GTA after each mission.
