# BR-no-GTA: four developer tools (isolated, opt-in)

Authority: DeepSeek Harness only. This branch does not change main, V24, voice gates, or Hazewave.

## Preflight and local packages
Run only in existing BR-no-GTA Codespace on branch `work/br-devtools-four-isolated-v1`:
```bash
bash scripts/install_br_devtools_four.sh
```
This installs pinned local npm packages under ignored/untracked `.local/devtools-four`. Do not commit node_modules or credentials. This does not activate Claude Code plugins, deploy applications, create databases, or start agents. Verify local package versions and tool discovery before marking complete.

## Supabase MCP
Official remote endpoint: `https://mcp.supabase.com/mcp?read_only=true`. Configure in the existing MCP client with OAuth and least privilege. Do not connect a production project or allow SQL writes, migrations, or account-management tools. With no Supabase account/project authentication, status is **NOT CONNECTED**, not PASS. Project scoping is `project_ref` only when an authorized project exists.

## Vercel MCP
Official remote endpoint: `https://mcp.vercel.com`. Connect via the existing MCP client's OAuth flow, read documentation and inspect only. Never deploy or create a Vercel project as part of installation. Without authenticated handshake, status **NOT CONNECTED**.

## Chrome DevTools MCP
Pinned local package: `chrome-devtools-mcp@1.10.1`; requires Node 22 and a compatible Chrome/Chromium. The installed binary is `.local/devtools-four/node_modules/.bin/chrome-devtools-mcp`. Start with `--headless --isolated` under an existing MCP client. Verify initialize, tools/list, page navigation, console/network and screenshots on a local or public non-sensitive page. Never expose Chrome's debugging port publicly. Without a browser/handshake, status **NOT VERIFIED**.

## oh-my-claudecode
Pinned CLI package: `oh-my-claude-sisyphus@5.4.0`; CLI install is not the Claude Code plugin. Claude Code marketplace installation is a separate interactive step and must remain disabled until authority and hooks are reviewed against AGENTS.md. Do not enable automatic teams, background loops or new authority. Without a Claude Code plugin activation test, status **NOT VERIFIED**.

## Acceptance evidence
Capture exact git SHA, clean worktree, Node/npm versions, npm install output, package versions, MCP initialize/tools-list results, Chrome screenshots, and Claude Code plugin listing. Do not mark 4/4 without all four operational handshakes and permission checks. Never log credentials. Do not alter Telegram, owner-voice ledger, Qwen identity thresholds or YouTube publishing.
