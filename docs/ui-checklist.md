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
- [ ] Tab reaches presets, every field, "Check order", the card buttons and "Sign order" in a
  logical order; Enter in a field submits "Check order"; no keyboard trap
- [ ] Focus ring is visible on every control (3 px blue outline)
- [ ] Status is understandable without colour (text label and icon on red, amber, green)
- [ ] Screen reader: the card area announces updates (aria-live); field errors are read with
  their field
- [ ] Zoom to 200% and a 320 px wide window: no horizontal scroll, nothing cut off
- [ ] Contrast spot check of the badge, hint, muted and error text (computed ratios are >= 4.5:1)
