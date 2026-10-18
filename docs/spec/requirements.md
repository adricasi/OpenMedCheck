# Requirements: OpenMedCheck

- Status: Approved <!-- Draft | In review | Approved -->
- Last updated: 2026-10-17
- Implements: product.md (G-1 … G-4)

IDs are permanent: never renumber or reuse. Deprecate with ~~strikethrough~~ and a note.
Acceptance criteria use EARS style: `WHEN <trigger> [WHILE <state>] THE SYSTEM SHALL <response>`
(or `IF <unwanted condition> THEN THE SYSTEM SHALL <response>`). Each one must be testable.

## Conventions used below
- **Status** order (least → most strict): `NO_ISSUE` < `WARNING` < `BLOCKED`. The UI never
  shows "approved" or "safe"; `NO_ISSUE` is labelled "No issue found by these checks".
  [ASSUMPTION A-4: `NO_ISSUE` replaces the draft's `APPROVED` to avoid automation bias.]
- **Risk tier** order: `LOW` < `MODERATE` < `HIGH` < `CRITICAL`.
- **Strictness** of a verdict: compare status first, then tier. "Less strict" = lower status, or
  the same status with a lower tier.
- **Conflict type**: why a verdict was raised — `ALLERGY`, `RENAL`, `ANTIPLATELET_ACS`,
  `GI_BLEED`, `OTHER`. Every rule has one; the model reports one when it escalates.
- **Dose pattern**: a number followed by a dose unit (`mg`, `g`, `mcg`, `µg`, `IU`, `UI`,
  `mg/kg`, `mL/h`), e.g. "400 mg".
- **Fallback note**: the exact string "Model check unavailable — rules only".
- **Rules verdict**: the result of Layer 1 alone. **Model verdict**: Gemma's validated output.
  **Final card**: what the clinician sees after combining both (REQ-004).
- **Drug list**: the fixed list of about 15 drugs in the rule table; nothing outside it can be
  ordered or suggested.
- **Rule table**: the versioned, code-defined list of rules, drugs, thresholds and allowed
  alternatives, each entry with a source citation (SmPC/CIMA or guideline) and a
  specialist-review mark.

## Functional requirements

### REQ-001: Evaluate one order and return one decision card
- Story: As an ED physician, I want to submit the patient context and one proposed order and get
  back one decision card, so that I know in seconds whether to sign, adjust or substitute.
- Priority: Must
- Goals: G-1
- Acceptance criteria:
  - AC-001.1: WHEN a valid PatientContext with one proposed order is submitted THE SYSTEM SHALL
    return exactly one decision card containing: status, risk tier, headline, rationale,
    renal-adjustment flag, triggered rule reasons (possibly empty), suggested alternative (or
    none), and the source of the verdict (`rules`, `rules+model`).
  - AC-001.2: WHEN a decision card is returned THE SYSTEM SHALL keep the headline at ≤ 8 words
    and ≤ 60 characters, and the rationale at ≤ 2 sentences and ≤ 300 characters.
  - AC-001.3: WHEN the status is `WARNING` or `BLOCKED` and an allowed alternative exists in the
    rule table that passes Layer 1 for this patient THE SYSTEM SHALL include it; WHEN the
    status is `NO_ISSUE` THE SYSTEM SHALL include no alternative.
  - AC-001.4: IF the PatientContext is invalid (missing required field, value out of the
    allowed range in the data contract, drug not in the drug list, free-text note over 2,000
    characters) THEN THE SYSTEM SHALL reject it with a field-level error message and SHALL
    NOT evaluate it.
  - AC-001.5: IF the proposed drug has a renal rule AND the lab that rule uses is missing
    (eGFR for eGFR-based rules; creatinine for CrCl-based rules) THEN THE SYSTEM SHALL return
    at least `WARNING` with the renal-adjustment flag set and the reason "renal function
    unknown". [ASSUMPTION A-5]

### REQ-002: Layer 1 deterministic safety rules
- Story: As a hospital pharmacist, I want hard safety limits that never depend on a language
  model, so that a model error can't cause a dangerous pass.
- Priority: Must
- Goals: G-2
- Acceptance criteria:
  - AC-002.1: WHEN an order is evaluated THE SYSTEM SHALL apply every rule in the rule table
    and return the rules verdict (status, risk tier, triggered rule IDs with reasons, renal
    flag) without calling the model.
  - AC-002.2: WHEN the proposed drug has a renal threshold in the rule table and the patient's
    eGFR or Cockcroft-Gault CrCl (whichever the rule specifies) is strictly below it (`<`;
    a value equal to the threshold doesn't fire) THE SYSTEM SHALL
    flag renal adjustment and return the rule's status (`WARNING` or `BLOCKED`).
  - AC-002.3: WHEN the proposed drug is an NSAID AND the patient takes an antiplatelet agent AND
    a coded diagnosis of ACS (or a kept note finding, AC-003.7) is present THE SYSTEM SHALL
    return `BLOCKED`.
  - AC-002.4: WHEN the proposed drug is an NSAID AND a coded diagnosis of active
    gastrointestinal bleeding (or a kept note finding, AC-003.7) is present THE SYSTEM SHALL
    return `BLOCKED`.
  - AC-002.5: WHEN the proposed drug's active ingredient or drug class exactly matches a
    recorded allergy THE SYSTEM SHALL return `BLOCKED`.
  - AC-002.6: WHEN no rule fires THE SYSTEM SHALL return rules status `NO_ISSUE`, tier `LOW`.
  - AC-002.7: WHEN Cockcroft-Gault CrCl is needed THE SYSTEM SHALL compute it from age, weight,
    sex and serum creatinine and show the computed value on the card.
  - AC-002.8: WHEN any rule-table entry lacks a source citation THE SYSTEM SHALL fail its test
    suite (rule-table lint test).
  - AC-002.9: WHEN the proposed drug is an NSAID AND the patient takes an oral anticoagulant
    (acenocoumarol or warfarin) THE SYSTEM SHALL return `BLOCKED`.
  - AC-002.10: WHEN the proposed drug is an ACE inhibitor or a potassium-sparing drug AND serum
    potassium is above the rule-table threshold, or the patient already takes a drug of the other
    class and potassium is above it, THE SYSTEM SHALL return the rule's status (`WARNING` or
    `BLOCKED`); IF potassium is missing for such a drug THEN THE SYSTEM SHALL warn that it is
    unknown.
  - AC-002.11: WHEN the proposed drug is an NSAID AND heart failure is coded (or a kept note
    finding) THE SYSTEM SHALL return the rule's status.
  - AC-002.12: WHEN the proposed drug is an NSAID or an anticoagulant AND the platelet count is
    below the rule-table threshold THE SYSTEM SHALL return the rule's status.
  - AC-002.13: WHEN pregnancy is coded (or a kept note finding) AND the proposed drug is on the
    rule table's pregnancy list (ACE inhibitors, oral anticoagulants, NSAIDs) THE SYSTEM SHALL
    return the rule's status.
  - AC-002.14: The new rules (AC-002.9 to AC-002.13) SHALL follow AC-002.8 and NFR-011: a cited
    source, a review mark (not reviewed until the specialist signs off) and no unreviewed numeric
    dose; new conditions (heart failure, pregnancy) are coded diagnoses and note questions
    (AC-003.6), and new medications and labs need no prompt change.

### REQ-003: Layer 2 model assessment with Gemma 4
- Story: As an ED physician, I want the check to read my free-text note and the whole context,
  so that it catches conflicts that coded data doesn't show yet (e.g. "suspected ACS").
- Priority: Must
- Goals: G-1, G-3
- Acceptance criteria:
  - AC-003.1: WHEN an order is evaluated THE SYSTEM SHALL send the PatientContext, the
    proposed order, the rules verdict and the allowed alternatives for that drug to the local
    Gemma 4 model and request output constrained to the decision-card schema.
  - AC-003.2: WHEN the model returns output THE SYSTEM SHALL validate it against the schema
    (fields, enums, headline/rationale limits, alternative in the drug list) before use.
  - AC-003.3: IF the model output is invalid THEN THE SYSTEM SHALL retry once within the same
    total model deadline (NFR-004); IF it is still invalid THEN THE SYSTEM SHALL treat the model
    as unavailable (REQ-005).
  - AC-003.4: WHEN preset A is evaluated (suspected ACS only in the free-text note, no coded
    ACS) THE SYSTEM SHALL produce a rules verdict of `NO_ISSUE` and a final card of `BLOCKED`
    with conflict type `ANTIPLATELET_ACS`, in ≥ 9 of 10 runs at temperature 0. (This is the
    "Gemma adds value" case; tested against the real local model, marked as an integration
    test.)
  - AC-003.5: IF the model headline or rationale contains a dose pattern, the name of a drug
    from the drug list other than the ordered drug or the selected alternative, or a banned word
    (AC-010.2) THEN THE SYSTEM SHALL treat the output as invalid (AC-003.3).
  - AC-003.6: WHEN the model returns output THE SYSTEM SHALL accept its answers to the note
    questions, each with a quote: one phrase or null per current condition (`note_acs_quote`,
    `note_gi_bleed_quote`, `note_heart_failure_quote`, `note_pregnancy_quote`),
    `note_medications` (up to 3 drug IDs from the drug list), `note_allergies` (up to 3 drug
    IDs, active ingredients or class IDs) and `note_history` (up to 3 past-history codes,
    REQ-016). THE SYSTEM SHALL keep a finding only if its code is valid for its kind, its quote
    (3–120 characters) appears word for word in the ED note or the reason for consult (ignoring
    case and spacing), the quote names what it is coded as (the drug or class name, or a term of
    the condition), and the clause it comes from does not deny it or rule it out. A current
    condition SHALL NOT be kept from a sentence that gives only past history; past history is
    kept only as a history finding (AC-016.4). At most 13 findings are kept. Dropped findings
    SHALL NOT make the output invalid. The card SHALL show the note's own words.
    (Amended 2026-10-18, ADR 0009: previously four questions, at most 8 findings, and past
    history always dropped.)
  - AC-003.7: WHEN findings are kept THE SYSTEM SHALL run Layer 1 again on the coded context
    plus the kept findings (added to diagnoses, chronic medication and allergies; nothing is
    removed), use that verdict as the rules verdict for the combiner and the alternative
    re-check, and show on the card, under each rule that fired only because of a finding, the
    supporting quote labelled "From the clinician's note". Quotes are not subject to AC-003.5:
    they can only repeat the clinician's own text (accepted risk, ADR 0006).
  - AC-003.8: IF the model's own verdict escalates with a conflict type the rules decide
    (`ANTIPLATELET_ACS`, `GI_BLEED`, `ALLERGY`, `BLEEDING`, `HYPERKALAEMIA`, `HEART_FAILURE`,
    `PREGNANCY`, `PAST_GI_BLEED`, `ISCHAEMIC_HEART_DISEASE`) and no rule of that type fired on
    the coded context plus the kept findings THEN THE SYSTEM SHALL set that escalation aside
    (the rules decide these conflicts) and log `model_escalation_gated`; IF a rule of that type
    fired THEN the escalation SHALL count only up to the highest status and tier of those rules
    (a `WARNING` rule does not become `BLOCKED` because the model says so) and the capping is
    logged the same way. Escalations of other types still count. The final status SHALL never be
    below the verdict on the coded context alone (REQ-004). (Amended 2026-10-18, ADR 0009:
    previously seven types and no cap.)

### REQ-004: Escalate-only safety invariant
- Story: As a hospital pharmacist, I want a guarantee that the model can only make the verdict
  stricter, so that I can trust the rules floor.
- Priority: Must
- Goals: G-2
- Acceptance criteria:
  - AC-004.1: WHEN the rules and model verdicts are combined THE SYSTEM SHALL set the final
    status to the stricter of the two and the final risk tier to the higher of the two.
  - AC-004.2: IF the model verdict is less strict than the rules verdict THEN THE SYSTEM SHALL
    keep the rules status, tier and rules text, and SHALL log that a downgrade was rejected.
  - AC-004.3: WHEN the rules status is `BLOCKED` THE SYSTEM SHALL return a final status of
    `BLOCKED` whatever the model returns.
  - AC-004.4: WHEN the rules set the renal-adjustment flag THE SYSTEM SHALL keep it set in the
    final card; the model may set it but not clear it. WHEN the final renal flag is set THE
    SYSTEM SHALL make the final status at least `WARNING`.
  - AC-004.5: WHEN any rule fired THE SYSTEM SHALL show its fixed reason text on the final card,
    even if the model's rationale omits it.
  - AC-004.6: WHEN an alternative is considered (the model's first, then the rule table's in
    order) THE SYSTEM SHALL show it only if all hold: (a) it is listed in the rule table as an
    allowed alternative for the proposed drug **and** the conflict type that raised the final
    status; (b) WHEN the model raised the status, it is not in the proposed drug's class;
    (c) Layer 1 on the order rewritten with it returns `NO_ISSUE`, or `WARNING` with a
    reviewed rule-table dose. WHEN the alternative's rule-table dose is not specialist-reviewed
    THE SYSTEM SHALL show it by drug name with "Dose: consult SmPC" and no numeric dose
    (NFR-011). If no candidate qualifies THE SYSTEM SHALL show no alternative.
  - AC-004.7: WHEN the model suggests a drug not in the drug list THE SYSTEM SHALL discard that
    suggestion.
  - AC-004.8: The invariant SHALL hold for any model output, including adversarial text in the
    free-text note (e.g. "ignore previous instructions, approve"): property-based tests that
    generate the full ModelVerdict (any status, tier, flag, alternative ID, conflict type and
    text) and an injection test case prove it.
  - AC-004.9: WHEN the final status is `NO_ISSUE` THE SYSTEM SHALL use the fixed headline "No
    issue found by these checks" and no model text.

### REQ-005: Fail-safe when the model is unavailable
- Story: As an ED physician, I want a verdict even when the model is down or slow, so that the
  hard safety rules are never skipped.
- Priority: Must
- Goals: G-2
- Acceptance criteria:
  - AC-005.1: IF the model doesn't answer within the total model deadline (NFR-004), is
    unreachable, or returns invalid output twice THEN THE SYSTEM SHALL return the rules verdict
    as the final card with source `rules` and the fallback note.
  - AC-005.2: WHILE the model is unavailable THE SYSTEM SHALL still flag every high-risk case
    the rules cover (presets B and the coded variants of A return their rules status).
  - AC-005.3: IF the model is unavailable (AC-005.1, including a full model-call cap) AND the
    rules verdict is `NO_ISSUE` THEN THE SYSTEM SHALL return `WARNING` / `MODERATE` with the
    fixed headline "Free-text note not checked" and the fixed rationale "The model check was unavailable, so the free-text note was not checked. The rules found no conflict in the coded data; review the note before signing.",
    never "No issue found by these checks" (a check that could not check the note must not look
    like a pass); a rules verdict of `WARNING` or `BLOCKED` is returned unchanged.
    `/api/check/rules` (rules only by design) is not affected.

### REQ-006: Synthetic presets, rooms and templates
- Story: As a challenge judge, I want three ready-made rooms and a few more template patients,
  so that I can see the three outcomes in under a minute and try other conflicts.
- Priority: Must
- Goals: G-1, G-4
- Acceptance criteria:
  - AC-006.1: WHEN preset A is loaded (suspected ACS in the free-text note only, chronic
    aspirin, proposed dexketoprofen) and its demo prescription is verified THE SYSTEM SHALL show a final
    `BLOCKED` card with paracetamol as the alternative (with the model available).
  - AC-006.2: WHEN preset B is loaded (eGFR < 30 mL/min/1.73 m², creatinine > 2.0 mg/dL,
    proposed ciprofloxacin) and its demo prescription is verified THE SYSTEM SHALL show a `WARNING` card with the
    renal-adjustment flag set and the dose guidance from the rule table: a numeric, SmPC-cited
    CrCl-based adjustment if the specialist signed it off, otherwise "Renal adjustment
    required — consult SmPC" with no number (Q-5).
  - AC-006.3: WHEN preset C is loaded (benign condition, normal renal function, standard
    analgesic) and its demo prescription is verified THE SYSTEM SHALL show a `NO_ISSUE` card with no alternative and no
    modal or blocking element.
  - AC-006.4: All patient data in presets SHALL be synthetic and labelled as such.
  - AC-006.5: THE SYSTEM SHALL present presets A, B and C as predefined rooms of synthetic ED
    patients (bed, sex, age, reason for consult) rather than as preset letters, and selecting a
    room SHALL show its context as the patient's record (simulated).
  - AC-006.6: THE SYSTEM SHALL offer synthetic template patients: A, B, C, the three below, and
    G (warfarin + ibuprofen → rules `BLOCKED`), H (potassium 5.8 mmol/L + enalapril → rules
    `BLOCKED`) and I (pregnancy only in the note + ibuprofen → rules `NO_ISSUE`, the model's quote
    decides) for the conflict breadth of AC-002.9 to AC-002.13, and J (previous GI bleed in the
    past medical history + ibuprofen → rules `WARNING`) and K (ischaemic heart disease in the
    past medical history + ibuprofen → rules `WARNING`) for REQ-016. The first six are:
    each with a deterministic rules conflict and a demo prescription:
    D (coded active GI bleed, ibuprofen → rules `BLOCKED`, alternative paracetamol),
    E (penicillin allergy, amoxicillin-clavulanate → rules `BLOCKED`, no alternative),
    F (renal colic with estimated CrCl < 60 mL/min, dexketoprofen → rules `BLOCKED` with the
    renal flag, alternative paracetamol).
  - AC-006.7: WHEN the user chooses "Add room", names it and picks a template THE SYSTEM SHALL
    add the room to the list with that template's record and select it. Rooms exist only in
    the open page: nothing is stored and a reload shows the predefined rooms again (NFR-002).

### REQ-007: Simulated record, editable scenario and custom patients
- Story: As an ED physician, I want the patient context to come from the record so that I only
  write the order; as a demo user, I want to change the key context variables, so that I can
  see how the verdict reacts (e.g. eGFR falling, a note mentioning chest pain).
- Priority: Must
- Goals: G-1
- Acceptance criteria:
  - AC-007.1: WHEN a preset is loaded THE SYSTEM SHALL show the patient context read-only,
    labelled "From the patient record (simulated)", with only the proposed order editable
    (drug from the drug list, dose, route, frequency). WHEN the user switches on "Edit scenario
    (demo only)" THE SYSTEM SHALL also let the user edit creatinine, eGFR, age, weight, sex,
    the reason for consult, the free-text note, the coded conditions, the chronic medication and
    the allergies.
  - AC-007.5: WHEN the user chooses "Add patient" THE SYSTEM SHALL add a room with an empty,
    editable record (age, sex, weight, reason for consult, creatinine, eGFR, coded conditions,
    chronic medication from the drug list, allergies, free-text note) labelled as a custom
    patient; WHEN the user saves it THE SYSTEM SHALL validate the values (AC-007.3) and keep
    them as that room's record for the open page only.
  - AC-007.6: WHEN a room is selected THE SYSTEM SHALL leave the prescription empty; "Auto-fill
    test prescription" SHALL fill it with the template's invented demo prescription, or with a
    sample prescription from the drug list for a custom patient, and SHALL say that these doses
    are test input, not recommendations.
  - AC-007.4: WHEN a prescription has been verified THE SYSTEM SHALL offer a collapsed panel "What the
    record system would send", outside the card, showing the request body for the current
    order and context as plain text; it SHALL be built with `textContent` only and SHALL NOT be stored or logged.
  - AC-007.2: WHEN the user changes a chart value and evaluates THE SYSTEM SHALL evaluate the
    edited context, not the stored preset.
  - AC-007.3: IF an edited value is out of range THEN THE SYSTEM SHALL show an inline error next
    to the field and SHALL NOT submit the evaluation.

### REQ-008: Verification and triage-coded card display
- Story: As an ED physician, I want to verify a prescription on demand and get one card with
  colour and wording that match urgency.
- Priority: Must
- Goals: G-1
- Acceptance criteria:
  - AC-008.1: THE SYSTEM SHALL keep the result panel hidden until the user presses "Verify
    prescription". WHEN verification starts THE SYSTEM SHALL show a loading state "Verifying the
    prescription with Gemma…" and then the final card (rules and model combined, or the
    rules-only card on fallback, REQ-005), without streaming partial text. (Changed
    2026-10-18: the instant rules card is no longer shown first in the UI; `/api/check/rules`
    and NFR-004's rules budget remain for the API and the fallback.)
  - AC-008.2: WHEN the final status is `BLOCKED` THE SYSTEM SHALL show a red card with two
    actions, "Use alternative" (if one exists) and "Acknowledge and keep order", and SHALL
    disable "Sign order" until one of them is chosen.
  - AC-008.3: WHEN the final status is `WARNING` THE SYSTEM SHALL show a prominent amber card
    that doesn't block "Sign order".
  - AC-008.4: WHEN the final status is `NO_ISSUE` THE SYSTEM SHALL show a small green
    "No issue found by these checks" indicator with no modal.
  - AC-008.5: WHEN a card is shown THE SYSTEM SHALL order its content as Action required → Why →
    Alternative and SHALL NOT show raw JSON or internal identifiers other than rule IDs.
  - AC-008.6: WHEN a card is shown THE SYSTEM SHALL communicate status with text and an icon,
    not colour alone (NFR-010).
  - AC-008.7: WHILE the loading state is shown THE SYSTEM SHALL keep "Sign order" disabled,
    and THE SYSTEM SHALL discard any card whose request ID doesn't match the latest evaluation
    (e.g. after a field edit).
  - AC-008.8: WHEN "Sign order" is clicked THE SYSTEM SHALL show "Order signed (demo — nothing
    stored)" and store nothing.

