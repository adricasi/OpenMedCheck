# 0003. Combine deterministic rules and the model with an escalate-only combiner

- Status: Accepted
- Date: 2026-10-17
- Deciders: adricasi

## Context
The product promise is that no model error can weaken a hard safety determination (G-2,
REQ-004). The model reads untrusted free text (the ED note), so prompt injection must be
assumed. Clinicians still need a model to catch conflicts that coded data doesn't show
(preset A, REQ-003).

## Options considered
1. **Rules first, model second, pure combiner that takes the stricter result**: the model
   sees the rules verdict and may only escalate; a pure function merges the two; alternatives
   are re-checked by the rules. Pros: the invariant is in ~50 lines of pure code and can be
   proven with property-based tests regardless of model behaviour. Cons: the model can't
   correct a rule that over-fires (false positives stay).
2. **Model decides, rules as a veto list**: Pros: more flexible. Cons: a silent model failure
   could produce a pass for a case the veto list doesn't cover; harder to state the guarantee.
3. **Rules only, model writes the explanation text**: Pros: simplest, safest. Cons: no value from
   the free-text note: preset A would pass. Kept as the fail-safe mode (REQ-005).

## Decision
We will use option 1: Layer 1 rules produce a verdict; Layer 2 Gemma returns a schema-validated
verdict; a pure combiner takes the stricter status, the higher tier and the union of flags;
fired rule reasons are always shown; model alternatives must be on the drug list and pass a
Layer 1 re-check. Any model failure falls back to option 3.

## Consequences
- Positive: the safety guarantee is independent of the model and of the prompt; it's testable
  in unit tests without a GPU.
- Negative / risks: rule false positives can't be downgraded by context; acceptable for a
  safety demo, stated in the post.
- Follow-ups: `hypothesis` as a dev dependency for property-based tests of the combiner.
