# UI checklist (T-007)

Manual pass for the browser. Run `uv run openmedcheck` with Ollama serving `gemma4:e4b`
and open http://127.0.0.1:8000.

Legend: `[x]` verified by an automated test or a scripted DOM stub run (named in brackets);
`[ ]` needs a person in a real browser. Nothing below was verified in a real browser by the
implementer.

## Every page
- [x] Banner "Not for clinical use — synthetic patients. Not a medical device." is visible
  (`tests/test_ui_static.py`, AC-010.1)
- [ ] Banner stays visible while scrolling (sticky) at 1280 px and at 375 px width
- [x] No CDN, no inline script or style, no `innerHTML` in static JS (`tests/test_ui_static.py`)
- [ ] Browser console shows no CSP violations and no failed requests while using the page
- [x] No "approved", "safe", or "diagnose" wording in templates and JS (`tests/test_ui_static.py`)

## Preset A (suspected ACS in the note only, aspirin at home, dexketoprofen)
- [x] `GET /api/presets/A` returns a valid request; rules-only card is `NO_ISSUE`
  (`tests/test_catalog_api.py`)
- [ ] Click "Preset A": rules card appears at once with "Checking context…"; "Sign order" is
  disabled meanwhile (AC-008.1, AC-008.7)
- [ ] With the model ready: final card is red, shows the text "Blocked" and an icon, order
  Action required → Why → Alternative; alternative is paracetamol (AC-006.1, AC-008.2, AC-008.5)
- [ ] "Sign order" is disabled until "Use alternative" or "Acknowledge and keep order" is chosen
  (AC-008.2)

## Preset B (reduced renal function, ciprofloxacin)
- [x] Rules card is `WARNING` (`tests/test_catalog_api.py`); changing eGFR/creatinine changes the
  verdict (AC-007.2)
- [ ] Amber card with "Warning" text and icon; renal adjustment line visible; "Sign order" is
  enabled and no modal appears (AC-006.2, AC-008.3)

## Preset C (benign, paracetamol)
- [x] Rules card is `NO_ISSUE` (`tests/test_api.py`, `tests/test_catalog_api.py`)
- [ ] Small green "No issue found by these checks" indicator, no alternative, no modal;
  "Sign order" enabled (AC-006.3, AC-008.4)

