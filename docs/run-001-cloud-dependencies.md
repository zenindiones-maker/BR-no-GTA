# RUN-001 cloud integration — #3 / #5

Base: ee36abb. PR #4 inspected at 3329572: no file diff.
Authority remains DeepSeek -> Harness -> GTA6 Brain -> Capability -> Worker -> Evidence/Result.
Worker never calls a model, database, scheduler or publisher.

## Implementation awaiting integration and real cloud evidence

- Existing EditPlan.from_dict and vendored VEdit Store/render API; no second editor.
- Source windows cannot be silently truncated; transitions cannot retime the plan.
- One MP4 under execution_id/render_job_id/video_id.mp4; existing outputs rejected.
- QA requires MP4, video, audio, finite duration within 1% (minimum 0.5 seconds)
  of the job and EditQA bounds, followed by full FFmpeg decode.
- Success artifact only after QA PASS; failure artifact contains only structured QA.
- Direct Python 3.12 Store/render import uses stdlib modules of vendored VEdit;
  UI/MCP/transcription dependencies are not required for that execution path.
- Validation workflow patches remain scoped to Python 3.11/MCP tests. WhisperX
  artifacts are unchanged; no second transcription implemented.

## Dependencies to register in #2/#4

| Missing item | Producer | Work consumer | Expected format | Impact |
|---|---|---|---|---|
| render_job_id | Application serializer | Validation/manifest | Positive persisted integer; resolve existing id naming | Identity not finalized |
| edit_plan propagation | Application pipeline | EditPlan.from_dict/VEdit | Existing version 1 complete serialization | Scenes alone cannot render |
| Recoverable artifact reference and media mapping | Media Worker + application | Cloud provisioning | Repository/run/artifact identity, integrity, relative media_path mapping; transport schema supplied by #2 | Retrieval blocked; no fields invented |
| Clip/scene lineage | Application | Worker validation | segment_id/content_unit_id/windows/transcript_words preserved | Cross-validation awaits final schema |
| Authorized canary and A/B jobs | Harness/Capability | workflow_dispatch | Complete jobs with real video/audio, 30–60 s / ~1500 s / ~1500 s | Real acceptance blocked |
| QA consumption | Application artifact consumer/publication gate | Manifest + QA result | Require PASS and matching identities | Work does not alter publisher |

Assets currently must be provisioned under runtime/media-worker/artifact with confined
relative paths. This is an unresolved integration boundary, not a new remote transport
schema. The workflow cannot currently provision those assets and is NOT production ready.

The worker's minimum validation follows the explicit Work mission; it does not finalize
the Codex contract. Authorization strings check consistency, not cryptographic proof of
Harness authorization. Final application/dispatch authority remains upstream.

## Evidence and remaining gates

Seven unittest cases check parsing, missing fields, authorization/lineage mismatch,
unsafe/missing assets, original VEdit timeline mapping, source overflow, QA, manifest,
independent outputs and decode failure. Media operations are mocked; no real canary claimed.

Engine workflow 34615698838 at ee36abb succeeded; this is not new worker/RUN-001 proof.
Before completion: finalize #2/#4, integrate retrieval, execute authorized real canary,
retrieve and verify its artifact, then repeat for A and B. Keep #3/#5 open.

## Worker hardening after 48e321b

- Malformed probe durations produce structured FAIL; decode failure is an explicit check.
- QA carries execution/video/job identities; MP4 count and size are checked.
- Successful manifests include a streaming SHA-256 digest for artifact verification.
- Asset resolution is injectable in the adapter; default remains confined, provisioned
  files only. No cloud transport or contract fields were invented.
- Dispatch validation and absent provisioning produce recoverable failure QA before
  installing FFmpeg. The provisioning check must follow the official retrieval step
  once #4 defines it; it is intentionally blocking today.
- Added cloud-only synthetic integration test: two short independent renders through
  the same execute() / VEdit / FFmpeg / ffprobe / decode path. This is technical test
  coverage, never authorized canary evidence. Its Actions result is still pending.

## Evidence ledger — synthetic technical integration

- Commit: 093796ac6e212b0bda92a814c74d33df4441d115.
- Workflow: cloud-worker-tests.yml; run: 34641276302; job: 103401249622.
- Link: https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/34641276302
- Result: SUCCESS, eight tests executed, including two synthetic 2-second renders
  through execute(), VEdit, FFmpeg, ffprobe and full-decode QA.
- Test identities: synthetic-test-1 / render_job_id 1 / video_id 1 and
  synthetic-test-2 / render_job_id 2 / video_id 2.
- No artifacts uploaded by that revision; sizes/hashes not retained in its logs.
  This proves technical rendering only, NOT artifact recovery or a real canary.
- Next revision retains test bundles and verifies their download on a separate
  GitHub-hosted job, including SHA-256, sizes, stream metadata and matching lineage.
  Recovery validation remains pending its own Actions run.

## Recovery evidence and final review

Run 34641514457 at ac78e637db2c696b990a60a80728f863162f287f passed both
worker-integration (103402123440) and recover-test-artifact (103402269461).
Artifact 10280540842, synthetic-worker-test-34641514457-1, 240305 bytes,
was recovered and verified on a separate runner. Retention ends 2026-09-18.
Ledger: https://github.com/zenindiones-maker/BR-no-GTA/pull/5#issuecomment-5639925507

Final review found incomplete lineage in QA/probe. The follow-up preserves all
eight existing identity/authorization fields in QA and probe.lineage and checks
them after artifact recovery. Unit tests cover timeline failure, partial engine
failure, probe failure and missing-audio QA failure: each leaves FAIL evidence
and no success manifest. Cloud verification of this follow-up remains pending.

No workflow references master_50min.mp4. Existing output directories are rejected
without overwrite; a GitHub Actions rerun uses a fresh checkout and failure
artifacts are distinguished by run ID / attempt. Worker determinism means
executing supplied plans without editorial choices, not bit-identical encoding
across different FFmpeg/OS versions.

Once this follow-up passes: READY FOR CANARY INPUT. Required from #2/#4 only:
authorized 30–60-second RenderJob, full existing edit_plan propagated in that job,
and official cloud-to-cloud video/audio asset references plus retrieval mapping.
No successful synthetic test is an authorized canary or a long-video acceptance.