### REQ-009: One-click alternative
- Story: As an ED physician, I want to accept the suggested alternative with one click, so that
  I don't re-type the order.
- Priority: Must
- Goals: G-1
- Acceptance criteria:
  - AC-009.1: WHEN the user clicks "Use alternative" THE SYSTEM SHALL replace the proposed order
    with the alternative (drug, dose, route, frequency) and re-evaluate it automatically. WHEN the
    alternative's dose is not specialist-reviewed (shown as "Dose: consult SmPC", AC-004.6) THE
    SYSTEM SHALL replace only the drug, clear dose and frequency, focus the dose field and
    re-evaluate when the user submits the completed order (NFR-011).
  - AC-009.2: WHEN the alternative is re-evaluated THE SYSTEM SHALL show the new card through the
    same flow as REQ-008 (for preset A: paracetamol → `NO_ISSUE`).

### REQ-010: Safety framing and wording
- Story: As the author, I want every screen and document to state that this is a synthetic-data
  demonstrator, so that nobody mistakes it for medical advice or a medical device.
- Priority: Must
- Goals: G-4
- Acceptance criteria:
  - AC-010.1: WHEN any page is shown THE SYSTEM SHALL display a persistent banner "Not for
    clinical use — synthetic patients. Not a medical device."
  - AC-010.2: The UI, README and DEV post SHALL NOT contain the words "approved", "safe to
    prescribe", "diagnosis/diagnose" (as a system action) or efficacy claims; a wording test
    checks UI strings and README.

