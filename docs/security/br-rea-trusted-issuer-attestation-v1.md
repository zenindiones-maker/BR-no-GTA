# BR-no-GTA | Narrow REA issuer attestation (P0 remediation, NOT production approval)

Date: 2026-10-10. Repository: `zenindiones-maker/BR-no-GTA`. Authority: DeepSeek Harness only. Work branch: `work/br-rea-investigation-harness-gate-v1`. No changes to ARTEX runtime or other subsystems' authorization protocols.

## Verified root cause
`app/services/harness_authorization_service.py:issue_harness_authorization()` can be imported and invoked by arbitrary in-process Python, and sets `issued_by="deepseek_harness"` as an ordinary string. Persistence and single-use protect replay, **not** the caller's identity. A SQLite row, status, or caller-supplied metadata alone must not grant security-sensitive REA source-reading authority.

## What changed (in isolated candidate)
The only new scoped capability, `reverse-engineering.evidence.inspect`, now additionally requires a **detached Ed25519 attestation** that cryptographically binds:
- `schema=BRReaTrustedIssuerAttestation/v1`, `purpose=one_shot_first_party_python_source_inspection`
- persisted `authorization_id`, `harness_decision_id`, `execution_id`, authorized action and subject
- exact ordered authorized source paths; issuance and expiry UTC seconds, maximum 120-second validity.

Verification happens **before** the atomic single-use SQLite consumption and before any filesystem reads. No trusted public key (`BR_REA_TRUSTED_ISSUER_PUBLIC_KEY_B64`), invalid encoding, mismatched key, changed path, forged signature, expired proof, or replay => **no source inspection**. Neither signing logic nor private keys are installed in this production verifier. The trust anchor must be controlled outside the caller's runtime identity, not simply be an environment variable it can rewrite.

### Residual blocker (production)
The CI harness uses a generated ephemeral **test-only** signer within the test process to prove the verifier's real cryptographic behavior and routed source-inspection E2E. It proves signature validation, fail-closed behavior and source routing **but not independent production principal identity**. Production cannot be marked trusted until a separately protected DeepSeek Harness issuer principal, private-key custody, independently provisioned trusted public key, process/UID isolation, permissions and audit/revocation/rotation procedures are implemented and independently reviewed. Untrusted code with write access to the public-key environment, runtime Python modules, or inspected source can still subvert this model; the operational separation has not been established. **There is deliberately no test-to-production fallback, credential embedded in repo, new always-on daemon or silent publisher**.

## Exact evidence
- [Run 38085727595](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38085727595) on exact SHA `23025225015b2b0bd65d6bd686e13385d9165e9c`: completed **SUCCESS**.
- 18/18 real adversarial filesystem/SQLite/cryptographic tests PASS, plus 17 Owner Voice reference-policy tests, 3 static system audit tests and real public MCP forged-call denial; `BR_REA_HARNESS_REAL_E2E=PASS`, `BR_REA_ACCEPTANCE=PASS`. The public MCP test asserts that no forged request inserts a persisted grant.
- Prior 14 tests were extended by 4 negative signed-issuer cases. Test signer is not a production trust authority.

## Primary technical references
- [PyCA cryptography Ed25519 verify](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/): signature verified with a public key; invalid signatures are rejected.
- [NIST SP 800-63B Replay Resistance](https://pages.nist.gov/800-63-4/sp800-63b/authenticators/): short-lived assertions and unique per-authorization IDs complement the atomic single-use update.
- [GitHub Actions security](https://docs.github.com/en/actions/reference/security/secure-use): minimal privileges and no persisted repository credentials.

## No-go boundaries
This is **not** permission to run third-party ARTEX agents, recover deleted REA V4 components, grant new agents credentials, change voice identity or release a YouTube video. Review PR #34 independently before promotion. Do not create or expose private keys on A15, do not repurpose an unrelated shared token or put key materials in logs.
