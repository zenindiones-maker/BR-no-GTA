# RELEASE_ARTIFACT_PROVENANCE_V1

This is a follow-up control for release artifacts, not a source promotion gate.

Apply provenance and verification when BR-no-GTA produces distributable software artifacts, including:

- binaries;
- packages;
- build manifests;
- release bundles or other software release artifacts.

The implementation should bind the artifact digest, source revision, build inputs, builder identity, and verification policy, and should produce attestations only where downstream verification is actually consumed.

Security source promotion does not generate placeholder attestations merely to improve a score. A future bounded tranche should implement and consume RELEASE_ARTIFACT_PROVENANCE_V1 for real release artifacts.
