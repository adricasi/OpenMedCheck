# Contributing to OpenMedCheck

OpenMedCheck is an open, reviewable prescribing check: a rule table anyone can read, a local
open-weights model that only reads the clinician's note, and an evaluation set that shows what
the system catches and what it misses. Contributions from **clinicians** (emergency physicians,
pharmacists, nurses, residents) are as welcome as code.

> **Synthetic data only.** Never put real patient data in an issue, a test case, an evaluation
> case or a screenshot. OpenMedCheck is a concept demonstrator, not a medical device.

## Ways to help

| You are | You can |
|---|---|
| A clinician | Review a rule and its source, propose a new rule, write synthetic evaluation cases, answer the open questions in [`docs/clinical-review.md`](docs/clinical-review.md) |
| A developer | Fix a bug, improve the note verifier, add tests, improve the UI or the deployment guides |
| Anyone | Report a case where the card was wrong, unclear or noisy (with an invented patient) |

## How a rule works

Every rule lives in [`src/openmedcheck/rule_table.py`](src/openmedcheck/rule_table.py) as plain
data, and is shown, with its source, in the generated review sheet
[`docs/clinical-review.md`](docs/clinical-review.md). A rule has:

- **an ID** that never changes or gets reused (`NSAID_ORAL_ANTICOAGULANT`);
- **what it applies to**: a drug, or a drug class (`NSAID`, `ACE_INHIBITOR`, ...);
- **its condition**: a coded diagnosis, a home-medication class, a lab threshold (strictly beyond
  it; a value equal to the threshold does not fire), or a renal threshold (eGFR or
  Cockcroft-Gault CrCl, named explicitly);
- **a status and a risk tier** (`WARNING` or `BLOCKED`; `MODERATE`, `HIGH`, `CRITICAL`);
- **a reason** shown on the card (plain words; never "safe" or "approved"; no dose numbers);
- **a source**: the SmPC section (AEMPS CIMA) or the guideline it comes from. A rule with no
  source is not accepted. A design choice without an SmPC number is labelled
  **"Project policy … not SmPC text"** so nobody mistakes it for a citation;
- **a review mark** (`reviewed_by`, `reviewed_on`), empty until a clinical specialist has
  checked it. Numeric doses (renal dose guidance, alternative doses) stay hidden on the card,
  shown as "consult SmPC", until the entry is signed off.

Alternatives are keyed by (proposed drug, conflict type), come only from the rule table, and are
re-checked by the rules before they are shown.

### Proposing a rule (clinicians)

Open an issue titled `Rule proposal: <short name>` with:

1. the drug or class, the condition and the suggested status (`WARNING` / `BLOCKED`);
2. **the source**: the SmPC section (product and section number) or the guideline (authors,
   title, journal, year). If you are not sure of the exact section, say so; it is listed as an
   open question for review;
3. one or two **synthetic** cases where it should fire and one where it should not;
4. whether the conflict can appear only in free text (for example a condition written in the
   note), so the model needs a note question for it.

You don't need to write code; a maintainer turns the proposal into a rule-table entry, tests and
evaluation cases, and you review the result.

### Reviewing a rule (clinical specialists)

Read [`docs/clinical-review.md`](docs/clinical-review.md): every rule with its source, the
alternatives, the presets and the numbered questions. Reply in an issue (`Clinical review:
<rule ID>`) with "confirmed", a correction with its source, or "remove". Only after your
confirmation does a maintainer set `reviewed_by` / `reviewed_on`, which unlocks the numeric dose
for that entry. Your name is recorded only if you agree to it.

## The evaluation set

[`evals/cases.jsonl`](evals/cases.jsonl) holds synthetic emergency-department cases (one JSON
object per line, see [`evals/README.md`](evals/README.md)). Each case has the note, the coded
record, the order, the **note findings a careful clinician would extract**, and the expected
status. It is the regression guard for every change:

- `uv run pytest tests/test_eval_set.py` (no model, runs in CI) checks that every case is valid,
  that its expected statuses match the rules (the expected final status must equal the rules run
  on the record plus the expected findings), and that every rule fires in at least one case;
- `uv run python scripts/eval_set.py` (local model) measures finding precision and recall, the
  false-alarm and miss rates, and compares against the rules alone. A change to the prompt, the
  verifier, the model or a rule must not lower these without a written reason.

### Contributing cases (clinicians welcome)

The most valuable cases are the hard ones: abbreviations (`?ACS`, `NSTEMI`, `CCF`, `NKDA`),
negations (`ACS ruled out`, `not pregnant`, `stopped warfarin`), past or family history, typos,
mixed wording, and clean notes that should stay silent. Add a line to `evals/cases.jsonl` by
copying an existing case and changing it; set `expected.findings` to what the note states, and
let `tests/test_eval_set.py` tell you if the expected statuses don't match the rules. Explain in
the pull request why the case is interesting.

## Development

```bash
uv sync
uv run pytest --cov                                   # unit, API and rules tests (no model)
uv run ruff check --fix . && uv run ruff format .     # lint and format
uv run mypy src                                       # strict typing
uv run pytest -m ollama                               # real-model tests (local Ollama only)
uv run python scripts/eval_set.py                     # evaluation set with the local model
```

- **Spec first.** Requirements live in [`docs/spec/`](docs/spec/) with stable IDs (REQ-nnn,
  AC-nnn.n). A behaviour change starts with a spec change; tests are named after the acceptance
  criterion they prove (`test_ac_002_9_...`). Significant decisions get an ADR in
  [`docs/adr/`](docs/adr/).
- **Safety invariants are not negotiable** (ADR 0003, ADR 0006): the final card is never less
  strict than the rules on the coded record; the model can only escalate; doses come only from
  the reviewed rule table; note findings are kept only with a verbatim, non-negated quote; any
  model failure gives the rules-only card, never an error.
- **Privacy.** Never log, persist or cache patient context; logs use allowlisted fields only. No
  telemetry, no CDN.
- **Prompt changes** bump `PROMPT_VERSION` in `src/openmedcheck/prompt.py` and come with a fresh
  run of `scripts/eval_set.py`, recorded in `docs/measurements/`.
- Conventional Commits (`feat(rules): …`, `fix(check): …`), one logical change per pull request,
  English only.

## Code of conduct

Be kind, be precise, cite your sources, and assume good faith. Clinical disagreement is welcome
when it comes with a reference.
