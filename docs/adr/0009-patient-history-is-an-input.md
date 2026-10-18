# 0009. Past medical history is an input, not a negation

- Status: Accepted
- Date: 2026-10-18
- Deciders: adricasi
- Amends: [ADR 0006](0006-model-extracts-note-findings-rules-decide.md) (how past history in the
  note is treated). REQ-016 and AC-003.6 record the change.

## Context
Until now OpenMedCheck looked at the patient's *current* state only: coded current conditions,
home medication, allergies, labs and today's note. Past history was discarded on purpose: the
prompt told Gemma to leave out sentences that give "only past history", and the verifier treated
"history of", "previous", "prior" and "h/o" as negation, so "History of ACS in 2019" could not
become a current ACS. The evaluation set expected silence for "Previous GI bleed in 2015" +
ibuprofen and "History of ACS in 2019 with a stent" + ibuprofen.

That protected against one error (treating an old event as a current one) by ignoring the past
altogether, which is a clinical gap: NSAID SmPCs list a history of gastrointestinal bleeding or
perforation related to previous NSAID therapy and a history of recurrent peptic ulcer or
haemorrhage as contraindications (ibuprofen, section 4.3; some dexketoprofen labels list any
history of GI bleeding, ulceration or perforation), and EMA contraindicates diclofenac in
established ischaemic heart disease (2013 referral). The product owner considers checking the
order against the patient's history the core value of the product.

## Options considered
1. **Keep ignoring past history.** Pros: no change. Cons: the gap above; an alert that matters
   (NSAID after a previous GI bleed) is never raised.
2. **Treat past mentions as current conditions** (drop "history of" from the negation cues).
   Pros: small change. Cons: wrong: "History of ACS in 2019" would fire the current-ACS rule
   (`BLOCKED`, ACS + antiplatelet), a false alarm on an old, treated event.
3. **A separate past-history input with its own rules.** Coded `history` in the record
   (`PAST_GI_BLEED`, `ISCHAEMIC_HEART_DISEASE`); rules keyed on it; and, from the note, a separate
   `note_history` question whose findings feed `history`, never the current conditions. Pros:
   current and past stay distinct; each past event gets a rule that matches what the sources say
   about the past, not the present. Cons: a prompt and schema change (prompt v8) that needs the
   real-model evaluation; two new rules that need the specialist.

## Decision
We will use option 3, in two steps. Step 1 (T-018): the coded `history` field, the rules
`NSAID_HISTORY_GI_BLEED` and `NSAID_HISTORY_ISCHAEMIC_HEART_DISEASE` (both WARNING / HIGH), and the
recorded history shown to the model. Step 2 (T-019): the `note_history` question; for history
findings "history of", "previous", "prior" and "h/o" are evidence, not negation, while a denial
("no history of", "denies") or a relative (father, mother, sibling, family) still drops the
finding. Current-condition findings keep today's negation rules, so a past event never becomes a
current one.

Both rules start at WARNING because the labels differ on how far the contraindication goes
(NSAID-related or recurrent events in some labels, any history in others) and because they have
not been reviewed yet; whether either should be `BLOCKED` (for example diclofenac with ischaemic
heart disease) is a question for the specialist. The new rules reuse existing conflict types
(`GI_BLEED`, `ANTIPLATELET_ACS`), so the model's conflict-type enum and the alternative table do
not change, and the paracetamol alternative (reviewed dose) applies as for the current
conditions.

## Consequences
- Positive: an NSAID ordered after a previous GI bleed or a previous heart attack raises an alert
  with the reason, the source and (from the note) the doctor's own words. Adding history can
  only make the verdict stricter, so the escalate-only invariant (ADR 0003) is unchanged.
- Negative / risks: two clinically unreviewed rules ship marked as such (NFR-011); prompt v8 can
  shift the model's behaviour on the other evaluation cases, so it must be evaluated on the real
  model before merging, and step 2 stays a separate, revertible commit; a history mention the
  verifier misreads (an unusual family phrasing) could add a WARNING, never remove one.
- Follow-ups: specialist review of both rules (and the BLOCKED question); more history codes
  (stroke, renal transplant) only with a source and a rule; record-system integration would read
  the coded history from the problem list.
