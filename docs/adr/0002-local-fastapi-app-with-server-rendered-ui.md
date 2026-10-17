# 0002. Build the demo as one local FastAPI app with a server-rendered UI

- Status: Accepted
- Date: 2026-10-17
- Deciders: adricasi

## Context
OpenMedCheck must run entirely on one machine (REQ-011, NFR-001) with no CDN or telemetry
calls. The UI needs a two-step card display (rules card, then final card; REQ-008), editable
fields with inline validation (REQ-007) and a one-click alternative (REQ-009). One developer,
about 24 h to feature freeze, strong in Python. The rules engine and model client are Python.

## Options considered
1. **FastAPI + Jinja2 page + a small vanilla-JS module (no build step)**: one process, one
   language, one toolchain (`uv`). Static assets are served locally. Pros: least setup, easy to
   test with `TestClient`, nothing to vendor. Cons: hand-written DOM code; less polish than a
   component framework.
2. **FastAPI JSON API + React/Vite TypeScript SPA**: Pros: richer UI, components. Cons: a second
   toolchain (Node, npm, lockfile, audit), a build step in the README, more hours.
3. **Streamlit or Gradio**: Pros: fastest first screen. Cons: hard to control the two-step
   card, button-disabling and layout; reruns the whole script per interaction; pulls a large
   dependency tree; harder to write the API tests the invariant needs.

## Decision
We will build one FastAPI app that serves a Jinja2 page, local static CSS/JS and a JSON API,
because it fits the deadline, keeps a single Python toolchain and makes the API (where the
safety invariant lives) directly testable.

## Consequences
- Positive: `uv sync && uv run openmedcheck` is the whole start-up; no Node. The JSON API can be
  reused by a future EHR integration.
- Negative / risks: the UI code is hand-written. Mitigation: keep it to one page and one JS
  module, all model text inserted with `textContent` (never `innerHTML`, NFR-001).
- Follow-ups: new runtime dependencies `fastapi`, `uvicorn`, `jinja2`, `httpx`, `pydantic`
  (pinned in `uv.lock`, audited with `pip-audit`).