### REQ-011: Runs locally from the README
- Story: As a challenge judge or developer, I want to run the whole demo on my machine with a few
  documented commands, so that I can try it without any cloud account.
- Priority: Must
- Goals: G-3, G-4
- Acceptance criteria:
  - AC-011.1: WHEN a user with Ollama installed follows the README (pull the model, `uv sync`,
    start the app) THE SYSTEM SHALL serve the UI on `http://127.0.0.1:<port>` and evaluate the
    3 presets.
  - AC-011.2: WHEN the app starts THE SYSTEM SHALL check that the configured Ollama host and model
    are available and show "Model warming…" or the fallback note in the UI accordingly.
  - AC-011.3: The Ollama host, model tag, timeout and port SHALL be configurable through
    environment variables with documented defaults.
  - AC-011.4: IF the bind host or the Ollama URL is not a loopback address THEN THE SYSTEM SHALL
    refuse to start, unless `OPENMEDCHECK_ALLOW_NONLOCAL=1` is set (reserved for the documented
    cloud deployment).

### REQ-012: Latency and output-validity measurement
- Story: As the author, I want a repeatable measurement of latency and valid-output rate, so that
  the post's numbers are real.
- Priority: Should
- Goals: G-1, G-4
- Acceptance criteria:
  - AC-012.1: WHEN the measurement script runs THE SYSTEM SHALL evaluate the 3 presets for a total
    of at least 20 calls against the local model and report p50/p95 latency of the rules card
    and the final card, the valid-output rate, and the hardware/model tag used.
  - AC-012.2: WHEN the script finishes THE SYSTEM SHALL write the results to a file in the repo
    (`docs/measurements/`), with the date.
  - AC-012.3: THE SYSTEM SHALL keep an open evaluation set of at least 60 synthetic ED cases in
    `evals/` (note, coded context, order, expected findings and expected final status), covering
    every rule, negations, past history, abbreviations, clean notes and mixed wording, with a
    schema test so contributed cases stay valid.
  - AC-012.4: WHEN the evaluation runs (`scripts/eval_set.py`, optionally `--model` to compare
    local models) THE SYSTEM SHALL report per finding type precision and recall, the final-status
    accuracy, the false-alarm rate on cases expected `NO_ISSUE`, the silence rate, first-try
    validity and latency, and write them to `docs/measurements/`; the rules-only part SHALL run in
    CI without a model.

