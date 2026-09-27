# Browser QA plane

DeepSeek Harness remains the only authority. Browser tooling is subordinate evidence collection.

- Playwright Test (`browser.qa.validate`) is the deterministic acceptance gate for real-browser behavior, accessibility/ARIA, console/network failures, and reviewed visual baselines.
- Playwright MCP (`browser.qa.explore`) is a bounded explorer for reproduction and diagnosis. Its output is observation evidence, never canonical PASS.
- MCP runs only against allowlisted loopback VEdit origins, in an isolated context, with synthetic project data. `browser_run_code_unsafe`, `browser_evaluate`, WebMCP, arbitrary MCP servers/endpoints, personal profiles, downloads and uploads are disabled.
- Interaction uses accessibility snapshots and semantic target refs. Vision mode is disabled by default.
- Visual goldens are never auto-updated; a baseline change is a reviewed candidate with explicit hashes.
- On a reproducible bug: persist MCP evidence, add a deterministic Playwright regression test, prove failure when possible, fix the cause, then prove the deterministic gate passes.
- Traces, screenshots and reports are content-addressed artifacts. Browser evidence cannot change routing, authorization, terminality, learning promotion, publication or repository authority.
