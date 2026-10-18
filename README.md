<div align="center">

# OpenMedCheck

**Open-source prescribing check for emergency-department doctors.**
Flags a medication order that conflicts with the patient's labs, diagnoses or free-text note —
and stays silent when nothing conflicts. Deterministic rules decide; Gemma 4, running fully
locally, can only escalate.

[![CI](https://github.com/adricasi/OpenMedCheck/actions/workflows/ci-python.yml/badge.svg)](https://github.com/adricasi/OpenMedCheck/actions/workflows/ci-python.yml)
[![Security](https://github.com/adricasi/OpenMedCheck/actions/workflows/security.yml/badge.svg)](https://github.com/adricasi/OpenMedCheck/actions/workflows/security.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-not%20a%20medical%20device-critical)](#-disclaimer)

[Quick start](#-quick-start) ·
[How it works](#-how-it-works) ·
[Configuration](#️-configuration) ·
[Architecture](#-architecture--deployment) ·
[Contributing](#-contributing)

</div>

## ⚠️ Disclaimer

> **Not for clinical use — synthetic patients. Not a medical device.** OpenMedCheck is a concept
> demonstrator built for the DEV Hacktoberfest Open-Source AI Challenge. It works on synthetic
> patients only, gives no medical advice, and must not be used for any real patient.

## Table of contents

- [What it does](#what-it-does)
- [How it works](#-how-it-works)
- [Try it](#-try-it)
- [Quick start](#-quick-start)
- [Using the demo](#using-the-demo)
- [Configuration](#️-configuration)
- [Tests and checks](#-tests-and-checks)
- [Evaluation set](#-evaluation-set)
- [Measurements](#-measurements)
- [Architecture & deployment](#-architecture--deployment)
- [Privacy and zero egress](#-privacy-and-zero-egress)
- [Why open-weights — and who would pay](#-why-open-weights--and-who-would-pay)
- [Licence and credits](#-licence-and-credits)
- [Contributing](#-contributing)
- [Development workflow](#-development-workflow-spec-driven)

## What it does

One proposed medication order plus a synthetic patient context goes in; one triage-coded decision
card comes out: a status (`NO_ISSUE`, `WARNING` or `BLOCKED`), a risk level, a short rationale, a
renal-adjustment flag and, where the rule table allows one, an alternative drug. `NO_ISSUE` is
shown as "No issue found by these checks". The system checks orders against the diagnoses and
data it is given; it never makes diagnoses of its own.

**The doctor only writes the order.** The patient context is not meant to be typed: in a
hospital it would be pulled from the patient's record (demographics, latest labs, coded
diagnoses, current medication, allergies and the ED note) when the order is drafted, and the
card would appear inline in the existing prescribing screen — or, when nothing conflicts, no
card at all (the demo shows "No issue found by these checks" so the check's result is visible).
The check engine is the product; the web UI here is a demo harness whose editable chart and
synthetic presets stand in for that record. Record-system integration (for example HL7 FHIR
with CDS Hooks) is not implemented in v0.1 and is out of scope for this version (see
[product.md](docs/spec/product.md) non-goals).

## 🧠 How it works

Two layers, and the second can only make the first stricter (**escalate-only**):

```mermaid
flowchart LR
    O["Order + patient context<br/>(labs, diagnoses, meds, allergies, note)"] --> R
    R["Layer 1 — rules engine<br/>(deterministic, cites a source,<br/>sets the floor)"] --> C
    O -. free-text note .-> M
    M["Layer 2 — Gemma 4 E4B<br/>(reads the note, can only<br/>raise status/risk, never lower)"] --> C
    C["Combiner (pure)<br/>status = max(rules, model)"] --> D["Decision card<br/>NO_ISSUE / WARNING / BLOCKED"]
```

1. **Layer 1, deterministic rules.** A rule table in code (every entry cites a source and carries
   a review status; every current entry was reviewed by a clinical specialist on 2026-10-18, and
   an entry not yet reviewed shows "consult SmPC" instead of a numeric dose) checks the order
   against labs, allergies and listed diagnoses. It sets the floor: the final status is never
   below the rules' status, and a rules `BLOCKED` is final. The renal flag cannot be cleared, and
   the reasons of every fired rule always appear on the card.
2. **Layer 2, Gemma 4 E4B.** The local model reads the free-text ED note and can raise the status
   or risk tier. It can never lower a verdict. Alternatives are suggested by name only, drawn
   from the drug list; doses come only from the rule table (never from the model), and until a
   specialist has signed off an entry the card shows "Dose: consult SmPC" instead of a number.
   Every alternative is re-checked by Layer 1 before it is shown, and "Use alternative" in the UI
   sends the changed order through the full check again.

If the model times out, is unreachable, or returns invalid output twice, the app returns the
rules-only card instead of an error. See [design.md](docs/spec/design.md) for the details.

> **Why Layer 2 isn't a footnote:** on the 76-case evaluation set below, rules alone match the
> expected outcome on 72% of cases and miss half of everything that's only in the free-text note
> (21/42). Reading that note is Gemma's job, not the rules': adding it lifts the match rate to
> **97%** and the misses to **1/42**. Preset A — a suspected ACS visible only in the note — is
> `NO_ISSUE` from rules alone and `BLOCKED` only once Gemma reads it. Full numbers: see
> [Evaluation set](#-evaluation-set).

## 🚀 Try it

OpenMedCheck is built to **run on-premises inside the hospital**, so patient context never leaves
the building. There is no hosted demo: v0.1 ships local-only
([ADR 0008](docs/adr/0008-drop-opt-in-hosted-demo.md)).

**Demo video/GIF:** [to be added by the human before submission — T-012].

| Run it | Command | Details |
|---|---|---|
| **Docker (recommended)** | `docker compose --profile setup run --rm model-pull && docker compose up --build`, then open <http://127.0.0.1:8000> | [docs/deploy/local-docker.md](docs/deploy/local-docker.md) |
| **uv (for development)** | see [Quick start](#-quick-start) below | — |

For how this would run in a hospital's own cloud instead of on one laptop, see the documented
(not implemented) GCP reference architecture:
[docs/deploy/gcp-reference-architecture.md](docs/deploy/gcp-reference-architecture.md) and
[ADR 0005](docs/adr/0005-gcp-reference-architecture-documented-only.md).

## 📦 Quick start

Requirements: Linux, macOS or WSL with Python 3.12+, git, [uv](https://docs.astral.sh/uv/),
[Ollama](https://ollama.com/) and a GPU with at least 8 GB of VRAM for the latency figures below.
Network access is needed once, to install the Python packages and pull the model; the running
app makes no other outbound call.

```bash
git clone https://github.com/adricasi/OpenMedCheck.git && cd OpenMedCheck
ollama pull gemma4:e4b      # the model (about 6.6 GB); Ollama must be running on 127.0.0.1:11434
ollama list                 # check that gemma4:e4b is listed
uv sync                     # install the Python environment
uv run openmedcheck         # serve the app (leave it running)
```

Then open <http://127.0.0.1:8000> in a browser. The page shows the disclaimer banner and three
rooms with synthetic ED patients (Bed 3, Bed 7 and Bed 12, which are presets A, B and C).

## Using the demo

1. Select a room: its simulated record opens read-only and the prescription is empty.
2. Write a prescription, or press "Auto-fill test prescription" for the case's demo order.
3. Press "Verify prescription": the page shows "Verifying the prescription with Gemma…", then
   one card (rules and Gemma combined, or rules only if the model is unavailable).

"Add room" creates a room from one of six template patients (A–F; D, E and F add a coded GI
bleed, a penicillin allergy and reduced kidney function). "Add patient" opens an empty record to
fill in, including conditions, chronic medication and allergies; "Save patient" keeps it. Added
rooms and patients exist only in the open page: nothing is stored, and a reload shows the three
predefined rooms again. "Edit scenario (demo only)" unlocks a record so you can try other cases,
and "What the record system would send" shows the request body. When the page loads it asks the
server to warm the model up. A first check right after Ollama starts can take longer than the
10 s model deadline; the card then falls back to rules only (see below). Wait for the model
status to read ready and verify again.

What each template shows after "Auto-fill test prescription" and "Verify prescription", with
the model ready (the rules column is what `/api/check/rules` returns):

| Template (room) | Rules card | Final card |
|---|---|---|
| A (Bed 3) | `NO_ISSUE` ("No issue found by these checks") | `BLOCKED` after the model reads the note; alternative: Paracetamol 1 g, PO, every 8 hours |
| B (Bed 7) | `WARNING` with the renal-adjustment flag | `WARNING`, renal flag kept, "Renal adjustment required — consult SmPC", no alternative |
| C (Bed 12) | `NO_ISSUE` | `NO_ISSUE`, no alternative |
| D (added room) | `BLOCKED`: NSAID with a coded active GI bleed | `BLOCKED`; alternative: Paracetamol 1 g, PO, every 8 hours |
| E (added room) | `BLOCKED`: recorded penicillin allergy | `BLOCKED`, no alternative |
| F (added room) | `BLOCKED`: dexketoprofen with estimated CrCl below 60 mL/min, renal flag | `BLOCKED`, renal flag kept; alternative: Paracetamol 1 g, PO, every 8 hours |

"Use alternative" on preset A fills in the specialist-reviewed rule-table dose (paracetamol 1 g,
PO, every 8 hours) and verifies the changed order again on the same patient; that second check
gives `NO_ISSUE` ("No issue found by these checks"). An alternative whose dose is not reviewed is
offered by name only, and the prescriber enters the dose. The prescriber always decides.

If Ollama or the model is missing, or does not answer in time, the app still starts and returns
the rules-only card with the note "Model check unavailable — rules only". The rules alone cannot
read the free-text note, so when they find nothing the card is a `WARNING` "Free-text note not
checked" instead of "No issue found by these checks" (a check that could not check the note must
not look like a pass; rule findings such as preset B's are shown unchanged). To try it, start a
second instance:
```bash
OPENMEDCHECK_OLLAMA_URL=http://127.0.0.1:9 OPENMEDCHECK_PORT=8001 uv run openmedcheck
```

The checks are also available over HTTP: `GET /api/presets/{A–F}` returns a request body
that you can `POST` as JSON to `/api/check/rules` (rules only) or `/api/check` (final card), and
`GET /api/model/health` reports `ready`, `warming` or `unavailable`.

## ⚙️ Configuration

All settings are environment variables read at start-up (`src/openmedcheck/config.py`). The app
refuses to start with an invalid value.

| Variable | Default | Meaning |
|---|---|---|
| `OPENMEDCHECK_HOST` | `127.0.0.1` | Address to bind. Must be `localhost`, `127.0.0.1` or `::1` unless `OPENMEDCHECK_ALLOW_NONLOCAL=1`. |
| `OPENMEDCHECK_PORT` | `8000` | Port to bind (1-65535). |
| `OPENMEDCHECK_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama base URL (`http` or `https`). Same loopback rule. |
| `OPENMEDCHECK_MODEL` | `gemma4:e4b` | Model tag served by Ollama; must not be empty. |
| `OPENMEDCHECK_MODEL_TIMEOUT_S` | `10.0` | Total model deadline in seconds across the first attempt and the retry; must be a positive, finite number. |
| `OPENMEDCHECK_ALLOW_NONLOCAL` | `0` | Explicit opt-in (REQ-015) to allow a non-loopback bind host or Ollama URL. Leave it at `0` for the zero-egress guarantee — v0.1 has no deployment that needs `1` (see [Architecture & deployment](#-architecture--deployment)). |
| `OPENMEDCHECK_PUBLIC_HOSTS` | empty | Comma-separated host names accepted in the Host header, shown with the "hosted for trying it" notice. Needs `OPENMEDCHECK_ALLOW_NONLOCAL=1`. Unused in v0.1. |
| `OPENMEDCHECK_OLLAMA_API_KEY` | empty | Secret sent as `Authorization: Bearer` to a non-local model host. Needs an `https://` Ollama URL (unless Ollama is on loopback). Never logged or returned. Unused in v0.1. |
| `PORT` | unset | Platform port, used only when `OPENMEDCHECK_PORT` is unset. |

## ✅ Tests and checks

```bash
uv run pytest --cov                                  # tests with coverage
uv run ruff check --fix . && uv run ruff format .    # lint + format
uv run mypy src                                      # type check (strict)
uv run pip-audit                                     # dependency vulnerabilities
uv run pytest -m ollama                              # real-model tests (local only, not in CI)
```

Unit, service and API tests use a fake model client; only the `-m ollama` tests call a real
model.

## 🧪 Evaluation set

An open set of **76 synthetic ED cases** ([evals/](evals/README.md)) covers every rule, notes
where the conflict is only in free text, negations ("ACS ruled out", "not pregnant", "stopped
warfarin"), past and family history, abbreviations, typos and clean notes that must stay silent.
Each case states the findings the authors expect the note to state (not yet reviewed by a
clinician), and a test keeps every case consistent with the rules. Result on the same machine
([comparison](docs/measurements/2026-10-18-model-comparison.md)):

| | Final status matches label | False alarms | Misses | Model step p50 |
|---|---|---|---|---|
| Rules only | 72% | 0/34 | 21/42 (50%) | n/a |
| **Rules + Gemma 4 E4B** | **97%** | **0/34** | **1/42 (2%)** | 1.87 s |
| Rules + Gemma 3 4B | 78% | 5/34 | 11/42 | 5.59 s |
| Rules + Gemma 4 12B | 80% | 0/34 | 14/42 (timeouts on an 8 GB GPU) | 9.62 s |

Note findings from Gemma 4 E4B: 100% precision for every type, 100% recall except allergy (5/6)
and active GI bleed (3/4). The cases, prompt and verifier were developed together, so 97% is a
development-set figure, not a held-out estimate. Run it yourself:
`uv run python scripts/eval_set.py [--model <tag>]`. Synthetic notes, temperature 0: this
measures coverage of wordings, not clinical validity.

## 📊 Measurements

Measured on one machine (NVIDIA RTX 3000 Ada Laptop GPU, 8188 MiB; Ollama 0.35.1; `gemma4:e4b`,
`think: false`, temperature 0), model step, warm, unless stated:

- [T-001 spike](docs/measurements/2026-10-17-spike.md): 30/30 valid on the first try in both
  runs; model-step p95 1.73 s (draft prompt) and 2.40 s (with conflict guidance), against the
  NFR-004 budget of 3 s for the final card.
- [Prompt v2 evaluation](docs/measurements/2026-10-17-prompt-v2.md): 60/60 = 100% valid on the
  first try (20 per preset); model-step p95 1.50 s (A), 1.32 s (B), 1.44 s (C); preset A (20
  calls) was BLOCKED with ANTIPLATELET_ACS in 20/20 (AC-003.4 asks for at least 9/10), with the
  rules alone giving `NO_ISSUE`.
- [Prompt v3 evaluation](docs/measurements/2026-10-17-prompt-v3.md): 60/60 valid on the first
  try (15 per case, through the full check pipeline); preset A `BLOCKED` with ANTIPLATELET_ACS
  15/15, preset A re-checked with paracetamol `NO_ISSUE` 15/15, B `WARNING` with the renal flag,
  C `NO_ISSUE`; model-step p95 at most 1.50 s.
- [English presets and prompt v4](docs/measurements/2026-10-18-prompt-v4.md): after the presets
  were translated to English, prompt v3 blocked the paracetamol re-check 15/15. v4 sends the
  ANTIPLATELET_ACS guidance only when the order is an NSAID (a fact from the drug list). Then
  60/60 valid on the first try; preset A `BLOCKED` 15/15, paracetamol re-check `NO_ISSUE` 15/15,
  B `WARNING`, C `NO_ISSUE`; end to end rules card p95 2.0 ms, final card p95 1.45 s (40 calls);
  cold first check 6.9 s with the model's reading (one sample).
- Earlier (prompt v3, Spanish notes): [end-to-end measurement (T-009)](docs/measurements/2026-10-17.md),
  as a client sees the app over HTTP: rules card p50 1.3 ms, p95 3.8 ms (200 calls, budget
  200 ms); final card, warm, p50 1.51 s, p95 1.72 s (40 calls over presets A, B, C and A with
  paracetamol, budget 3 s); 40/40 cards had valid model output; preset A `BLOCKED` and A with
  paracetamol `NO_ISSUE` in every run. A cold first check took 10.0 s and fell back to the
  rules-only card (the model load exceeds the 10 s deadline on this laptop); the warm-up call
  the UI makes on page load avoids this.

At temperature 0 repeated calls on one fixed preset are nearly deterministic, so these figures
show stability on three presets, not robustness to other wordings. Each measurement file lists
its caveats.

## 🏗️ Architecture & deployment

- [Specification](docs/spec/): [product](docs/spec/product.md),
  [requirements](docs/spec/requirements.md), [design](docs/spec/design.md) and
  [tasks](docs/spec/tasks.md).
- Architecture decisions in [docs/adr](docs/adr/):
  [0002 local FastAPI app with server-rendered UI](docs/adr/0002-local-fastapi-app-with-server-rendered-ui.md),
  [0003 escalate-only two-layer engine](docs/adr/0003-escalate-only-two-layer-engine.md),
  [0004 Gemma 4 E4B served locally with Ollama](docs/adr/0004-serve-gemma-4-e4b-locally-with-ollama.md),
  [0005 GCP reference architecture, documented only](docs/adr/0005-gcp-reference-architecture-documented-only.md),
  [0008 dropped the opt-in hosted demo](docs/adr/0008-drop-opt-in-hosted-demo.md).
- Deployment guides in [docs/deploy](docs/deploy/):
  [local Docker](docs/deploy/local-docker.md) (the only one actually run) and the
  [GCP reference architecture](docs/deploy/gcp-reference-architecture.md) (documented, not
  implemented).
- **Version 0.1 runs locally only.** The GCP deployment is documented, not implemented, and no
  cloud resources are created.

## 🔒 Privacy and zero egress

- The app binds to `127.0.0.1` by default. The only outbound connection is to the configured
  Ollama URL (default `http://127.0.0.1:11434`). There is no telemetry and no CDN: the UI
  assets are served locally (NFR-001).
- Patient data is synthetic, but it is treated as special-category health data: nothing from the
  patient context (note, labs, medications, allergies, demographics) is written to logs, disk or
  caches. Logs carry only allowlisted fields such as request ID, rule IDs fired, statuses and
  timings (NFR-002).

## 💰 Why open-weights — and who would pay

Built for the DEV Hacktoberfest Open-Source AI Challenge, whose Week 2 brief asks for something
built with open-weight models or open-source AI that someone would actually pay for.

**Why open-weights, specifically:**
- **Privacy.** Patient context is special-category health data. Because Gemma 4 is open-weights
  and runs through Ollama, inference stays on the machine that's already running the app — no
  prompt or patient context goes to a third-party model API (see [Privacy and zero
  egress](#-privacy-and-zero-egress)).
- **Cost.** Inference runs on local/self-hosted GPU hardware; there is no per-call model fee.
- **Auditability.** The safety floor is plain, reviewed code and a cited rule table a pharmacist
  can read — Gemma can only escalate it, never weaken it (see [How it works](#-how-it-works)).
  That invariant is checkable because the model is swappable and inspectable, not a black-box
  API.
- **No lock-in.** The model tag is one configuration value (`OPENMEDCHECK_MODEL`); fine-tuning
  on a hospital's own note style is a possible next step, not something a hosted API vendor
  would need to agree to first.

**Who would pay (a hypothesis, not a claim — this has not been validated with real
conversations):** not the ED doctor directly, but an organisation that needs an on-premises,
auditable check next to its existing prescribing system — hospital IT/clinical-informatics
teams and pharmacy services wanting a self-hosted, reviewable layer on top of a vendor module,
or EHR/clinical-decision-support vendors wanting an open, escalate-only component they can
embed and inspect. A plausible model is support, rule-table maintenance and integration around
the open-source core, not a licence fee for the core itself.

**Regulatory reality, stated plainly:** used on real patients this would involve
special-category health data under GDPR (Art. 9) and, on this reading, medical-device software
under the EU MDR (likely class IIa–IIb), needing a conformity assessment and CE marking.
**OpenMedCheck is none of that.** It has no clinical validation and makes no performance claim
on real patients. See the [research notes](docs/discovery/research-notes.md) for the
sourced alert-fatigue figures.

## 📄 Licence and credits

Licensed under the [Apache License 2.0](LICENSE). Copyright 2026 adricasi.

The language model is Gemma 4, developed by Google and used here through Ollama. Gemma is
provided under and subject to the Gemma Terms of Use: <https://ai.google.dev/gemma/terms>. The
model weights are not part of this repository.

Clinical content in the rule table is a demonstrator and has not been signed off for clinical
use; see [docs/clinical-review.md](docs/clinical-review.md) for the review status and open
questions for a specialist.

## 🤝 Contributing

Clinicians and developers are welcome: propose a rule with its source, review a rule, or add
synthetic evaluation cases. See [CONTRIBUTING.md](CONTRIBUTING.md).

## 🛠️ Development workflow (spec-driven)

The specification in
`docs/spec/` is the source of truth, and each task is implemented from it with tests named after
the acceptance criteria. Commits run pre-commit (formatters, linters, gitleaks); a human reviews
and merges pull requests.
