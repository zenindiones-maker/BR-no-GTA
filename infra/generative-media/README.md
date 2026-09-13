# Gate 5B isolated generative-media runtimes

These runtimes remain subordinate to DeepSeek Harness.

Runtime state lives only under `.runtime/generative-media/` and is ignored by Git.
No model weights are downloaded by the bootstrap scripts in this directory.

## Governance

Harness -> Registry -> Routing/Policy -> provider/model/executor ->
persisted HarnessAuthorization -> bounded executor -> isolated runtime ->
artifact validation -> evidence/result -> Harness.

Installation success does not promote capability maturity or Registry availability.

## Supply-chain boundary

Source repositories and model repositories use separate immutable revisions.
Hunyuan's upstream `requirements.txt` contains an unpinned Git dependency for
OpenAI CLIP. The bootstrap rewrites only that dependency to the audited
`openai/CLIP` commit recorded in `runtime-pins.toml`.

ACE-Step is installed with `uv sync --frozen` from its pinned source commit,
using its committed lockfile. It is never installed into the BR main `.venv`.

Model download is intentionally a separate manual gate. No script here invokes
`huggingface-cli download`, `acestep-download`, or any generation command.