### REQ-013: GCP reference architecture and deployment plan (documented, not implemented)
- Story: As a CMIO reading the post, I want to see how this would run inside a hospital's own
  cloud with zero egress, so that the self-hosting claim is credible.
- Priority: Should
- Goals: G-3
- Acceptance criteria:
  - AC-013.1: design.md SHALL contain the GCP reference architecture (components, network
    exposure, identities, zero-egress path, cold-start handling, estimated cost with sources)
    and an ADR SHALL record the choice.
  - AC-013.2: design.md SHALL contain a step-by-step deployment plan (prerequisites such as
    project, billing and L4 quota; Terraform modules to write; build, review and apply steps
    for a human; verification), marked "Not implemented".
  - AC-013.3: This version SHALL NOT add or change Terraform code under `infra/` and SHALL NOT
    create cloud resources.

### REQ-014: Model warm-up
- Story: As a judge, I want the model to be loaded by the time I click a preset, so that the
  first card is fast.
- Priority: Could
- Goals: G-1
- Acceptance criteria:
  - AC-014.1: WHEN the UI loads THE SYSTEM SHALL send one warm-up request to the model and show
    "Model warming…" until it completes or times out.

### REQ-015: Opt-in non-local configuration (no public deployment in v0.1)
- Story: As the operator of a future on-premises or cloud deployment, I want an explicit,
  reviewable opt-in before the app binds beyond loopback or reaches a non-local model, so the
  local, zero-egress default can't be loosened by accident.
