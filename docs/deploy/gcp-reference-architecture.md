# GCP reference architecture — NOT IMPLEMENTED, documentation only

> **No step in this guide has been run.** `infra/` contains no Terraform for this plan; no GCP
> project, resource or bill exists because of OpenMedCheck. This file is the command-level
> walkthrough of the architecture decided in
> [ADR 0005](../adr/0005-gcp-reference-architecture-documented-only.md) and detailed in
> [`docs/spec/design.md`](../spec/design.md) (§ "GCP reference architecture", § "Deployment
> plan"), written so a human can follow it when the project is actually deployed. Only a human
> runs `terraform apply`/`destroy`/`import`, `gcloud ... delete/create/update/deploy`, or any
> other state-changing command from this guide (AC-013.3). Every `gcloud` and
> `terraform` command below is illustrative: read it, don't paste-and-run it without checking it
> against the current CLI and your own project IDs first.

For **today's actual deployment** — the only one that exists — see
[`local-docker.md`](local-docker.md).

## Why this exists instead of a public demo
OpenMedCheck's story is "runs inside the hospital's own cloud, with the model never reachable
from outside it" (G-3). [ADR 0008](../adr/0008-drop-opt-in-hosted-demo.md) dropped an earlier
opt-in hosted demo on Render + DigitalOcean specifically because every alternative to this
architecture either put the model behind a public endpoint, sent patient context to a
third-party model API, or cost money around the clock for a demo that runs once. This plan is
the one that keeps the model private end to end — at the cost of being the one that takes the
most work to actually stand up, which is why it stays documented rather than deployed in v0.1.

## Architecture at a glance
```
Clinician browser (hospital network)
        │ HTTPS
        ▼
External HTTPS load balancer  ── Cloud Armor (edge filtering)
        │ IAP (clinician Google group only)
        ▼
Cloud Run: web  (this repo's container, no GPU)
        │ Direct VPC egress, TLS, ID token (audience = gemma's URL)
        ▼
Cloud Run: gemma  (Ollama + gemma4:e4b baked in, 1x NVIDIA L4, ingress: internal only)
```
`gemma` has no path from the public internet at all: not a firewall rule away, not a
misconfigured ingress setting away — removing it would need both the Cloud Run `ingress`
setting *and* the IAM invoker binding to be changed, by a human, through a reviewed Terraform
plan. `web` has no outbound path except to Google's own API range and to `gemma`; both services
have a deny-all egress firewall rule behind them. Full component detail, IAM table, firewall
table and monitoring plan: `docs/spec/design.md`.

## 0. Prerequisites
Each step below is read from the console or a `gcloud` command with no side effects (`describe`,
`list`), except where marked **(state-changing — human only)**.

1. **Projects and billing (state-changing — human only).** One project per environment:
   `openmedcheck-dev`, `openmedcheck-prod`. Link billing to each.
2. **Budget (state-changing — human only).** Create a budget on each project with alerts at
   50/90/100% of the figure in "Cost estimate" below. Budget alerts notify; they do not cap
   spend — `max-instances` on `gemma` is the real ceiling (see step 6 "Teardown").
3. **L4 GPU quota.** Check the Quotas page for NVIDIA L4 quota in `europe-west1`. The default
   per-region allowance, and whether choosing zonal redundancy changes it, are **not verified
   here** — read Cloud Run's current GPU documentation before requesting an increase.
4. **Enable APIs (state-changing — human only).**
   ```bash
   gcloud services enable \
     run.googleapis.com \
     artifactregistry.googleapis.com \
     compute.googleapis.com \
     dns.googleapis.com \
     iap.googleapis.com \
     iam.googleapis.com \
     iamcredentials.googleapis.com \
     sts.googleapis.com \
     billingbudgets.googleapis.com \
     ondemandscanning.googleapis.com \
     logging.googleapis.com \
     --project=openmedcheck-prod
   ```
5. **Organisation policies (state-changing — human only).** Disable service-account key creation, restrict public IP assignment project-wide, restrict
   resource locations to `europe-west1`/`eu`.
6. **Terraform state buckets (state-changing — human only).** One GCS bucket per environment,
   versioning on, uniform bucket-level access on, before the first `terraform init`.

## 1. Code changes this plan needs — write and merge first
`docs/spec/design.md` § "Code changes this plan needs" lists every place the shipped app
assumes loopback-only (bind host, port, trusted hosts, the Ollama URL check, calling `gemma`
with an ID token, log field names). **Each row needs its own spec change (new ACs, and an
NFR-001 amendment for the one new outbound destination — the metadata server) before any image
referencing it is built.** Make each one a spec change first, then implement it with tests and a review of the
escalate-only invariant, same as any other change to this codebase. This step
produces ordinary pull requests against this repository; it touches no cloud resource.

## 2. Terraform to write
Nothing under `infra/` exists for this plan yet. Layout (also in `docs/spec/design.md`):
```
infra/
  modules/
    network/            # VPC, subnet, Private Google Access, private DNS zone, firewall rules
    artifact_registry/  # one Docker repository
    iam/                # web-sa, gemma-sa, every binding design.md's "IAM bindings" table lists
    run_gemma/          # Cloud Run service: GPU, ingress internal, OLLAMA_HOST
    run_web/            # Cloud Run service: Direct VPC egress, trusted hosts, Ollama URL
    lb/                 # static IP, managed cert, SSL policy, URL map, IAP, Cloud Armor
    logging/            # log bucket in europe-west1/EU
    budget/             # billing budget + alert thresholds
  envs/
    dev/   {backend.tf, main.tf, variables.tf}   # min-instances=0, non-zonal
    prod/  {backend.tf, main.tf, variables.tf}   # min-instances=1, zonal redundancy
```
Every resource in `docs/spec/design.md`'s "Resource inventory" table belongs to exactly one of
these modules; nothing else is created. Labels on every resource: `env`, `owner`, `app`,
`managed-by=terraform`.

## 3. Images
Build `web` from this repository's `Dockerfile`, and `gemma` from an Ollama base image with
`gemma4:e4b` baked in at build time (no download at container start — a cold `gemma` instance
should not also be waiting on a model pull). Push both to the `artifact_registry` module's
repository, run Container Analysis / On-Demand Scanning on each, and **deploy by digest, never
by a mutable tag**, so Terraform and CI agree on exactly one owner for the image reference. This
step runs in CI (build + push), not by hand.

## 4. Review and apply — human only
```bash
# Per environment, after the Terraform in step 2 is written and the images in step 3 exist:
terraform -chdir=infra/envs/dev init
terraform -chdir=infra/envs/dev plan -out=tfplan      # read-only; safe to run any time
```
Have the plan reviewed (IAM, network exposure, cost). Fix every
blocking finding before proceeding.
```bash
terraform -chdir=infra/envs/dev apply tfplan           # HUMAN ONLY
```
Repeat for `prod` once `dev` is verified (step 5).

## 5. Verify
Run every check below after an apply, in this order; stop and fix before telling anyone the
environment is live if any of them fails.

| # | Check | Expected result |
|---|---|---|
| 1 | `curl -i https://<gemma's run.app URL>/api/tags` from your own machine | 403, or no route at all — never a 200 |
| 2 | `web` calling `gemma` with its ID token (through the app's own health/warm-up path) | Succeeds |
| 3 | The same call with no token, or from an identity that isn't `web-sa` | 403 |
| 4 | `gcloud run services describe web/gemma --region=europe-west1` | Both report the new revision `Ready` |
| 5 | From inside either container, a request to a public IP outside the Google API range | Times out or is refused |
| 6 | A request to the load balancer with an unexpected `Host` header | 400 |
| 7 | A Google account outside the clinician group, through IAP | 403 |
| 8 | The `gemma` `run.app` URL called directly, no token | 403 |
| 9 | A sampled `web`/`gemma` log line | Only `logging_setup.ALLOWED_FIELDS` — no context, no prompt text |
| 10 | Measure latency against `https://<load balancer URL>` and compare with NFR-004 | First call after idle may be rules-only (`min-instances=0`); later calls meet the budget. `scripts/measure.py` has no remote-target option today — it only drives a local subprocess — so this step needs that option added (step "Code changes this plan needs" in design.md) before it can be run this way |
| 11 | Uptime check, alerting policies, budget (design.md "Monitoring, alerting and operations") | All active |

## 6. Operate

### Rollback
```bash
gcloud run services update-traffic web --region=europe-west1 \
  --to-revisions=<previous-revision>=100                       # HUMAN ONLY
```
For an infrastructure change, `terraform plan` the revert and apply it through the same review
as step 4. Both services are stateless; `prevent_destroy` on the static IP and the versioned GCS
state bucket stops an accidental `destroy` from taking the public address or the Terraform state
with it.

### Stop GPU spend immediately (no rollback needed)
```bash
gcloud run services update gemma --region=europe-west1 --max-instances=0   # HUMAN ONLY
```
`web` keeps serving — every check falls back to a rules-only card (REQ-005); the app does not go
down.

### Teardown
```bash
terraform -chdir=infra/envs/prod plan -destroy -out=tfplan.destroy   # read-only
# review (same as step 4), then:
terraform -chdir=infra/envs/prod apply tfplan.destroy                # HUMAN ONLY
```
Then remove the budget and confirm in Billing that no charge continues. Only a human runs `destroy`.

## Cost estimate
Full sourcing and the europe-west1 caveat are in `docs/spec/design.md` § "Cost estimate"
(Google Cloud, "Cloud Run pricing", read 2026-10-17). Summary:

| Scenario | Instance-hours | Non-zonal L4 | Zonal L4 |
|---|---|---|---|
| Idle (`min-instances=0`, nobody checking) | 0 | US$0 | US$0 |
| Demo video day, 2 h billed | 2 | US$2.09 | US$2.84 |
| A judging week, ~2 h/day | 10 | US$10.47 | US$14.22 |
| Production, `min-instances=1`, always on | 730 | US$764 | US$1,038 |

Plus roughly US$25–30/month fixed (load balancer, Cloud Armor, Artifact Registry) while the
stack exists at all, whether or not `gemma` is ever called — unverified from memory, confirm in
the Pricing Calculator before relying on it.

## Open risks before this is ever applied
- The europe-west1 Cloud Run GPU price was not directly confirmed (Q-1, closed with a caveat;
  see design.md).
- Whether Direct VPC egress traffic from `web` to `gemma` actually honours the firewall rules in
  "Firewall rules" the way this plan assumes is a design risk to verify on a real `dev` apply,
  not just in Terraform `plan` output.
- Cold start (~19 s to first token from zero, per Google's GPU GA announcement, not re-measured
  here) exceeds the app's 10 s model deadline; `min-instances=0` demo traffic should expect the
  first check after idle to be rules-only, by design (REQ-005), not a bug.
