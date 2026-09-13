# Tooling checkpoint and deferred RUN-001 boundary

Base: `3c09ea26663b798b4993031090c23366649f0c55` on `codex/run-001-app`.
Reviewed commits `96b6692`, `3c04e0d`, `3c09ea2`: only tooling workflows changed.
Existing cloud evidence remains valid:
- Agent Tooling Bootstrap run `34719137613`: SUCCESS (user-confirmed).
- Codex Agent Skills Validation run `34719371222`, job `103622270463`: SUCCESS;
  fetched logs confirm Codex `0.154.0`, plugin `0.6.9`, enabled native install.

New validation: pinned Addy bootstrap executed successfully on Linux; official
Higgsfield companion installation discovered 8 and installed the selected 4.
Native Codex app-server `skills/list`: 24 Addy plus 4 Higgsfield enabled, zero
loading errors; selected code-review skill readable. No LLM turn or generation.
Python compilation, shell syntax, all three tooling YAML parses and diff check
passed. No audiovisual regression suite was rerun: no runtime code changed.

The new Higgsfield binary installation here failed at its official npm release
binary download: proxy tunnel timeout. Its prior GitHub Actions PASS is preserved,
but this is not evidence of a fresh local CLI/auth PASS. No login was initiated,
no token read, no credits spent. The complete new bootstrap still requires cloud
execution after push. This checkpoint does not claim authenticated generation.

Push attempted over Git: failed because no HTTPS credential was available.
GitHub connector write attempt: 403, Resource not accessible by integration.
New commits therefore require transfer before new Actions validation is possible.

## Job 16 — diagnosis only, not a canary PASS

Run `34717863409`, job `103618219740` failed. Its diagnostic artifact
`render-failure-34717863409-1`, ID `10305845640`, was retrieved successfully.
`render-qa.json` says FAIL at `timeline`; materialization evidence says KeyError
at render. Neither contains the exception key/traceback or effective EditPlan.

The preserved RenderJob was passed through the existing create_edit_plan and
build_timeline with a technical probe stub (no download, render, or new DB record).
This reproduced:

```
build_timeline -> Store.add_effect -> effects.validate_effect -> _spec
KeyError: effetto sconosciuto: 'vedit_graphic:title'
```

The application emits the semantic title descriptor `vedit_graphic:title`;
the worker passes it as an engine filter name. The engine catalog rejects it.
This reproduction explains the boundary failure; it is not proof of an MP4.

Preserved identity from the artifact:
- render_job_id: 16
- video_id: 3
- content_item_id: 3
- script_id: 7
- idea_id: 43
- execution_id: run-001-canary-render-16
- brain_decision_id: run-001-canary-render-po-token
- authorized_action: EXECUTION

No Job 17, redispatch, record rewrite or runtime patch was made. After tooling
cloud validation, the minimum runtime correction is to map the existing semantic
graphic into the engine's existing text/graphics operation with its explicit
timing/style, preserving the plan. Do not silently omit the title or change media
acquisition. Preserve effective EditPlan and safe failure location in subsequent
failure artifacts, then reconcile/retry Job 16 through the existing backend.