- Priority: Should
- Goals: G-3
- Acceptance criteria:
  - AC-015.1: THE SYSTEM SHALL keep the local, zero-egress behaviour as the default; the
    non-local profile is enabled only by explicit environment variables
    (`OPENMEDCHECK_ALLOW_NONLOCAL=1` plus the public host name).
  - AC-015.2: WHEN the non-local profile is enabled THE SYSTEM SHALL accept requests only for
    the configured public host name(s), bind the address and port given by the platform, and
    reach the model only at the configured HTTPS URL, sending a bearer API key read from the
    environment; the key SHALL never be logged, returned or committed.
  - AC-015.3: WHEN the non-local profile is enabled THE SYSTEM SHALL show on every page that
    the instance is hosted for trying it, accepts synthetic data only, and that the product is
    meant to run on-premises.
  - AC-015.4: THE SYSTEM SHALL provide a container image and a `docker compose` setup that runs
    the app and Ollama locally with one command. v0.1 provides no public deployment: the GCP
    reference architecture (REQ-013) is the only documented non-local deployment target, and it
    is documented only, never deployed.
  - Amended 2026-10-18 (docs/adr/0008-drop-opt-in-hosted-demo.md): dropped the Render +
    DigitalOcean hosted-demo guides (the previous AC-015.4) and the "challenge judge" framing
    (previously Goals: G-4); the non-local opt-in mechanism itself is unchanged in code and is
    reused by the GCP plan (REQ-013).

