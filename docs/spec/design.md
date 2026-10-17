# Design: OpenMedCheck

- Status: Approved <!-- Draft | In review | Approved -->
- Last updated: 2026-10-17
- Implements: requirements.md (REQ-001 … REQ-014, NFR-001 … NFR-012)

## Overview
One local Python process (FastAPI) serves the page, the static assets and a JSON API. Each
check runs the deterministic **rules engine** first (Layer 1). The browser shows that card
straight away. The **check service** then asks a local **Ollama** server running Gemma 4 E4B
(Layer 2) for a schema-constrained verdict, validates it and merges it with the rules verdict in
a pure, **escalate-only combiner**. Any model alternative is re-checked by the rules before it is
shown. If the model is slow, down or wrong twice, the rules card is final. Nothing is stored;
logs carry no patient data. The GCP deployment is a documented plan only (§ GCP reference
architecture).

```mermaid
flowchart LR
  subgraph Browser
    ui[Page: chart left / card right]
  end
  subgraph App["openmedcheck (FastAPI, 127.0.0.1)"]
    api[JSON API]
    rules[Rules engine<br/>Layer 1 + rule table]
    svc[Check service]
    comb[Escalate-only combiner]
    mc[ModelClient]
  end
  ollama[(Ollama 127.0.0.1:11434<br/>gemma4:e4b)]
  ui -- "1. POST /api/check/rules" --> api --> rules
  ui -- "2. POST /api/check" --> api --> svc
  svc --> rules
  svc --> mc -- "JSON-schema format" --> ollama
  svc --> comb
  comb -- "re-check alternative" --> rules
```

## Options considered
| Decision | Options | Chosen | ADR |
|---|---|---|---|
| App and UI | FastAPI + Jinja2 + vanilla JS · FastAPI + React SPA · Streamlit/Gradio | FastAPI + Jinja2 + vanilla JS: one toolchain, testable API, no CDN | [0002](../adr/0002-local-fastapi-app-with-server-rendered-ui.md) |
| Safety engine | Rules → model → escalate-only combiner · model decides with rule veto · rules only | Escalate-only combiner, rules-only as fail-safe | [0003](../adr/0003-escalate-only-two-layer-engine.md) |
| Model serving | Ollama + JSON schema · vLLM · llama.cpp + GBNF · hosted API | Ollama `gemma4:e4b`, `httpx`, no SDK | [0004](../adr/0004-serve-gemma-4-e4b-locally-with-ollama.md) |
| Cloud target | Cloud Run + L4 internal · same + min=1 · Vertex + PSC · GCE spot · hosted API | Cloud Run + L4 internal, **documented only** | [0005](../adr/0005-gcp-reference-architecture-documented-only.md) |
| Progressive display | Two API calls · one call with SSE/streaming | Two calls: `/api/check/rules` (instant), `/api/check` (final, recomputes rules server-side). No streaming (REQ-008) | — (minor) |
| Rule table format | Python module of typed dataclasses · YAML + schema | Python module: mypy-checked, no YAML dependency; a script renders it to Markdown for the specialist | — (minor) |

