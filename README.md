# openmedcheck

Open-source prescribing check for emergency-department doctors: it flags a proposed medication
order that conflicts with the patient's labs, diagnoses or free-text note, and stays silent when
nothing conflicts (the card then reads "No issue found by these checks"). Gemma 4 runs locally.

> **Not for clinical use — synthetic patients. Not a medical device.** OpenMedCheck is a concept
> demonstrator built for the DEV Hacktoberfest Open-Source AI Challenge. It works on synthetic
> patients only, gives no medical advice and must not be used for any real patient.

## What it does

One proposed medication order plus a synthetic patient context goes in; one triage-coded decision
card comes out: a status (`NO_ISSUE`, `WARNING` or `BLOCKED`), a risk level, a short rationale, a
renal-adjustment flag and, where the rule table allows one, an alternative drug. `NO_ISSUE` is
shown as "No issue found by these checks". The system checks orders against the diagnoses and
data it is given; it never makes diagnoses of its own.

**The doctor only writes the order.** The patient context is not meant to be typed: in a
hospital it would be pulled from the patient's record (demographics, latest labs, coded
diagnoses, current medication, allergies and the ED note) when the order is drafted, and the
card would appear inline in the existing prescribing screen, or, when nothing conflicts, no
card at all (the demo shows "No issue found by these checks"). The check engine is the
product; the web UI here is a demo harness whose editable chart and synthetic presets stand in
for that record. Record-system integration (for example HL7 FHIR with CDS Hooks) is not
implemented in v0.1 and is out of scope for this version (see
[product.md](docs/spec/product.md) non-goals).

## How it works

Two layers, and the second can only make the first stricter (escalate-only):

1. **Layer 1, deterministic rules.** A rule table in code (every entry cites a source and carries
   a review status; entries not yet reviewed by a specialist show "consult SmPC" instead of a
   numeric dose) checks the order against labs, allergies and listed diagnoses. It
   sets the floor: the final status is never below the rules' status, and a rules `BLOCKED` is
   final. The renal flag cannot be cleared, and the reasons of every fired rule always appear
   on the card.
2. **Layer 2, Gemma 4 E4B.** The local model reads the free-text ED note and can raise the
   status or risk tier. It can never lower a verdict. Alternatives are suggested by name only,
   drawn from the drug list; doses come only from the rule table (never from the model), and
   until a specialist has signed off an entry the card shows "Dose: consult SmPC" instead of a
   number. Every alternative is re-checked by Layer 1 before it is shown, and "Use alternative"
   in the UI sends the changed order through the full check again.

If the model times out, is unreachable or returns invalid output twice, the app returns the
rules-only card instead of an error. See [design.md](docs/spec/design.md) for the details.

## Quick start

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

Then open <http://127.0.0.1:8000> in a browser. The page shows the banner "Not for clinical use —
synthetic patients" and three synthetic presets, A, B and C, that you evaluate from the UI. When
the page loads it asks the server to warm the model up. A first check right after Ollama starts
can take longer than the 10 s model deadline; the card then falls back to rules only (see
below). Wait for the model status to read ready and check again.

What each preset shows with the model ready:

| Preset | Rules card (instant) | Final card |
|---|---|---|
| A | `NO_ISSUE` ("No issue found by these checks") | `BLOCKED` after the model reads the note; alternative: Paracetamol, "Dose: consult SmPC" |
| B | `WARNING` with the renal-adjustment flag | `WARNING`, renal flag kept, "Renal adjustment required — consult SmPC", no alternative |
| C | `NO_ISSUE` | `NO_ISSUE`, no alternative |

