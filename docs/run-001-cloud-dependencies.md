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