## Components
| Component | Responsibility | Tech | Requirements |
|---|---|---|---|
| `contracts` | Pydantic models for PatientContext, Order, RulesVerdict, ModelVerdict, DecisionCard, problem details; range validation | Pydantic v2 | REQ-001, AC-001.4 |
| `renal` | Cockcroft-Gault CrCl from age, weight, sex, creatinine | Pure Python | AC-002.7 |
| `rule_table` | Drug list (~15), drug classes, renal thresholds, contraindication rules, allowed alternatives with rule-table doses, source citations, review marks | Python module (data) | REQ-002, NFR-011 |
| `rules_engine` | Applies all rules to a context + order → RulesVerdict; no I/O | Pure Python | REQ-002, AC-001.5, REQ-005 |
| `prompt` | Versioned system prompt + per-request user message; note is delimited as untrusted data; card JSON schema built per request (alternative enum = allowed alternatives for this drug) | Python | REQ-003, AC-003.5 |
| `model_client` | `ModelClient` protocol; `OllamaClient` (httpx, `/api/chat`, `format`=schema, temperature 0, timeout); `FakeModelClient` for tests | httpx | REQ-003, REQ-005, NFR-004 |
| `combiner` | Pure escalate-only merge of RulesVerdict + ModelVerdict; text-source selection; flags union | Pure Python | REQ-004 |
| `check_service` | Orchestrates rules → model (validate, retry once) → combine → alternative re-check → DecisionCard; timing; one log line | Python | REQ-001, REQ-003–005, NFR-007 |
| `presets` | Synthetic presets A, B, C | Python data | REQ-006 |
| `web` | FastAPI app, routes, Jinja2 template, static CSS/JS, trusted-host and body-size middleware, model health/warm-up | FastAPI, Jinja2, uvicorn | REQ-007–011, REQ-014, NFR-001 |
| `logging_setup` | JSON log formatter, allowlisted fields only | stdlib `logging` | NFR-002, NFR-007 |
| `config` | Reads and validates environment variables | stdlib + explicit validation | AC-011.3 |
| `scripts/measure.py` | 20+ calls over presets → p50/p95, valid-output rate → `docs/measurements/` | Python | REQ-012, NFR-004, NFR-012 |
| `scripts/render_rule_table.py` | Rule table → `docs/clinical-review.md` table for the specialist | Python | NFR-011 |

## Data model
No persistence. All data is synthetic, in memory for one request only, classified as
**special-category health data (treated as if real)** for logging and exposure rules (NFR-002).

- **PatientContext**: `patient_id` (synthetic label), `age` (18–110), `sex` (`M`/`F`),
  `weight_kg` (30–250), `reason_for_consult` (≤ 200 chars), `ed_note` (free text, ≤ 2,000 chars),
  `diagnoses[]` (coded, from a small fixed list, e.g. `ACS`, `ACTIVE_GI_BLEED`),
  `chronic_medications[]` (drug IDs from the drug list), `allergies[]` (active ingredient or
  class IDs), `labs`: `creatinine_mg_dl` (0.1–20, optional), `egfr_ml_min_1_73m2` (0–200,
  optional), `potassium_mmol_l` (1.5–9, optional), `platelets_per_ul` (1,000–2,000,000,
  optional).
- **Order**: `drug_id` (drug list), `dose_text`, `route` (`PO`/`IV`/`IM`/`SC`), `frequency`.
- **RulesVerdict**: `status`, `risk_level`, `fired_rules[]` (`rule_id`, fixed `reason`),
  `renal_adjustment_required`, `crcl_ml_min` (if computed), `rule_alternative` (or none).
- **ModelVerdict** (validated model output): `status`, `risk_level`, `headline` (≤ 8 words),
  `rationale` (≤ 2 sentences, ≤ 300 chars), `renal_adjustment_required`, `conflict_type`
  (enum, required when it escalates), `alternative_drug_id` (enum of allowed alternatives for
  this drug, or null). The model never supplies a dose; doses come from the rule table. After
  schema validation, a content check rejects dose patterns, other drug-list names and banned
  words in the headline/rationale (AC-003.5).
- **DecisionCard**: `status`, `risk_level`, `headline`, `rationale`, `fired_rules[]`,
  `renal_adjustment_required`, `crcl_ml_min`, `alternative` (`drug_id`, display name,
  `dose_text`, `route`, `frequency`, `reason`) or null, `source` (`rules` / `rules+model`),
  `model_note` (e.g. "Model check unavailable — rules only"), `request_id`.
- **Rule table entry**: `rule_id`, applies-to (drug IDs or classes), condition, resulting
  `status`/`risk_level`, `conflict_type`, `reason`, `source` (citation URL/text),
  `reviewed_by`/`reviewed_on` (or null → numeric doses suppressed).
