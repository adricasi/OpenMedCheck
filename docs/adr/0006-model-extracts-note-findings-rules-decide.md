# 0006. The model extracts note findings with quotes; the rules decide

- Status: Accepted; amended by [ADR 0009](0009-patient-history-is-an-input.md) (past history
  in the note becomes a history finding; the gate caps confirmed escalations)
- Date: 2026-10-18
- Deciders: adricasi

## Context
Up to prompt v4 Gemma both read the ED note and judged the conflict, guided by prompt text for
two conflict types. That made the model's judgement the only path from free text to a
verdict, and it proved fragile: translating the notes to English made prompt v3 attach the
NSAID-and-ACS conflict to paracetamol in 15/15 runs (see `docs/measurements/2026-10-18-prompt-v4.md`).
Every new conflict type would need new prompt text and a new evaluation. Clinicians also need
to see *why* a free-text conflict was raised.

## Options considered
1. **Keep model judgement only (v4)**: Pros: no change. Cons: each conflict needs prompt
   guidance; no evidence shown; the rules never see what the note says.
2. **Model extracts structured findings with verbatim quotes; the rules decide**: the model
   returns conditions, medications and allergies it reads in the free text, each with a quote;
   code keeps a finding only if its code is valid and the quote appears word for word in the
   note; Layer 1 re-runs on the coded context plus the kept findings. Pros: every existing rule
   applies to free text without prompt text; the model's task is narrow and checkable; the card
   shows the quote. Cons: a larger schema and output; extraction misses still need the model's
   own verdict as a second signal.
3. **Fine-tune or use MedGemma for extraction**: Pros: likely better recall. Cons: needs an
   evaluation set and clinical review; out of scope for v0.1.

## Decision
We will use option 2. The model's own escalate-only verdict stays as a second signal for
conflicts the rules don't cover (`OTHER`); for the conflicts the rules decide (`ANTIPLATELET_ACS`,
`GI_BLEED`, `ALLERGY`) its escalation counts only if a rule of that type fired (AC-003.8). The
v5 evaluation showed why: on "ACS ruled out" the verifier dropped the quote, but the model's own
verdict still blocked the NSAID in 15/15 runs. Findings can only add facts, so the re-run rules verdict is never below the
coded verdict, and the combiner still never lowers it (ADR 0003). This relies on every rule
being monotonic: adding a fact can make a rule fire, never stop one. A finding whose quote is not
found verbatim is dropped silently; it never makes the output invalid.

## Consequences
- Positive: "Gemma reads, the rules decide": rule outcomes from free text are deterministic once
  a finding is kept, and each one is shown with the doctor's own words.
- Negative / risks: more output tokens (latency); if the model misses a finding it would have
  judged correctly, the escalation is lost for the rule-decided conflicts (never a coded rules
  result); quotes can contain whatever the note says,
  including dose text, but only text the doctor wrote.
- The gate keys on the model's conflict label: a model that labels an ACS concern `OTHER` still
  escalates. Escalate-only holds either way; the gate only limits the rule-decided labels.
- Negation is checked locally (a cue a few words before the matched term, or "ruled out" right
  after it, inside its clause), after a sentence-wide check dropped real findings such as
  "Suspected ACS, no ST elevation".
- Follow-ups: more conflict types through the rule table; specialist review of note-derived
  rules; a larger, varied evaluation set of notes.