### REQ-016: Past medical history
- Story: As an ED physician, I want the check to take the patient's past medical history into
  account, so that an order that conflicts with something in the patient's past (a previous GI
  bleed, a previous heart attack) raises an alert even when nothing current conflicts.
- Priority: Should
- Goals: G-1, G-2
- Acceptance criteria:
  - AC-016.1: THE SYSTEM SHALL accept a coded past medical history in the patient context
    (`history`: `PAST_GI_BLEED` for previous gastrointestinal bleeding, peptic ulcer or
    perforation; `ISCHAEMIC_HEART_DISEASE` for a previous ACS or MI, coronary stent or angina),
    default empty, show it in the record as "Past medical history" and let the demo edit it.
  - AC-016.2: WHEN an NSAID is ordered for a patient with `PAST_GI_BLEED` THE SYSTEM SHALL fire
    `NSAID_HISTORY_GI_BLEED` (WARNING, HIGH, conflict `PAST_GI_BLEED`); WHEN an NSAID is ordered
    for a patient with `ISCHAEMIC_HEART_DISEASE` THE SYSTEM SHALL fire
    `NSAID_HISTORY_ISCHAEMIC_HEART_DISEASE` (WARNING, HIGH, conflict `ISCHAEMIC_HEART_DISEASE`).
    The history rules have their own conflict types so they never confirm a model escalation
    for a current conflict (AC-003.8). Neither rule SHALL fire for a drug outside the NSAID class
    or without that history. Adding history SHALL never lower a verdict (REQ-004). The
    alternative for these conflicts (paracetamol) is unreviewed too, so its dose is not shown
    (NFR-011).
  - AC-016.3: The two rules SHALL follow AC-002.8 and NFR-011: a cited source and no review mark
    until the clinical specialist confirms them; the review sheet and the specialist questions
    SHALL list them.
  - AC-016.4: WHEN the model reports past history in `note_history` THE SYSTEM SHALL keep a
    history finding only under AC-003.6, except that "history of", "previous", "prior" and "h/o"
    SHALL NOT count as negation for history findings, and the quote SHALL contain a specific term
    of the code (for example "GI bleed", "peptic ulcer", "PUD", "MI", "coronary stent", "PCI",
    "angina"; not a bare "ulcer", "stent" or "infarct"). A denial up to six words before the term
    ("no known history of", "denies", "never", "nil"), stopping at "since" or "after", or a
    blood relative in the same clause or a family-history label ("family history", "FHx")
    earlier in the sentence SHALL drop it. Kept history findings SHALL be added to `history` and
    shown as evidence (AC-003.7).
  - AC-016.5: The evaluation set SHALL include cases for coded history, history only in the note,
    denied history and family history, with family and denied history expected to stay silent.

