import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const source = process.env.BR_SUPERPOWERS_DSH_SOURCE;
const sourceCommit = process.env.BR_SUPERPOWERS_DSH_COMMIT;
if (!source || !sourceCommit || !/^[0-9a-f]{40}$/.test(sourceCommit)) {
  throw new Error("Pinned Superpowers DSH source environment is missing");
}

const moduleUrl = pathToFileURL(join(source, "lib", "index.js")).href;
const superpowers = await import(moduleUrl);

let providerFactory = null;
const ctx = {
  skills: {
    registerProvider(factory) {
      providerFactory = factory;
      return factory;
    },
  },
};

superpowers.apply(ctx);
if (typeof providerFactory !== "function") {
  throw new Error("Superpowers DSH did not register a skill provider");
}

const provider = providerFactory({});
const candidates = await provider.list({});
const discovered = [...new Set(candidates.map((item) => item.name))].sort();
const required = [
  "using-superpowers",
  "brainstorming",
  "writing-plans",
  "executing-plans",
  "test-driven-development",
  "systematic-debugging",
  "verification-before-completion",
];

for (const skill of required) {
  if (!discovered.includes(skill)) {
    throw new Error(`Required Superpowers skill not discovered: ${skill}`);
  }
}

const report = {
  schema_version: 1,
  provider_id: "superpowers-dsh",
  source_commit: sourceCommit,
  discovered_skill_ids: discovered,
  bootstrap_global: false,
  authority: "NONE",
  routing_authority: "NONE",
  publication_authority: "NONE",
  direct_external_side_effects: false,
  status: "PASS",
};

const outputDir = join(
  process.cwd(),
  "runtime",
  "deepseek-harness-native",
  "skill-pack",
);
await mkdir(outputDir, { recursive: true });
await writeFile(
  join(outputDir, "superpowers-provider.json"),
  JSON.stringify(report, null, 2) + "\n",
  "utf8",
);

console.log(`SUPERPOWERS_PROVIDER_SKILLS=${discovered.length}`);
console.log("SUPERPOWERS_PROVIDER_LOADED=PASS");
console.log("SUPERPOWERS_BOOTSTRAP_GLOBAL=OFF");
