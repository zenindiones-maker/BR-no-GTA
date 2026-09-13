# RUN-001 real-media boundary

Base app: 445675f. Validated cloud history through 4320d13 is merged without
rewriting either branch. The old artifact-ID proposal is not part of this work.

## Composition and authority

`production_media_bridge.bind_selected_segments(plan, segment_ids)` consumes
already selected, persisted segments. IDs must correspond one-to-one to the
ordered production scenes; content item, script and idea must match. It refuses
timing changes rather than making a new editorial selection. The existing
production execution service invokes this bridge before creating VideoSpec.
A producer must therefore bind selected segment IDs before advancing to VIDEO.
Missing selections fail explicitly. MediaSelection remains metadata-only.

The existing Dispatcher supplies execution authorization. The existing render
request service exports the persisted queue `id` as `render_job_id`; it does not
mint an ID or authorization. RenderJob 10 is not a canary and must not run.

## Runner boundary

`audiovisual_worker.execute_cloud` validates the envelope before acquisition.
For remote scenes it invokes `render_media_materializer`, which uses the existing
`YtDlpMediaIngestion`, not raw HTTP. Page URLs such as YouTube are passed to that
adapter. References remain `remote://media-worker/...` plus `source_url`.
A reference cannot map to conflicting URLs in one job.

The materializer downloads once per identity, checks a nonempty confined file,
probes real streams/duration, checks source windows, and records hashes and sizes.
Physical paths exist only in runtime copies. No database is written on hydration.
A failed acquisition or invalid source window blocks rendering without substitute
media. Public URLs may contain ordinary query parameters; credential parameters
are rejected. No cookies or secrets are copied from a phone.

If EditPlan is already supplied, its persisted copy is preserved and only runtime
media paths are resolved. Otherwise complete authorized scenes and explicit real
audio requirements are required to invoke the existing VEdit facade on physical
files. Its result passes the existing worker's strict duration/lineage validation.
No `require_real_media` bypass exists. The original job, effective EditPlan, asset
hash evidence, final probe, QA and manifest are retained. Failed hydration also
retains the input job and stage/type evidence.

Source audio is not silently promoted to narration. Audio requirements must
explicitly carry asset_ref, source_url, source_start_seconds and duration_seconds
(and their existing type/direction). The Harness must supply these decisions.

## Async execution

The official factory dispatches without waiting. The existing on_dispatch callback
persists GitHub execution metadata before returning `pending=True`; the queue stays
running. `resume_cloud_render_job(job_id, executor)` resumes result collection from
the existing backend using that persisted run ID, without dispatching another run.
Collection still uses the existing watcher/artifact validator and must run on a
cloud backend, not on the phone. No scheduler or background host is created here.
A cloud backend must invoke this resume operation; automatic reconciliation has
not been demonstrated. Loss between remote dispatch and callback persistence is
not claimed to be solved.

## Validation and limits

Focused tests cover bridge lineage/timing, acquisition failure, identity preservation,
physical-file input to the real VEdit facade, unchanged persisted input, and async
resume without redispatch. Test media and authorization are fixtures, never proof of
a real canary. The validated cloud renderer was reused rather than reconstructed.

No real canary job/source authorization is accessible in this workspace. There is
no connected BR Harness runtime or production DB here. The most recent inspected
successful Media Worker run 34304107545 returned an empty artifacts list. No real
source bytes, MediaKnowledge, or selected canary were recovered from it.

Remaining execution inputs: an actual authorized 30–60s production item with selected
segment IDs and source URLs, explicit real audio direction, and access to the
existing cloud backend/Harness that owns those records. The implementation does
not invent those records, shorten Script 7, or repurpose RenderJob 10.

The render workflow uses per-execution/per-job output paths and the existing
`render-output` artifact name scoped to its GitHub run. It no longer requires a
50-minute master. Source Media Worker JSON-only artifacts remain unchanged.