"Use alternative" on preset A swaps the order for the alternative and runs the full check again
on the same patient; in the recorded runs that second check gives `NO_ISSUE` ("No issue found
by these checks"). The prescriber always decides.

If Ollama or the model is missing, or does not answer in time, the app still starts and returns
the rules-only card with the note "Model check unavailable — rules only". The rules alone cannot
read the free-text note, so preset A then stays `NO_ISSUE`; the note on the card says why. To
try it, start a second instance:
`OPENMEDCHECK_OLLAMA_URL=http://127.0.0.1:9 OPENMEDCHECK_PORT=8001 uv run openmedcheck`.

The checks are also available over HTTP: `GET /api/presets/{A|B|C}` returns a request body
that you can `POST` as JSON to `/api/check/rules` (rules only) or `/api/check` (final card), and
`GET /api/model/health` reports `ready`, `warming` or `unavailable`.
TODO(T-012): link the demo video.

## Configuration

All settings are environment variables read at start-up (`src/openmedcheck/config.py`).

| Variable | Default | Meaning |
|---|---|---|
| `OPENMEDCHECK_HOST` | `127.0.0.1` | Address to bind. Must be `localhost`, `127.0.0.1` or `::1` unless `OPENMEDCHECK_ALLOW_NONLOCAL=1`. |
| `OPENMEDCHECK_PORT` | `8000` | Port to bind (1-65535). |
| `OPENMEDCHECK_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama base URL (`http` or `https`). Same loopback rule. |
| `OPENMEDCHECK_MODEL` | `gemma4:e4b` | Model tag served by Ollama; must not be empty. |
| `OPENMEDCHECK_MODEL_TIMEOUT_S` | `10.0` | Total model deadline in seconds across the first attempt and the retry; must be a positive, finite number. |
| `OPENMEDCHECK_ALLOW_NONLOCAL` | `0` | Set to `1` to allow a non-loopback bind host or Ollama URL. Leave it at `0` for the zero-egress guarantee. |

The app refuses to start with an invalid value.

## Tests and checks

```bash
uv run pytest --cov                                  # tests with coverage
uv run ruff check --fix . && uv run ruff format .    # lint + format
uv run mypy src                                      # type check (strict)
uv run pip-audit                                     # dependency vulnerabilities
uv run pytest -m ollama                              # real-model tests (local only, not in CI)
```

Unit, service and API tests use a fake model client; only the `-m ollama` tests call a real
model.

## Measurements

Measured on one machine (NVIDIA RTX 3000 Ada Laptop GPU, 8188 MiB; Ollama 0.35.1; `gemma4:e4b`,
`think: false`, temperature 0), model step only, warm:

- [T-001 spike](docs/measurements/2026-10-17-spike.md): 30/30 valid on the first try in both
  runs; model-step p95 1.73 s (draft prompt) and 2.40 s (with conflict guidance), against the
  NFR-004 budget of 3 s for the final card.
- [Prompt v2 evaluation](docs/measurements/2026-10-17-prompt-v2.md): 60/60 = 100% valid on the
  first try (20 per preset); model-step p95 1.50 s (A), 1.32 s (B), 1.44 s (C); preset A (20 calls) was BLOCKED with
  ANTIPLATELET_ACS in 20/20 (AC-003.4 asks for at least 9/10), with the rules alone giving
  `NO_ISSUE`.

- [Prompt v3 evaluation](docs/measurements/2026-10-17-prompt-v3.md): 60/60 valid on the first
  try (15 per case, through the full check pipeline); preset A `BLOCKED` with ANTIPLATELET_ACS
  15/15, preset A re-checked with paracetamol `NO_ISSUE` 15/15, B `WARNING` with the renal flag,
  C `NO_ISSUE`; model-step p95 at most 1.50 s.

At temperature 0 repeated calls on one fixed preset are nearly deterministic, so these figures
show stability on three presets, not robustness to other wordings. Both documents list their
caveats.

- [End-to-end measurement (T-009)](docs/measurements/2026-10-17.md), as a client sees the app over
  HTTP: rules card p50 1.3 ms, p95 3.8 ms (200 calls, budget 200 ms); final card, warm, p50
  1.51 s, p95 1.72 s (40 calls over presets A, B, C and A with paracetamol, budget 3 s); 40/40
  cards had valid model output; preset A `BLOCKED` and A with paracetamol `NO_ISSUE` in every
  run. A cold first check took 10.0 s and fell back to the rules-only card (the model load
  exceeds the 10 s deadline on this laptop); the warm-up call the UI makes on page load avoids
  this.

## Architecture

- [Specification](docs/spec/): [product](docs/spec/product.md),
  [requirements](docs/spec/requirements.md), [design](docs/spec/design.md) and
  [tasks](docs/spec/tasks.md).
- Architecture decisions in [docs/adr](docs/adr/):
  [0002 local FastAPI app with server-rendered UI](docs/adr/0002-local-fastapi-app-with-server-rendered-ui.md),
  [0003 escalate-only two-layer engine](docs/adr/0003-escalate-only-two-layer-engine.md),
  [0004 Gemma 4 E4B served locally with Ollama](docs/adr/0004-serve-gemma-4-e4b-locally-with-ollama.md),
  [0005 GCP reference architecture, documented only](docs/adr/0005-gcp-reference-architecture-documented-only.md).
- Version 0.1 runs locally only. The GCP deployment is documented, not implemented, and no
  cloud resources are created.

## Privacy and zero egress

- The app binds to `127.0.0.1` by default. The only outbound connection is to the configured
  Ollama URL (default `http://127.0.0.1:11434`). There is no telemetry and no CDN: the UI
  assets are served locally (NFR-001).
- Patient data is synthetic, but it is treated as special-category health data: nothing from the
  patient context (note, labs, medications, allergies, demographics) is written to logs, disk or
  caches. Logs carry only allowlisted fields such as request ID, rule IDs fired, statuses and
  timings (NFR-002).

## Licence and credits

Licensed under the [Apache License 2.0](LICENSE). Copyright 2026 adricasi.

The language model is Gemma 4, developed by Google and used here through Ollama. Gemma is
provided under and subject to the Gemma Terms of Use: <https://ai.google.dev/gemma/terms>. The
model weights are not part of this repository.

Clinical content in the rule table is a demonstrator and has not been signed off for clinical
use; see [docs/clinical-review.md](docs/clinical-review.md) for the review status and open
questions for a specialist.

## Development workflow (spec-driven)

The specification in
`docs/spec/` is the source of truth, and each task is implemented from it with tests named after
the acceptance criteria. Commits run pre-commit (formatters, linters, gitleaks); a human reviews
and merges pull requests.
