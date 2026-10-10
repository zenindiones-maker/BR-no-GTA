#!/usr/bin/env bash
set -euo pipefail
# BR-no-GTA: isolated developer-tool installer. Run INSIDE the existing Codespace.
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
[[ "$(git remote get-url origin)" == *"zenindiones-maker/BR-no-GTA"* ]] || { echo "REPOSITORY_MISMATCH"; exit 20; }
[[ "$(git branch --show-current)" == "work/br-devtools-four-isolated-v1" ]] || { echo "ISOLATED_BRANCH_REQUIRED"; exit 21; }
[[ -z "$(git status --porcelain)" ]] || { echo "DIRTY_WORKTREE_REFUSED"; exit 22; }
command -v node >/dev/null && command -v npm >/dev/null && command -v npx >/dev/null || { echo "NODE_NPM_REQUIRED"; exit 23; }
node -e 'if (+process.versions.node.split(".")[0]<22)process.exit(1)' || { echo "NODE_22_REQUIRED"; exit 24; }
mkdir -p .local/devtools-four
echo "INSTALLING_PINNED_BROWSER_MCP"
npm install --prefix .local/devtools-four --no-audit --no-fund --save-exact chrome-devtools-mcp@1.10.1
echo "INSTALLING_PINNED_OMC_CLI_NO_SETUP"
npm install --prefix .local/devtools-four --no-audit --no-fund --save-exact oh-my-claude-sisyphus@5.4.0
echo "VERIFYING_INSTALLED_PACKAGES"
node -e 'for(const p of ["chrome-devtools-mcp","oh-my-claude-sisyphus"]){const x=require("./.local/devtools-four/node_modules/"+p+"/package.json");console.log(p+"="+x.version)}'
echo "REMOTE_MCP_NOT_INSTALLED_LOCALLY: supabase=https://mcp.supabase.com/mcp?read_only=true"
echo "REMOTE_MCP_NOT_INSTALLED_LOCALLY: vercel=https://mcp.vercel.com (OAuth required)"
echo "CLAUDE_PLUGIN_NOT_ACTIVATED: install separately only after harness authorization"
echo "DEVTOOLS_INSTALL_LOCAL_PACKAGES=PASS"