- **Allowed alternatives**: keyed by (proposed drug, conflict type) → ordered list of
  (`drug_id`, `dose_text`, `route`, `frequency`, `source`, review mark). Example: (dexketoprofen,
  `ANTIPLATELET_ACS`) → paracetamol. An alternative with an unreviewed dose is offered by name
  only, with "Dose: consult SmPC" (no numeric dose).

Candidate drug list (final list set during the clinical review, Q-5): NSAIDs (dexketoprofen,
ibuprofen, naproxen, diclofenac); other analgesics (paracetamol, metamizole, tramadol, morphine);
antibiotics (ciprofloxacin, levofloxacin, amoxicillin-clavulanate); antiplatelets as home
medication (aspirin, clopidogrel); plus enoxaparin and metformin. All thresholds and doses
come from the cited SmPC, not from this document. [ASSUMPTION A-7]

## Interfaces
JSON over HTTP on `127.0.0.1:${OPENMEDCHECK_PORT}`. Errors use RFC 9457
`application/problem+json` with field-level `errors[]`. Version: unversioned `/api/*` for v0.1
(local only, single client).

| Method + path | Purpose | Response |
|---|---|---|
| `GET /` | Page (banner, chart, card area) | HTML |
| `GET /api/drugs` | Drug list for the dropdown | `[{drug_id, name, active_ingredient, class}]` |
| `GET /api/presets`, `GET /api/presets/{id}` | Synthetic presets | PatientContext + Order |
| `POST /api/check/rules` | Layer 1 only, instant card | DecisionCard with `source=rules` |
| `POST /api/check` | Full check (rules + model + combiner) | DecisionCard |
| `GET /api/model/health` | `ready` / `warming` / `unavailable` + model tag | JSON |
| `POST /api/model/warmup` | One warm-up call (REQ-014) | 202 |

Request body for both checks: `{ "context": PatientContext, "order": Order }`. Status codes:
200 card · 413 body > 16 KB · 415 not JSON · 422 validation error (fields listed) · 500 only for
bugs (never for model failures, which return a rules-only 200).

Ollama call: `POST ${OPENMEDCHECK_OLLAMA_URL}/api/chat`, `stream=false`, `format=<card schema>`,
`options.temperature=0`, `keep_alive` long enough to stay warm between demo calls.

Configuration (environment variables, defaults): `OPENMEDCHECK_HOST=127.0.0.1`,
`OPENMEDCHECK_PORT=8000`, `OPENMEDCHECK_OLLAMA_URL=http://127.0.0.1:11434`,
`OPENMEDCHECK_MODEL=gemma4:e4b`, `OPENMEDCHECK_MODEL_TIMEOUT_S=10` (total deadline across the
attempt and the retry), `OPENMEDCHECK_ALLOW_NONLOCAL=0` (the app refuses to start with a
non-loopback host or Ollama URL unless set; AC-011.4).

## Check flow and the invariant
1. Validate input (Pydantic) → 422 on error, nothing evaluated.
2. Rules engine → RulesVerdict (also returned alone by `/api/check/rules`).
3. Build prompt (system prompt + context + order + rules verdict + allowed alternatives); call
   the model with the per-request schema; validate schema, then content (AC-003.5); retry once
   on invalid. One 10 s deadline covers both attempts; on expiry → fallback.
4. Combiner (pure):
   - status = max(rules, model); risk = max(rules, model); renal flag = rules OR model; if the
     renal flag is set, status = max(status, `WARNING`).
   - Strictness compares status, then tier. Text: if the model verdict is at least as strict as
     the rules verdict, use the model's headline/rationale; otherwise use the rules text and set
     `downgrade_rejected=true`. If the final status is `NO_ISSUE`, use the fixed headline "No
     issue found by these checks" and no model text (AC-004.9).
   - `fired_rules[]` from the rules are always copied to the card.
   - Deciding conflict type = the fired rule's (highest-status rule) if the rules set the final
     status, else the model's.
