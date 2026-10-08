# BR-no-GTA — Native REA/Ghidra Reconstruction V9

Status: isolated development candidate, not promoted. REA 6.0.0 + Ghidra 12.1.4 + JDK21+ on ephemeral Linux x64 runner, owned synthetic original C ELF64 only.

## Research and provenance

- https://morluto.github.io/rea/get-started/
- https://morluto.github.io/rea/guides/native/
- https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/RuntimeScripts/support/analyzeHeadlessREADME.md
- https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build

Ghidra official archive: ghidra_12.1.4_PUBLIC_20260921.zip SHA256 ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db, verified before archive unpacking. No automatic upgrades, agent MCP registration, production changes, extra Codespace, new paid services or modification to BR_OWNER_V1, Telegram or A15.

## What must actually pass

1. Real compiler creates a reviewed original local ELF64 from the owner-authored C fixture.
2. DeepSeek Harness persistence authorizes one specific native analyzer via scoped owned file root, exact REA CLI and Ghidra provider.
3. Native provider-specific doctor must exit zero. The REA function CLI must produce JSON Evidence with actual ghidra provider identity and normalized result. Neither REA CLI nor Ghidra executes the target binary.
4. Separately written reconstruction fixture is independently compiled and executed by the differential CI ONLY on known synthetic fixtures. On 3205 deterministic paired inputs, original and candidate must output identical bytes; the intentionally defective candidate must differ. This is sampled behavioral correspondence, not autonomous code recovery nor formal equivalence.
5. Only function Evidence digest, provider version, structural fields, artifact hash, measured case count and error count appear in reporting. Raw pseudocode, decompiled source, binary, symbols, file paths and strings must not be forwarded to general agents.
6. No learning write, auto-routing change, publication or canonical promotion is attempted.

Any provider failure, missing receipt, rights violation or mismatch blocks the native readiness claim. Static function analysis and behavioral equivalence are two distinct gates.

## Remaining professional work

Expand to blinded and multi-version original fixtures, typed call graphs and xrefs, negative controls, fuzz/property tests, security-reviewed runtime instrumentation, original audiovisual file format tooling, and real REAPER/animation/voice benchmarks. Local Ghidra installation alone does not make optional native debuggers, REA MCP, or unrelated binaries safe or ready. A successful 3205-case synthetic proof is not proof of perfect cloning of real proprietary multimedia.


## Security-boundary follow-up (post functional CI)

The GitHub Actions host downloads required release assets and has not been tested as a network-egress-denied sandbox. Therefore, **do not treat this as safe to analyze untrusted native binaries or files containing secrets**. Current executable admission remains restricted to reviewed, synthetic, owner-compiled x86-64 ELF fixtures on ephemeral runners. In the native REA/Ghidra Python adapter, the subprocess receives a minimal environment whitelist rather than inherited cloud/GitHub credential variables, with a separate regression test. This reduces ambient-secret risk but does NOT prove process/network containment.

Before agent-access expansion or production promotion: conduct an independent Ghidra bridge security review; test network and process isolation, time/memory/child-process ownership, unsafe file paths and subprocess lifetime; attest source licenses and code provenance; verify runtime provider health on the exact dedicated workstation; measure randomized/blinded behavioral cases beyond the synthetic deterministic 3,205 case set. No auto-promotion, untrusted ELF execution, or generic agent access is allowed in V9.
