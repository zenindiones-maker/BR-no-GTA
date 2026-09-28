import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.env.BR_DSH_SKILL_FILESYSTEM_MODULE;
if (!modulePath) {
  throw new Error("BR_DSH_SKILL_FILESYSTEM_MODULE is required");
}

const skillFilesystem = await import(pathToFileURL(modulePath).href);
if (typeof skillFilesystem.FileSystemSkillProvider !== "function") {
  throw new Error("DSH filesystem provider class is unavailable");
}

const abortController = new AbortController();
const warnings = [];
const ctx = {
  get(name) {
    if (name === "fs") return undefined;
    return undefined;
  },
  logger: {
    warn(message) {
      warnings.push(String(message));
    },
    debug() {},
    info() {},
    error() {},
  },
};

const control = {
  signal: abortController.signal,
  invalidate() {},
};

const provider = new skillFilesystem.FileSystemSkillProvider(
  ctx,
  control,
  {
    watch: false,
    includeDefaultRoots: true,
  },
);

const required = ["tdd", "teach", "caveman", "handoff", "video-edit"].sort();
const expectedInvocation = {
  tdd: { modelInvocable: true, userInvocable: true },
  teach: { modelInvocable: false, userInvocable: true },
  caveman: { modelInvocable: true, userInvocable: true },
  handoff: { modelInvocable: false, userInvocable: true },
  "video-edit": { modelInvocable: true, userInvocable: true },
};
const listed = await provider.list({
  cwd: process.cwd(),
  signal: abortController.signal,
});
const candidates = Array.isArray(listed) ? listed : listed.candidates;
if (!Array.isArray(candidates)) {
  throw new Error("DSH filesystem provider returned an invalid catalog");
}

const projectCandidates = candidates.filter(
  (candidate) => candidate.source === "project-dsh",
);
const byName = new Map();
for (const candidate of projectCandidates) {
  if (!byName.has(candidate.name)) byName.set(candidate.name, []);
  byName.get(candidate.name).push(candidate);
}

const proofs = [];
for (const skillId of required) {
  const matches = byName.get(skillId) ?? [];
  if (matches.length !== 1) {
    throw new Error(
      `Expected one native DSH project skill for ${skillId}; found ${matches.length}`,
    );
  }

  const candidate = matches[0];
  const definition = await provider.get(candidate, {
    cwd: process.cwd(),
    signal: abortController.signal,
  });
  if (!definition || !String(definition.content ?? "").trim()) {
    throw new Error(`DSH failed to load non-empty skill body: ${skillId}`);
  }
  if (candidate.provider !== "filesystem") {
    throw new Error(
      `Unexpected DSH provider for ${skillId}: ${candidate.provider}`,
    );
  }
  if (candidate.rank !== 100) {
    throw new Error(
      `Unexpected project-dsh rank for ${skillId}: ${candidate.rank}`,
    );
  }

  const expectedFragment = [
    ".dsh",
    "skills",
    skillId,
    "SKILL.md",
  ].join(sep);
  const resolvedPath = resolve(String(candidate.path));
  if (!resolvedPath.endsWith(expectedFragment)) {
    throw new Error(
      `Unexpected DSH skill path for ${skillId}: ${resolvedPath}`,
    );
  }

  const modelInvocable = definition.invocation?.modelInvocable !== false;
  const userInvocable = definition.invocation?.userInvocable !== false;
  const expected = expectedInvocation[skillId];
  if (
    modelInvocable !== expected.modelInvocable ||
    userInvocable !== expected.userInvocable
  ) {
    throw new Error(
      `Invocation policy mismatch for ${skillId}: ` +
        `model=${modelInvocable} user=${userInvocable}`,
    );
  }

  proofs.push({
    skill_id: skillId,
    provider: candidate.provider,
    source: candidate.source,
    rank: candidate.rank,
    path: resolvedPath,
    model_invocable: modelInvocable,
    user_invocable: userInvocable,
    content_non_empty: true,
  });
}

const discovered = proofs.map((item) => item.skill_id).sort();
if (JSON.stringify(discovered) !== JSON.stringify(required)) {
  throw new Error(
    `Native DSH discovery mismatch: expected=${required} actual=${discovered}`,
  );
}

await provider.dispose();
abortController.abort();

const report = {
  schema_version: 1,
  status: "PASS",
  provider_package: "@deepseek-ai/dsh-skill-filesystem",
  provider_version: process.env.DSH_VERSION ?? null,
  project_root: process.cwd(),
  requested_local_skill_ids: required,
  discovered_local_skill_ids: discovered,
  proofs,
  warnings,
  authority: "NONE",
  control_plane: "DEEPSEEK_HARNESS",
};

const outputDir = join(
  process.cwd(),
  "runtime",
  "deepseek-harness-native",
  "skill-pack",
);
await mkdir(outputDir, { recursive: true });
await writeFile(
  join(outputDir, "dsh-local-skill-discovery.json"),
  JSON.stringify(report, null, 2) + "\n",
  "utf8",
);

console.log(`DSH_LOCAL_SKILLS_DISCOVERED=${discovered.length}`);
for (const skillId of discovered) {
  console.log(`${skillId.toUpperCase().replaceAll("-", "_")}_DSH_DISCOVERED=PASS`);
}
console.log("REQUESTED_LOCAL_SKILLS_DSH_DISCOVERY=PASS");
console.log("SKILL_INVOCATION_POLICY_NATIVE=PASS");
