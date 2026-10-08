# BR-no-GTA — Iris Vision Plane V7

**Status:** Candidate only; no canonical promotion, private voice access, YouTube publication or Telegram mutation.

**Upstream:** [brijr/iris](https://github.com/brijr/iris), MIT, release v0.4.1, tag commit c3c08f839719fef515ed4c490873de37a0186ab8.

**Pinned Linux artifact:** iris-x86_64-unknown-linux-musl.tar.gz; SHA-256 aa6073ba255c0bcf09364a5503cbd4794791b832e5934a52b169a455d66101c7. Chrome-family browser required. Do not use curl-pipe-shell or unpinned latest, and do not install binaries on the A15 gateway.

## Design

Iris is only a *camera*. It is not an autonomous browser, software decompiler, quality assessor or Harness authority. Upstream exposes a CLI and an optional stdio MCP capture server. V7 uses only the pinned CLI; directly registering the unrestricted MCP to agents would bypass Harness routing and is prohibited.

Registered capability: reverse-engineering.web.iris-vision, domain web-visual-observation, RESEARCH only.
Executor: app.services.reverse_engineering_harness_service.execute_authorized_iris_capture.
Entrypoint: scripts/br_iris_visual_observe_v7.py.

A persisted Harness authorization is required with two independent scoped lists:
- allowed_media_roots: directories containing owner-authored static HTML.
- allowed_vision_output_roots: directories for private generated screenshots.

Both lists are nonempty, path scoped; source must be a real owned .html file, output a new .png inside the designated directory. Siblings, symlinks, pre-existing files, private Owner Voice folders and alternative URL schemes fail closed.

## Current allowed capture

Only owner-authored, trusted, local, self-contained static HTML rendered with Chrome from file://. Allowed viewport: 960x600 desktop or 390x844 mobile; optional bounded CSS selector; one screenshot per authorized task, PNG output created with permissions 0600 and SHA-256 evidence.

The source HTML validator rejects scripts, forms, event handlers, URLs/imports, external media, iframes and other dynamic tags. **This parser is defense in depth, not a proof of browser sandboxing.** It must never be pointed at third-party or otherwise untrusted HTML. Browser network egress isolation has NOT been verified.

The receipt contains source hash, image hash, dimensions, binary hash, capture mode, private output path, true/false provenance flags and a warning that visual quality was not independently approved. Raw pixels are not sent to the Harness learning reducer or Telegram automatically. Screenshot is an authorized private artifact, not canonical memory.

## Not yet authorized

- Capturing arbitrary live HTTPS websites (including redirects, subresource requests, localhost, RFC1918, cloud metadata, DNS rebinding, authenticated sessions and consent forms);
- Browser script execution and recording/copying third-party proprietary design;
- Direct open-world Iris MCP registration;
- Expanding permission to Owner Voice recordings, cookies, tokens or billing;
- Scoring a screenshot as artistically approved or using screenshot similarity as permission to clone protected sites.

Public-site capture should only be enabled after an independently audited browser egress sandbox and redirect/subresource controls, with explicit human approval and a site-specific allowlist. Do not substitute DNS checks alone for network containment.

## Real proof

A dedicated zero-secrets GitHub Actions workflow installs the exact upstream released binary, verifies archive SHA-256, checks Chrome exists and exercises two captures: full viewport desktop and selected-element mobile. It tests private image file bytes, PNG magic, SHA-256, correct metadata, owner source scope and no publication or memory writes. An independent review is still required before production promotion.

Command after a real Harness authorization exists:

    BR_IRIS_PINNED_BIN=/private/pinned/iris python scripts/br_iris_visual_observe_v7.py \
      --authorization-id EXISTING_HARNESS_AUTH_ID \
      --input /approved-owned/pages/scene.html \
      --output-image /private/visual-evidence/scene.png \
      --output-receipt /private/visual-evidence/scene-receipt.json \
      --viewport 960x600 --selector '#hero'

The CI screenshot fixture is not a real production web app and does not establish full scrollytelling or creative design QA. New original or licensed content can be compared against these visual receipts under further Harness-governed experiments.
