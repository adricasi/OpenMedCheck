# OpenMedCheck evaluation set

Synthetic emergency-department cases for measuring what the check catches, what it misses and
how often it stays silent. **All patients are invented.** Contributions are welcome; see
[CONTRIBUTING.md](../CONTRIBUTING.md#contributing-cases-clinicians-welcome).

## Format

`cases.jsonl` holds one JSON object per line:

```json
{
  "id": "acs-note-suspected",
  "tags": ["acs", "note_only"],
  "description": "Suspected ACS only in the note, home aspirin, NSAID.",
  "context": {
    "patient_id": "SYN-EVAL-001", "age": 62, "sex": "M", "weight_kg": 80,
    "reason_for_consult": "Chest pain",
    "ed_note": "62-year-old man with central chest pain for 1 hour. Suspected ACS; troponin pending.",
    "diagnoses": [], "chronic_medications": ["aspirin"], "allergies": [],
    "labs": {"creatinine_mg_dl": 1.0, "egfr_ml_min_1_73m2": 80}
  },
  "order": {"drug_id": "ibuprofen", "dose_text": "400 mg", "route": "PO", "frequency": "every 8 hours"},
  "expected": {
    "findings": ["CONDITION:ACS"],
    "rules_status": "NO_ISSUE",
    "final_status": "BLOCKED"
  }
}
```

- `context` and `order` are the same request the app sends to `/api/check` (synthetic
  `patient_id` starting with `SYN-`; drug IDs from the drug list). `context.history` is the
  coded past medical history (`PAST_GI_BLEED`, `ISCHAEMIC_HEART_DISEASE`; REQ-016), empty if
  absent.
- `expected.findings`: what the note or reason for consult **states**, as `KIND:CODE`.
  Kinds and codes: `CONDITION:ACS`, `CONDITION:ACTIVE_GI_BLEED`, `CONDITION:HEART_FAILURE`,
  `CONDITION:PREGNANCY`, `MEDICATION:<drug ID>`, `ALLERGY:<drug ID, active ingredient or class
  ID>`, `HISTORY:PAST_GI_BLEED`, `HISTORY:ISCHAEMIC_HEART_DISEASE`. A past event the note
  states for the patient is a `HISTORY` finding, never a current `CONDITION` (REQ-016, ADR
  0009); a denied, ruled-out or relative's mention is **not** a finding. Clinical shorthand
  for a suspicion counts: `?ACS`, `query ACS`, `possible ACS` and `r/o ACS` (still to be ruled
  out) state a suspected ACS; only `ACS ruled out` or `ACS excluded` is a rule-out.
- `expected.rules_status`: the rules on the coded record alone.
- `expected.final_status`: the rules on the coded record **plus** the expected findings, which
  is what the full check should return.

`tests/test_eval_set.py` enforces both statuses, so a case can never silently disagree with the
rules, and checks that every rule fires in at least one case.

## Tags

`note_only` (the fact is only in free text), `coded`, `history` (coded past medical history,
REQ-016), `negation`, `past_history`,
`family_history`, `abbreviation`, `wording` (typos, unusual phrasing), `clean` (should stay
silent), `non_nsaid`, `missing_lab`, `boundary`, `known_limit`, plus the topic (`acs`,
`gi_bleed`, `allergy`, `anticoagulant`, `potassium`, `heart_failure`, `platelets`, `pregnancy`,
`renal`, `medication`).

## Run it

```bash
uv run pytest tests/test_eval_set.py                  # validity, no model (CI)
uv run python scripts/eval_set.py --rules-only        # rules baseline, no model
uv run python scripts/eval_set.py                     # with the configured local model
uv run python scripts/eval_set.py --model gemma3:4b   # compare another local model
```

Reports are written to `docs/measurements/<date>-eval-set-<model>.md` (aggregates and case IDs
only; no note text or model output).
