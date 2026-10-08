# BR-no-GTA — repository agent map

DeepSeek Harness is sole authority and reducer. Workers, GTA6 Brain, Hermes,
Agent Office, providers, tools and Skills are subordinate executors. A worker
may act only through a fresh Harness authorization and the bound task contract.

## Stable execution map

Human goal → DeepSeek Harness → typed atomic task → capability eligibility →
TaskExecutionBlueprint → bounded worker/environment → TaskResultEnvelope →
independent review when required → Harness reducer → durable mission state.

Multi-agent execution is not the default. Use task topology evidence. Sequential
or conflicting work uses no fanout. Mutating work requires an isolated Sprite or
git worktree; independent review is read-only and cannot mutate the candidate.

Skills have authority=NONE. They may refine procedure but cannot expand read,
write, tool or side-effect scope, publish, change mission state, write canonical
memory, or promote themselves.

Never expose secrets, login/device material, raw credentials, or private prompt
contents in repository artifacts, GitHub logs, Telegram review groups or traces.
OpenAI Platform API spend is forbidden unless the owner explicitly changes that
policy; Codex ChatGPT-subscription execution must not fall back to paid API.

## Canonical references

Required: `docs/operations/system-operational-readiness.html`
Required: `app/services/global_capability_registry.py`
Required: `app/services/harness_authorization_service.py`
Required: `app/services/task_execution_foundation_service.py`
See: `docs/architecture/br-no-gta-professionalization-master-plan-v1.md`
Required for long-running development: `docs/architecture/development-continuity-recovery-plane-v1.md`
See: `docs/agent-execution/gta6-agent-domain-guidance.md`
See: `docs/superpowers/specs/2026-09-28-agent-skills-pack-design.md`

The detailed GTA6 research/editorial/production guidance is versioned in the
referenced domain document rather than duplicated here. Repository contracts
and versioned policy override stale prose. Fail closed on conflicting authority
instructions or broken mandatory references.

## Single-human voice/release gates V11 (isolated candidate)

Follow docs/architecture/br-owner-voice-and-production-gates-v11.md. Single
BR_OWNER_V1 human reference from Telegram only; Qwen 1.7B Base serial calls,
private per-segment metrics and no reuse of rejected audio. Scratch
checkpoints are NOT cross-run durable. Real owner-certified voice then complete
20–25 minute professional render then private Telegram/YouTube owner approval.
No fallback voice, unattended delivery, canonical promotion, or invented PASS.


## V13 LLaMA-Factory controlled training-admission plane

Follow docs/architecture/br-llamafactory-harness-v13.md. LLaMA-Factory
(hiyouga/LlamaFactory, SHA ce9dc9e072f80fa3abe0989d4ab90da25f083438)
is an isolated research specialist for authorized original LLM/VLM textual
training datasets. Its source package/CLI metadata install does not prove
a complete operational ML training environment, GPU capacity, model quality
or canonical deployment. Only the DeepSeek Harness persisted RESEARCH route
can admit bounded owner-authored Alpaca datasets. GPU train, model downloads,
fallback cost, publication, untrusted datasets and cross-agent authority
remain forbidden without separate independent evidence and approval.

BR_OWNER_V1 human voice is explicitly OUT OF SCOPE for LLaMA-Factory:
Qwen3-TTS Base has its own official single-speaker training and private
identity/pronunciation gates. Never claim that a LLaMA-Factory dataset receipt
fixes voice identity or Telegram delivery. User-facing GPT-6 rich UI is a
ChatGPT feature and does not automatically mutate the repository.