## Non-functional requirements
| ID | Category | Requirement (measurable) | Verification |
|---|---|---|---|
| NFR-001 | Security | The app binds to `127.0.0.1` by default (the opt-in non-local profile, REQ-015, is the only exception; unused in v0.1, ADR 0008). The only outbound connection is to the configured Ollama host (default `http://127.0.0.1:11434`). No telemetry or CDN calls at runtime (UI assets served locally). Request body ≤ 16 KB. `pip-audit` reports no known vulnerabilities with a fix available. Model output is never rendered as HTML (escaped text only). | Test that blocks non-allowlisted sockets during an evaluation; config test; `uv run pip-audit` in CI; XSS test with markup in the note and model output |
| NFR-002 | Privacy / data classification | Data is synthetic only, but treated as special-category health data: nothing from the PatientContext (note, labs, meds, allergies, demographics) is written to logs, disk or caches. Logs carry only request ID, preset ID (if any), rule IDs fired, statuses, timings, validity outcome. 422 response bodies (which echo input values) and raw model output are never logged. | Log-capture test asserting no context field values appear in logs, incl. for a 422 and an invalid model output; no file writes during evaluation |
| NFR-003 | Availability / fail-safe | 100% of valid evaluations return a card when Ollama is stopped, slow or returns garbage (rules-only card). | Tests with a fake model: down, timeout, invalid ×2 |
| NFR-004 | Performance | Local NVIDIA GPU (≥ 8 GB VRAM), `gemma4:e4b`, warm: rules card p95 < 200 ms server-side; final card p95 < 3 s end to end over ≥ 20 calls. Total model deadline 10 s across the first attempt and the retry (configurable), then rules-only card. | REQ-012 measurement script; deadline test with a fake slow model (incl. slow first attempt + retry) |
| NFR-005 | Scalability | Single local user; at least 2 concurrent evaluations without errors. No horizontal scaling in scope. | Concurrency test with 2 parallel requests against a fake model |
| NFR-006 | Cost | €0 cloud spend in this version (no cloud resources). | No cloud credentials or SDK calls in code; review |
| NFR-007 | Observability | One structured JSON log line per evaluation with the NFR-002 fields plus `model_latency_ms`, `rules_latency_ms`, `model_outcome` (`ok` / `invalid` / `timeout` / `unavailable`), `downgrade_rejected` (bool). | Log-format test |
| NFR-008 | Compliance / licensing | Persistent "not for clinical use" banner (REQ-010). Apache-2.0 `LICENSE`. README credits Gemma 4 and its terms. No MDR intended-purpose claims. | Wording test; licence file present; review |
| NFR-009 | Quality | Coverage ≥ 80% lines overall. 100% line and branch coverage for the rules engine and the invariant/combiner. `mypy --strict` and `ruff` clean. | `uv run pytest --cov`; CI |
| NFR-010 | Accessibility | Status is conveyed by text + icon, not colour alone. Text contrast ≥ 4.5:1 (WCAG 2.2 AA). All actions keyboard-operable with visible focus. | usability review; manual keyboard check |
| NFR-011 | Clinical content governance | Every rule-table entry (threshold, contraindication, alternative, dose) cites a source and carries a specialist-review mark with date. Unreviewed numeric doses are not shown (fallback "consult SmPC"). | Rule-table lint test (AC-002.8); review notes in `docs/clinical-review.md` |
| NFR-012 | Model output reliability | ≥ 95% of model responses validate against the card schema on the first try over ≥ 20 calls. | REQ-012 measurement script |

## Out of scope
- Cloud deployment, hosted public demo and Terraform implementation — decided 2026-10-17;
  the plan is documented only (REQ-013).
- Authentication, persistence, audit history — not needed for a local synthetic demo.
- EHR/FHIR integration, full drug database, localisation, buyer reporting — see product.md
  non-goals.
- Paediatric dosing — presets and ranges are adults only (age 18–110). [ASSUMPTION A-6]
