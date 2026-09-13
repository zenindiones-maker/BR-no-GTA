# Agent tooling — Linux/Codex

This is development tooling. Harness remains the sole authority; no production
capability, dispatcher action, database change, render or publication is added.
RUN-001 checkpoints remain in `.github/codex/run-001.txt` and the evidence ledger.

## Reconstruct an agent environment

Use Node 24, npm, Git, Python 3 and Linux (not Termux):

```sh
bash scripts/agent-tooling/bootstrap.sh all
export PATH="${XDG_DATA_HOME:-$HOME/.local/share}/br-agent-tooling/bin:$PATH"
python3 scripts/agent-tooling/check_discovery.py all
```

`BR_AGENT_TOOLING_ROOT` may override the package/source directory. If set, use
that directory's `bin` in PATH. Bootstrap adds it to GITHUB_PATH in Actions.
Start a new Codex session after installation. It discovers Addy through the
native plugin marketplace and Higgsfield through user-scoped agent skills.
The discovery check queries `skills/list` on Codex app-server without an LLM
turn, login or generation. It checks enabled skills and reads one selected skill.
This proves discovery/readability, not autonomous model selection quality.

Persistent Git state: bootstrap, exact revisions, governance, this document and
workflow definitions. On a persistent Linux agent, installed plugins/skills remain
in its user profile. On Actions, installation is reconstructed on each new runner;
no cache or downloadable installation artifact is required. An unrelated agent
workflow must call bootstrap before starting Codex; this does not claim that every
workflow in the repository already does so. No production workflow is changed.

## Revisions and compatibility

- Codex CLI: `0.154.0` (previously demonstrated by run `34719371222`).
- Higgsfield CLI: `1.1.24` (previous cloud validation preserved).
- Official companion installer: `skills@1.5.26`.
- Addy: `be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39`, plugin `0.6.9`.
  25 upstream skills; 24 in the Codex compatibility view. Only
  `browser-testing-with-devtools` is omitted, because its MCP is not configured.
- Higgsfield skills: `d071406147a37b835bed09543d85ab3e9bd85c7d`.
  Installer finds 8 skills (README badge/table says 9). Selected four:
  `higgsfield-generate`, `higgsfield-youtube-thumbnail`, `higgsfield-brandkit`,
  `higgsfield-video-explainer`.

Source repositories are checked out at exact SHAs. Addy is installed through
`codex plugin marketplace add <local compatibility view>` and
`codex plugin add agent-skills@agent-skills`, the upstream native mechanism.
The compatibility view retains companion references/scripts/assets and excludes
`hooks/`: its SessionStart hook injects the meta-router; this project uses native
progressive discovery instead. Original checkouts remain unchanged. Higgsfield
uses the official `skills add <pinned local checkout> --agent codex --global
--copy` mechanism, retaining complete selected directories. No blind vendoring of
`.agents/` or runtime copying is performed.

AVAILABLE != ACTIVE. Let native discovery choose relevant skills, or select a
single skill explicitly in a new Codex session. Never paste the entire catalogue
or `using-agent-skills` into an always-on prompt. Local governance and user/Harness
authorization prevail. No custom skill/router is necessary for this delta.

## Upstream review and boundaries

Reviewed native plugin/marketplace manifests, Codex installation instructions,
skill layouts and executable entry points. Addy includes Claude hooks, HTTP cache
helpers and local shell tests; these are not installed as Codex hooks. Higgsfield
includes creative-generation instructions and brandbook scripts invoking local
export tools; installing a skill does not authorize running these or paid jobs.
Do not follow upstream auto-update recommendations during bootstrap: changes to
pins require explicit review. This is a bounded integration review, not a claim
that every upstream instruction or dependency is harmless. npm's official
Higgsfield post-install downloads a release binary; failure must stop bootstrap.

## Authentication and credits

Bootstrap never logs in, prints a token, saves an auth artifact, or generates media.
For an authorized interactive Linux agent, use the official browser flow:

```sh
higgsfield auth login
```

Complete the browser step privately. Never upload the device prompt, tokens,
cookies, user profile or CLI credential files to Git or Actions artifacts. Do not
run a token-inspection command in CI. An authenticated read-only check is:

```sh
higgsfield account credits >/dev/null
```

Failure here can mean authentication, network or account failure; do not label
all failures as “needs login”. Use CLI help and private diagnostics to distinguish
them. No undocumented environment token or secret name is assumed. This change
does not configure unattended authenticated Higgsfield generation. For ephemeral
runners, an officially supported noninteractive credential mechanism must first
be confirmed before connecting an Actions Secret. Do not reuse Codex/ChatGPT auth
as Higgsfield auth. Never request a new login just to repeat installation tests.
Cost estimation and explicit task authorization precede any paid generation.

## Sources

- https://github.com/addyosmani/agent-skills/blob/be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39/docs/codex-setup.md
- https://github.com/higgsfield-ai/skills/tree/d071406147a37b835bed09543d85ab3e9bd85c7d
- https://github.com/higgsfield-ai/cli
