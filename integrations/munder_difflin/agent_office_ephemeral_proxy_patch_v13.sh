#!/usr/bin/env bash
set -euo pipefail
UPSTREAM_DIR="${1:?Usage: script <ephemeral-upstream-dir>}"
PIN="6248293a7cd9dfdbf9633d12bbe857831ccfee88"
PATCHED="2.0.8"
test -d "$UPSTREAM_DIR/.git"
test "$(git -C "$UPSTREAM_DIR" rev-parse HEAD)" = "$PIN"
test -z "$(git -C "$UPSTREAM_DIR" status --porcelain)"
pushd "$UPSTREAM_DIR" >/dev/null
# Upstream source and pin stay unchanged in Git; ephemeral lock is different.
npm pkg set "overrides.proxy-addr=$PATCHED"
npm install --package-lock-only --ignore-scripts --no-audit --no-fund
node <<'JS'
const fs=require("fs");
const manifest=JSON.parse(fs.readFileSync("package.json","utf8"));
if (manifest.overrides?.["proxy-addr"]!=="2.0.8") throw Error("PROXY_ADDR_OVERRIDE_NOT_PINNED");
const lock=JSON.parse(fs.readFileSync("package-lock.json","utf8"));
const matches=Object.entries(lock.packages||{})
    .filter(([p]) => p==="node_modules/proxy-addr" || p.endsWith("/node_modules/proxy-addr"));
if (!matches.length || matches.some(([,item])=>item.version!=="2.0.8"))
    throw Error("PROXY_ADDR_TRANSITIVE_PIN_NOT_APPLIED");
process.stdout.write("AGENT_OFFICE_PROXY_ADDR_LOCK_EXACT_2_0_8=PASS\n");
JS
npm ci --ignore-scripts --no-audit --no-fund
node <<'JS'
const fs=require("fs"),path=require("path");
const lock=JSON.parse(fs.readFileSync("package-lock.json","utf8"));
const rows=Object.entries(lock.packages||{})
    .filter(([p]) => p==="node_modules/proxy-addr" || p.endsWith("/node_modules/proxy-addr"));
for (const [name,rec] of rows) {
 const file=path.join(process.cwd(),name,"package.json");
 if (!fs.existsSync(file)) throw Error("PROXY_ADDR_INSTALLED_PATH_MISSING");
 if (JSON.parse(fs.readFileSync(file,"utf8")).version!==rec.version)
     throw Error("PROXY_ADDR_INSTALLED_VERSION_MISMATCH");
}
if (!rows.length) throw Error("PROXY_ADDR_PACKAGE_MISSING");
process.stdout.write("AGENT_OFFICE_PROXY_ADDR_INSTALLED_PATCHED=PASS\n");
JS
popd >/dev/null
echo "AGENT_OFFICE_UPSTREAM_PINNED_INPUT_UNCHANGED=TRUE"
echo "AGENT_OFFICE_UPSTREAM_EPHEMERAL_LOCK_OVERRIDDEN=TRUE"
echo "AGENT_OFFICE_CANONICAL_VENDOR_PATCH_NOT_ATTEMPTED=TRUE"
