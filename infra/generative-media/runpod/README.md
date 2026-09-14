# Runpod Gate 5B worker boundary

Runpod is infrastructure only. DeepSeek Harness remains the only authority.

The application-side `RunpodGenerativeMediaRuntime` receives a request only after
Registry/routing/HarnessAuthorization validation. Its injected transport client may
use the authenticated Runpod MCP operationally, but the BR core does not import or
depend on Codex UI/MCP packages and does not store a Runpod API key.

`worker_once.py` is the bounded remote entrypoint. It accepts only the already
selected runtime payload plus the exact approved source/model revisions, rejects
revision drift, requires an NVIDIA GPU, invokes the existing isolated runtime, and
returns artifact/runtime provenance. It has no scheduler, publisher, database,
router, authorization issuer, or fallback logic.

Model weights are not downloaded by these files. The existing pinned materializer
remains a separate explicit gate before any real generation smoke.
