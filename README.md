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

## How it works

Two layers, and the second can only make the first stricter (escalate-only):

1. **Layer 1, deterministic rules.** A rule table in code (every entry cites a source and carries
   a review status; entries not yet reviewed by a specialist show "consult SmPC" instead of a
   numeric dose) checks the order against labs, allergies and listed diagnoses. It
   sets the floor: the final status is never below the rules' status, and a rules `BLOCKED` is
   final. The renal flag cannot be cleared, and the reasons of every fired rule always appear
   on the card.
2. **Layer 2, Gemma 4 E4B.** The local model reads the free-text ED note and can raise the
   status or risk tier. It can never lower a verdict. Alternatives are drawn only from the drug
   list, doses only from the rule table (never from the model), and every alternative is
   re-checked by Layer 1 before it is shown.

If the model times out, is unreachable or returns invalid output twice, the app returns the
rules-only card instead of an error. See [design.md](docs/spec/design.md) for the details.

## Quick start

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com/) and a
GPU with at least 8 GB of VRAM for the latency figures below.

```bash
ollama pull gemma4:e4b      # the model; Ollama must be running on 127.0.0.1:11434
uv sync                     # install the Python environment
uv run openmedcheck         # serve the app
```

Then open <http://127.0.0.1:8000>. The three synthetic presets A, B and C are evaluated from the
UI. If Ollama or the model is missing, the app still starts and shows rules-only cards.

TODO(T-007/T-005b): confirm the model layer, `/api/check` and the preset UI described here in the fresh-clone run-through (T-010); UI walkthrough with screenshots of presets A, B and C.
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