## Alternative flow
- [x] The alternative order (paracetamol on preset A's context) is re-checked and is `NO_ISSUE`
  (`tests/test_catalog_api.py`, AC-009.1)
- [ ] A, "Use alternative" while the alternative's dose is unreviewed (card shows "Dose: consult
  SmPC", no route/frequency): only the drug is replaced, dose and frequency are cleared, focus
  moves to Dose with a prompt, nothing auto-runs; enter a dose and frequency, press "Check
  order": green card (AC-009.1, AC-009.2; spec decision pending, see report)
- [ ] Once the dose is specialist-reviewed (route and frequency present): all four order fields
  are replaced and the check reruns automatically

## Simulated record (AC-006.5, AC-007.1, AC-007.4)
- [x] The page lists "ED patients (synthetic)" (Bed 3, Bed 7, Bed 12) instead of preset letters;
  each preset carries a distinct bed label (`tests/test_ui_static.py`,
  `tests/test_catalog_api.py`)
- [x] jsdom run of the real `app.js` against the local app with `gemma4:e4b` ready, 2026-10-18
  (34/34 checks): record and order hidden before a patient is selected; on selection focus
  moves to the record heading and the context is read-only (inputs `readOnly`, sex shown as a
  read-only text copy) and labelled "From the patient record (simulated)", only the order is
  editable; the request panel is filled on load and tracks the current inputs; Bed 7 `WARNING`, Bed 3 `BLOCKED`,
  Bed 12 `NO_ISSUE`; the request panel shows the body sent, including the sex from the
  disabled select; "Edit scenario (demo only)" unlocks the fields and relabels the record;
  an edited normal eGFR is evaluated; switching it off restores the record, keeps the drafted
  order, clears the card and announces "Record restored; scenario edits discarded."; switching
  patients resets the toggle
- [ ] In a real browser: read-only fields are visibly distinct (dashed border) and readable;
  the toggle, "Skip to Prescribe" and the request panel work by keyboard; layout at 1280 px (three columns) and
  375 px (stacked)

## Editing and validation
- [x] Edited context is evaluated, not the stored preset (`tests/test_catalog_api.py`, AC-007.2)
- [x] Out-of-range value is rejected with a field error by the API (AC-007.3)
- [ ] Age 12 (or weight 5, creatinine 50): inline error "… must be between …" next to the field,
  field gets focus, no request is sent (check the Network tab) (AC-007.3)
- [ ] Editing any field clears the card ("Inputs changed…") and disables "Sign order"

## AC-008.2 — Sign disabled on BLOCKED
- [ ] On a red card "Sign order" is disabled with the hint text; enabled after "Acknowledge and
  keep order"

## AC-008.7 — Disabled while checking; stale responses dropped
- [ ] Throttle the network to "Slow 3G" or stop Ollama mid-check: "Sign order" stays disabled
  during "Checking context…"
- [ ] Click a preset and edit a field (or click another preset) before the final card arrives:
  the earlier card never appears (request sequence numbers; the DOM stub run confirmed the
  edit case)

## AC-008.8 — Sign order
- [ ] "Sign order" shows "Order signed (demo — nothing stored)"; reload the page: nothing was
  stored; the button cannot be clicked twice for the same card

## Model status line (AC-011.2, REQ-014)
- [ ] On load the line shows "Model warming…" then "Model ready (gemma4:e4b)"
- [ ] With Ollama stopped: "Model unavailable — rules-only checks"; presets still return a card
  with the note "Model check unavailable — rules only"
- [ ] If `/api/check` or `/api/model/health` is missing (404/5xx), the page still shows the rules
  card and a status line saying the model is unavailable (DOM stub run confirmed)

## Keyboard only (NFR-010)
- [ ] Tab reaches the patient list, the scenario toggle, every editable field, "Check order",
  the card buttons and "Sign order" in a
  logical order; Enter in a field submits "Check order"; no keyboard trap
- [ ] Focus ring is visible on every control (3 px blue outline)
- [ ] Status is understandable without colour (text label and icon on red, amber, green)
- [ ] Screen reader: the card area announces updates (aria-live); field errors are read with
  their field
- [ ] Zoom to 200% and a 320 px wide window: no horizontal scroll, nothing cut off
- [ ] Contrast spot check of the badge, hint, muted and error text (computed ratios are >= 4.5:1)

## Run-through 2026-10-17 (QA worker, no browser available)

No browser automation was available (no Playwright; the built-in browser cannot reach a
localhost server started from the shell). Everything below was verified over HTTP against the
real app (`uv run openmedcheck`, Ollama `gemma4:e4b` ready) and by reading `app.js`.
Every other unticked item above is **not verified - needs a human in a real browser**: sticky
banner, console/CSP messages, colours/icons as rendered, focus order and ring, "Checking
context..." between cards, stale-response behaviour, sign/acknowledge flow, zoom/320 px,
screen reader, contrast.

- [x] 2026-10-17 (HTTP): `GET /` serves the banner text, CSP header
  `default-src 'self'; script-src 'self'; ...` and one external-free script/stylesheet.
- [x] 2026-10-17 (HTTP): `GET /api/model/health` returns `{"status": "ready", "model":
  "gemma4:e4b"}`; the UI's `showHealth` reads `status` and `model` (matches). With Ollama URL
  `http://127.0.0.1:9` it returns `{"status": "unavailable", ...}` -> "Model unavailable -
  rules-only checks".
- [x] 2026-10-17 (HTTP): `POST /api/model/warmup` is 404 today; `warmUp()` swallows it and the
  page goes on to `refreshHealth()`.
- [x] 2026-10-17 (HTTP): A rules card `NO_ISSUE` (0.00 s) -> final `BLOCKED` (1.5 s) with
  alternative Paracetamol, dose "Dose: consult SmPC", empty route/frequency (UI takes the
  dose-clearing branch of "Use alternative").
- [x] 2026-10-17 (HTTP): B rules `WARNING` + renal flag, final `WARNING`, no alternative.
  C rules and final `NO_ISSUE`, headline "No issue found by these checks", no alternative.
- [x] 2026-10-17 (HTTP): Ollama unreachable: `/api/check` returns the rules card with
  `model_note` "Model check unavailable - rules only", `source: rules`, HTTP 200.
- [x] 2026-10-17 (HTTP): age 12 -> 422 with `errors[].field = context.age` (UI also validates
  client-side before sending).
- [x] 2026-10-17 (real model, eval): AC-009.1/9.2 — preset A re-checked with paracetamol (PO,
  1 g every 8 hours) gives final `NO_ISSUE` in 15/15 runs with prompt v3
  ([measurements](measurements/2026-10-17-prompt-v3.md)). Prompt v2 returned `BLOCKED` (6/6)
  because its guidance let a home antiplatelet alone raise ANTIPLATELET_ACS; fixed in v3.

## Fresh-clone run-through

2026-10-17, task T-010 (AC-011.1). Clone of branch `dev` (219dc52) into an empty temporary
directory, README followed step by step. Python 3.12.3, uv 0.12.20, Ollama with `gemma4:e4b`
already pulled (`ollama list` confirmed it; `ollama pull` not repeated). Synthetic data only.

| Step | Result |
|---|---|
| `git clone` of the branch | pass |
| `ollama list` shows `gemma4:e4b` | pass |
| `uv sync` (network: pypi.org, files.pythonhosted.org) | pass |
| `uv run openmedcheck` serves 127.0.0.1:8000 | pass; `GET /` 200, banner "Not for clinical use — synthetic patients" present |
| `GET /api/model/health` | pass: `ready`, model `gemma4:e4b` |
| `POST /api/model/warmup` | pass: 202 |
| Preset A, rules then final | pass: `NO_ISSUE` (0.00 s), then `BLOCKED` (1.94 s), alternative Paracetamol, "Dose: consult SmPC" |
| Preset A with paracetamol applied | pass: `NO_ISSUE` |
| Preset B | pass: rules `WARNING` with `renal_adjustment_required`; final `WARNING` (1.58 s), no alternative |
| Preset C | pass: `NO_ISSUE` both, headline "No issue found by these checks", no alternative |
| Second instance, `OPENMEDCHECK_OLLAMA_URL=http://127.0.0.1:9`, port 8001 | pass: health `unavailable`; A, B, C all HTTP 200 rules-only (`source: rules`), note "Model check unavailable — rules only"; A stays `NO_ISSUE` |

README corrections made from the run-through: added the clone step and the `ollama list` check,
the expected result per preset, the warm-up and cold-start behaviour, the rules-only fallback
instance command and the HTTP endpoints; the alternatives and "Dose: consult SmPC" wording in
"How it works". Not covered: a visual walk through the UI in a browser (checked through the same
API calls the UI makes) and README screenshots. Servers were stopped by PID and the clone deleted.