5. Alternative (AC-004.6): candidates = [model alternative, then the rule table's alternatives
   for (proposed drug, deciding conflict type)]. A candidate qualifies only if it is on that
   allowed list, is outside the proposed drug's class when the model raised the status, and
   its rewritten order re-run through Layer 1 returns `NO_ISSUE` (or `WARNING` with a reviewed
   rule-table dose). First qualifying candidate is shown, else none; an unreviewed dose is
   shown as "Dose: consult SmPC" with no numeric value.
   Never for `NO_ISSUE` cards.
6. Model unavailable at step 3 → card = rules verdict, `source=rules`, `model_note` = the
   fallback note "Model check unavailable — rules only".

UI (AC-008.7): each evaluation gets a client request ID; "Sign order" is disabled while
"Checking context…" is shown; responses for an older request ID are dropped.

## Security design
- Identities: none. Local single-user tool; no accounts (non-goal).
- IAM: n/a locally; see the GCP reference architecture for the documented target.
- Secrets: none required. No API keys (local Ollama). Nothing to put in Secret Manager.
- Network exposure: uvicorn binds `127.0.0.1` only. `TrustedHostMiddleware` allows only
  `127.0.0.1`/`localhost` (DNS-rebinding defence). No CORS headers; API requires
  `Content-Type: application/json` (a cross-site form post can't send it without a preflight).
  The only outbound connection is to the configured Ollama URL (NFR-001).
- Data protection: synthetic data; nothing persisted; logs allowlist (request ID, preset ID,
  rule IDs, statuses, timings, model outcome); no request bodies, 422 bodies or raw model output
  in any log; uvicorn access log off or reduced to method/path/status.
- Config guard: non-loopback bind host or Ollama URL refused at start-up unless
  `OPENMEDCHECK_ALLOW_NONLOCAL=1` (prevents accidental exposure or egress).
- Output encoding: Jinja2 autoescape on; JS inserts all model and user text with `textContent`.
- Supply chain: runtime deps limited to fastapi, uvicorn, jinja2, httpx, pydantic; dev adds
  hypothesis; pinned in `uv.lock`; `pip-audit` in CI; no CDN assets.
- Threats considered:
  | Threat | Mitigation |
  |---|---|
  | Prompt injection in `ed_note` asks the model to approve | Escalate-only combiner (model can't lower the verdict); note delimited as data; injection test (AC-004.8) |
  | Model invents a drug or dose | Alternative is an enum of allowed IDs per conflict type; doses only from the rule table; Layer 1 re-check; same-class alternatives excluded when the model escalated; dose patterns and other drug names in model text → invalid |
  | Model output with HTML/script (XSS) | Autoescape + `textContent`; XSS test |
  | Malicious website calls the local API (CSRF / DNS rebinding) | Trusted-host check, JSON-only content type, no CORS; no state to change |
  | Health data leaks into logs | Allowlisted log fields; log-capture test (NFR-002) |
  | Oversized input / resource exhaustion | 16 KB body limit, field length limits, model timeout |
  | Clinically wrong rule shown as authoritative | Source citation + specialist review mark per rule; unreviewed doses suppressed; "No issue found by these checks" wording; banner |

## Reliability and operations
- Failure modes and handling:
  | Failure | Behaviour |
  |---|---|
  | Ollama not running / model not pulled | Health shows `unavailable`; checks return rules-only cards |
  | Model slow (> timeout) | Rules-only card; `model_outcome=timeout` |
  | Invalid JSON / schema violation | Retry once, then rules-only; `model_outcome=invalid` |
  | Model tries to downgrade | Rules verdict kept; `downgrade_rejected=true` |
  | Bug in the app | 500 with problem details, no body logged |
- Observability: one JSON log line per check (NFR-007) to stdout; `scripts/measure.py` for
  latency and validity (REQ-012). No metrics backend locally.
- Backups / recovery: none needed (no state).

## Environments and deployment
- **v0.1 (this version):** local only. `ollama pull gemma4:e4b` → `uv sync` →
  `uv run openmedcheck` → open `http://127.0.0.1:8000`. CI (existing GitHub Actions) runs
  lint, type check, unit/API tests with the fake model, and pip-audit; tests needing a real model
  are marked `ollama` and run locally only.
- **Cloud:** documented plan only (below). Not implemented (AC-013.3).

## GCP reference architecture (documented, not implemented)
**Not implemented in v0.1** (REQ-013, AC-013.3): nothing in this section exists as code,
Terraform or cloud resources, and the app has no cloud SDK calls (NFR-006). It was reviewed against
the code on `dev` (`config.py`, `web.py`, `model_client.py`, `logging_setup.py`, `__main__.py`)
on 2026-10-17; the gaps between the code and this plan are listed under "Code changes this plan
needs", and each needs a spec change before anyone builds it.

Target for a hospital's own GCP tenancy, europe-west1, one project per environment
(`openmedcheck-dev`, `openmedcheck-prod`).

```mermaid
flowchart LR
  clin[Clinician browser<br/>hospital network] --> lb[HTTPS LB<br/>IAP + Cloud Armor]
  lb --> web[Cloud Run: web<br/>FastAPI + rules<br/>SA: web-sa]
  web -- "Direct VPC egress<br/>all traffic via VPC" --> gemma[Cloud Run: gemma<br/>Ollama + gemma4:e4b, 1x L4<br/>ingress: internal only<br/>SA: gemma-sa]
  web -. logs: IDs + verdicts only .-> logging[Cloud Logging]
  ar[Artifact Registry] -. images by digest .-> web & gemma
```

- **web**: Cloud Run service, the same container as local. Ingress
  `internal-and-cloud-load-balancing` behind an HTTPS load balancer with IAP (staff identities)
  **and** Cloud Armor (gcp.md: no public ingress without Cloud Armor). No `allUsers` invoker
  binding. Egress: Direct VPC egress, all traffic through a custom-mode VPC with no NAT, so the
  app cannot reach the internet. Probes: startup and liveness probe `GET /` (static HTML, no
  model call). Do **not** probe `/api/model/health`: it reports the model state, and `web` must
  stay up (rules-only) when the model is down (REQ-005).
- **gemma**: Cloud Run service with 1 NVIDIA L4, Ollama with the model weights baked into the
  image (no download at start), `OLLAMA_HOST=0.0.0.0:<container port>` so Ollama listens on the
  Cloud Run port instead of its loopback default, ingress `internal`, invoker role granted only
  to `web-sa`, `max-instances=1`, `min-instances=0` (demo) or `1` (production), concurrency =
  `OLLAMA_NUM_PARALLEL`. Instance-based billing (the mode the L4 prices below are quoted in).
- **Identities:** `web-sa` (`roles/run.invoker` on `gemma` only, log writer); `gemma-sa` (log
  writer only). No key files; CI deploys through Workload Identity Federation.
- **Network:** custom VPC + subnet in europe-west1, Private Google Access on, private DNS for
  `run.app` so `web` reaches `gemma` over the VPC (risk to verify, idea brief section 6).
- **Data:** no storage of context. `web` writes one JSON line per check to stdout with the
  allowlisted fields in `logging_setup.ALLOWED_FIELDS` (request ID, preset ID, rule IDs, statuses,
  risk levels, latencies, model outcome and attempts, prompt version, HTTP method/path/status);
  the platform's own Cloud Run request log adds method, path and status, never bodies. Cloud
  Audit Logs on; log retention default. For real patient data, add a VPC Service Controls
  perimeter around the project (gcp.md).
- **Cold start:** Google's Cloud Run GPU GA announcement reports a GPU instance ready in under
  5 s and about 19 s to first token from zero for a 4B Gemma (not re-measured here). The app's
  total model deadline is 10 s (`OPENMEDCHECK_MODEL_TIMEOUT_S`, across attempt and retry), so with
  `min-instances=0` the first check after idle will usually time out and return a rules-only
  card (the designed fail-safe, REQ-005). Mitigations: the instant rules card,
  `/api/model/warmup` on page load, and `min-instances=1` in production.
- **Cost:** see "Cost estimate" below. L4 price read on 2026-10-17 (Q-1, closed with a caveat).

### Code changes this plan needs (not implemented; each needs a spec change first)
The shipped app is loopback-only by design (AC-011.3, AC-011.4, NFR-001). Running it on Cloud Run
means deliberately relaxing that:

| Topic | v0.1 behaviour (verified in code) | Documented future change |
|---|---|---|
| Bind host | `OPENMEDCHECK_HOST` default `127.0.0.1`; `Config.validate` refuses any non-loopback host | The Cloud Run service sets `OPENMEDCHECK_HOST=0.0.0.0` and `OPENMEDCHECK_ALLOW_NONLOCAL=1`. Cloud Run only reaches a container listening on all interfaces, so the flag is the explicit, reviewable opt-in. Set it only in the service definition (Terraform), never as an image default or in a `.env` file |
| Port | `OPENMEDCHECK_PORT` (default 8000); the app does not read Cloud Run's `PORT` | Set `OPENMEDCHECK_PORT` to the service's container port in the service definition |
| Trusted hosts | `TrustedHostMiddleware` allows `127.0.0.1`, `localhost`, `[::1]`, plus `config.host` when it is non-loopback and `ALLOW_NONLOCAL=1`. With host `0.0.0.0` that adds the literal `0.0.0.0`, which no real `Host` header matches, so every request through the load balancer would be rejected (400) | Add a configurable trusted-hosts list (for example `OPENMEDCHECK_TRUSTED_HOSTS`, comma-separated) holding the load balancer's DNS name and the service's `run.app` name; keep the DNS-rebinding defence on. Needs a new AC and a test |
| Ollama URL | `OPENMEDCHECK_OLLAMA_URL` must be loopback unless `ALLOW_NONLOCAL=1` | Set to the internal `gemma` service URL (`https://...run.app`); allowed by the same flag |
| Calling `gemma` | `model_client` sends no credentials; `httpx.Client(trust_env=False)` | An invoker-only Cloud Run service needs a Google-signed ID token with the `gemma` URL as audience on every call. Add an optional token provider in `model_client`; it makes the metadata server a second outbound destination, which contradicts NFR-001 ("only the Ollama URL") and its outbound-socket test, so NFR-001 must be amended first |
| Log severity | JSON line carries `level`, `ts`, `logger`, `event` | Cloud Logging reads `severity` and `timestamp`; add them (or map them in the logging agent) so levels and times show correctly. Keep the allowlist unchanged |
| Health | `GET /api/model/health` is model health, not process health | Use `GET /` for probes (above) |

At the commit reviewed, `web.py` serves `/`, `/api/drugs`, `/api/presets` and `/api/check/rules`;
`/api/check` and `/api/model/*` in the Interfaces table are still pending in the task plan, so the
probe and warm-up statements above follow the design, not shipped code.

### Deployment plan (Not implemented in v0.1)
1. **Prerequisites (human):** create the project, link billing, set a budget with alerts at
   50/90/100% (size it from the Cost estimate; a demo week is about US$10); request L4 quota in
   europe-west1 on the Quotas page (the default per-region GPU quota, and whether zonal
   redundancy changes it, are not verified here: read the current Cloud Run GPU documentation);
   enable the Run, Artifact Registry, Compute (VPC), IAM and Logging APIs; apply organisation
   policies per gcp.md (no SA keys, restrict public IPs, resource locations).
2. **Code changes** from "Code changes this plan needs", through a spec change and with tests,
   before any image is built.
3. **Terraform to write** (`infra/`, following terraform.md; `envs/dev` and `envs/prod` as
   separate root modules with GCS remote state): `network` (custom VPC, subnet, PGA, private DNS
   zone for `run.app`, deny-all egress firewall); `artifact_registry`; `iam` (`web-sa`,
   `gemma-sa`, invoker binding); `run_gemma` (GPU, internal ingress, min/max instances,
   `OLLAMA_HOST`); `run_web` (Direct VPC egress, `OPENMEDCHECK_HOST=0.0.0.0`,
   `OPENMEDCHECK_ALLOW_NONLOCAL=1`, `OPENMEDCHECK_PORT`, trusted hosts, `OPENMEDCHECK_OLLAMA_URL` =
   gemma URL, ingress via LB); `lb` + IAP + Cloud Armor; budget; labels
   `env/app/owner/managed-by=terraform`.
4. **Images:** build `web` (this repo) and `gemma` (Ollama base + baked `gemma4:e4b`) in CI,
   push to Artifact Registry, scan, deploy by digest.
5. **Review:** `terraform plan -out=tfplan` -> plan review ->
   the human applies.
6. **Verify:** `gemma` URL unreachable from the internet (403/404); `web` -> `gemma` call works
   over the VPC with an ID token; `web` cannot reach an external host; a request with an
   unexpected `Host` header is rejected; a log sample has no context fields; run
   `scripts/measure.py` against the deployed URL and compare with NFR-004 (expect the first
   call after idle to be rules-only when `min-instances=0`).
7. **Rollback:** Cloud Run revision traffic shift to the previous revision; `terraform plan`
   for any infra revert; to stop GPU spend the human sets `gemma` to zero instances or removes
   the service.

## Testing strategy
| Level | Covers | Tools | Requirements |
|---|---|---|---|
| Unit | Rules engine per rule; Cockcroft-Gault; rule-table lint (citations, review marks, alternatives on the list); combiner (property-based: every status/tier pair, never below rules, renal flag never cleared); alternative re-check; schema validation of model output | pytest, hypothesis | REQ-002, REQ-004, NFR-009, NFR-011 |
| Service | Check service with `FakeModelClient`: escalate, downgrade attempt, invalid ×1 then valid, invalid ×2, timeout, unreachable, unknown drug suggestion, injection note | pytest | REQ-003, REQ-005, AC-004.* |
| API | Endpoints via `TestClient`: 200/413/415/422 shapes, presets A/B/C with a scripted fake model, trusted-host rejection, XSS strings escaped, log capture (no context values; one line per check with NFR-007 fields), outbound-socket guard | pytest, FastAPI TestClient | REQ-001, REQ-006, REQ-011, NFR-001/002/005/007 |
| Wording | Banned words in templates, static JS and README; banner present | pytest | REQ-010, NFR-008 |
| Integration (local, marked `ollama`) | Real `gemma4:e4b`: preset A rules `NO_ISSUE` → final `BLOCKED` in ≥ 9/10 runs; schema validity | pytest `-m ollama` | AC-003.4 |
| Measurement | 20+ calls: p50/p95, valid-output rate | `scripts/measure.py` | REQ-012, NFR-004, NFR-012 |
| Manual / review | UI flow for A/B/C, keyboard-only pass, contrast; usability review | checklist | REQ-007–009, NFR-010 |

Each AC is referenced in the test name or docstring (e.g. `test_ac_004_3_rules_blocked_is_final`).

## Cost estimate
- v0.1: EUR 0 cloud spend (local only, NFR-006). Electricity/hardware are the developer's own.
- Documented cloud target (Not implemented in v0.1); **Q-1 closed with a caveat**.
  - **Source:** Google Cloud, "Cloud Run pricing", https://cloud.google.com/run/pricing, section
    "Services (Instance-based billing)", read 2026-10-17, USD. Quoted rates:
    NVIDIA L4 without zonal redundancy US$0.0001867 per second (US$0.672 per hour); NVIDIA L4
    with zonal redundancy US$0.0002909 per second (US$1.047 per hour); CPU US$0.000018 per
    vCPU-second; memory US$0.000002 per GiB-second.
  - **Caveat:** the page picks the region with a selector. The static page I could read showed
    the default table (Iowa, us-central1); I could not select europe-west1 to confirm it. The
    same page's worked "Example 3" (Ollama on Cloud Run in europe-west1, 4 vCPU, 16 GiB, L4
    without zonal redundancy, up to 2 instances, bell-curve daily traffic) gives US$827.62 a
    month before the free tier (US$822.40 after it), which is consistent with these rates but
    does not prove them for europe-west1. Re-check the europe-west1 row, or the Pricing
    Calculator, before deploying.
  - **Assumptions:** one `gemma` instance of 4 vCPU and 16 GiB (the shape in Google's Example 3;
    not verified as the minimum for an L4), instance-based billing, 730 hours a month, no free
    tier, no committed-use discount; network, load balancer, Cloud Armor, Artifact Registry,
    logging and `web` costs are not priced here.
  - **Rate per running instance:** non-zonal 3600 x (0.0001867 + 4 x 0.000018 + 16 x 0.000002) =
    US$1.047/h; zonal 3600 x (0.0002909 + 4 x 0.000018 + 16 x 0.000002) = US$1.422/h.

    | Scenario | Instance-hours | Non-zonal | Zonal |
    |---|---|---|---|
    | Demo video day, `min-instances=0`, 2 h billed | 2 | US$2.09 | US$2.84 |
    | Demo week (5 days x 2 h) | 10 | US$10.47 | US$14.22 |
    | Production, `min-instances=1`, always on | 730 | US$764 | US$1,038 |

    With `min-instances=0`, billed time includes the time an instance stays up after a request,
    so real hours exceed active use; 2 h a day is an assumption, not a measurement. The earlier
    first estimate (about US$1/h, US$700-750 a month) is close to the non-zonal rate.

## Decisions
| ID | Decision | ADR |
|---|---|---|
| D-1 | One local FastAPI app with a server-rendered page and vanilla JS | docs/adr/0002-local-fastapi-app-with-server-rendered-ui.md |
| D-2 | Escalate-only two-layer engine; rules-only fail-safe | docs/adr/0003-escalate-only-two-layer-engine.md |
| D-3 | Gemma 4 E4B via local Ollama, JSON-schema output, httpx client | docs/adr/0004-serve-gemma-4-e4b-locally-with-ollama.md |
| D-4 | Cloud Run + L4 reference architecture documented, not deployed | docs/adr/0005-gcp-reference-architecture-documented-only.md |
| D-5 | Two API calls for the progressive card (no streaming) | this document |
| D-6 | Rule table as a typed Python module, rendered to Markdown for review | this document |

## Traceability
| Requirement | Design section(s) |
|---|---|
| REQ-001 | Data model (DecisionCard, ranges); Interfaces; Check flow 1, 5 |
| REQ-002 | Components (`rules_engine`, `rule_table`, `renal`); Data model |
| REQ-003 | Components (`prompt`, `model_client`); Interfaces (Ollama call); Check flow 3 |
| REQ-004 | Check flow 4–5; Components (`combiner`); Threats |
| REQ-005 | Check flow 6; Reliability (failure modes) |
| REQ-006 | Components (`presets`); Testing (API) |
| REQ-007 | Components (`web`); Data model ranges |
| REQ-008 | Options (progressive display, D-5); Interfaces |
| REQ-009 | Interfaces (`POST /api/check` with the rewritten order); Check flow 5 |
| REQ-010 | Testing (wording); Security (clinical threat) |
| REQ-011 | Environments and deployment; Interfaces (configuration) |
| REQ-012 | Components (`scripts/measure.py`); Testing (measurement) |
| REQ-013 | GCP reference architecture; Deployment plan; ADR 0005 |
| REQ-014 | Interfaces (`/api/model/warmup`, health) |
| NFR-001 | Security design (network exposure, output encoding, supply chain) |
| NFR-002 | Data model (classification); Security (data protection) |
| NFR-003 | Reliability (failure modes) |
| NFR-004 | ADR 0004; Interfaces (timeout); Testing (measurement) |
| NFR-005 | Testing (API concurrency) |
| NFR-006 | Cost estimate |
| NFR-007 | Reliability (observability); Components (`logging_setup`) |
| NFR-008 | Testing (wording); Security (clinical threat) |
| NFR-009 | Testing strategy |
| NFR-010 | Testing (manual / review) |
| NFR-011 | Components (`rule_table`, `render_rule_table.py`); Data model (rule entry) |
| NFR-012 | Testing (measurement); ADR 0004 |
