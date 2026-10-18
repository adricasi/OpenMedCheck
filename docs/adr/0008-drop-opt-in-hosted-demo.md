# 0008. Drop the opt-in hosted demo; ship local Docker and a documented-only GCP target

- Status: Accepted
- Date: 2026-10-18
- Deciders: adricasi
- Amends: [ADR 0007](0007-hosted-demo-profile.md) (superseded). `docs/spec/requirements.md`
  (REQ-015, AC-015.4) and `docs/spec/design.md` (GCP reference architecture) are updated to
  match.

## Context
ADR 0007 added an opt-in hosted demo so judges could try OpenMedCheck without installing Ollama:
the app on Render, Gemma on a DigitalOcean GPU droplet behind Caddy with a bearer token
(REQ-015, T-016). Comparing cloud providers for the submission (GCP, DigitalOcean, Render)
surfaced three problems with that plan before it was ever deployed:

- **Privacy.** Keeping Gemma private but off the app's own host, without paying for an
  always-on GPU there too, means a pay-per-use serverless model endpoint — a third-party model
  API. That is exactly the "hosted API" case the product's own architecture deliberately avoids
  (ADR 0003, ADR 0004): the (synthetic) order and note would leave the app's own infrastructure
  for someone else's model service, which needs its own privacy notice and processor
  disclosure even with synthetic data, and sits uneasily next to the "zero egress" story (G-3).
- **Cost and operational surface for a demo that runs once.** Keeping Gemma private instead —
  one GPU droplet, or the original Render + DigitalOcean split — means either a public GPU
  endpoint with a bearer key to generate, store and rotate (the split), or an hourly GPU bill
  that is the same whether anyone is looking at the demo or not (a DigitalOcean GPU droplet,
  from US$0.76/h for the smallest card, billed even while powered off until destroyed, per
  [DigitalOcean's GPU Droplet pricing page][DigitalOcean GPU Droplet pricing], read
  2026-10-18). Either way it is a second
  production-shaped surface — a public endpoint, or a public app plus a public GPU host — to
  secure, monitor and tear down, for a judging window of a few days.
- **It duplicates work the spec already commits to doing properly.** REQ-013 documents a GCP
  reference architecture precisely so the self-hosting, zero-egress story (G-3) is credible
  without being deployed in v0.1. Standing up a second, throwaway hosted path on different
  providers, with different trade-offs and its own privacy story, told a less consistent
  deployment story than finishing that one plan in full detail and running everything else
  locally.

## Options considered
1. **Keep ADR 0007 as is:** app on Render, Gemma on a DigitalOcean GPU droplet behind a bearer
   token. Pros: no new work, already documented. Cons: a public GPU endpoint and a key to
   manage; two providers and two bills; still needs standing the droplet up today, under time
   pressure.
2. **Single DigitalOcean GPU droplet** (app + Ollama on one host, Caddy in front, no model key
   needed because Ollama never leaves the host's loopback interface): cheaper than the split and
   keeps the model off the public internet. Rejected for today: still an hourly GPU bill
   (roughly US$18/day) for a demo audience that is small and short-lived, plus a droplet to
   harden and destroy afterwards.
3. **Small DigitalOcean CPU droplet with the model on DigitalOcean's pay-per-use serverless
   inference** (the pattern used by the sibling TCGrass project): cheap (around US$6/month plus
   fractions of a cent per check), no GPU to operate. Rejected here specifically on privacy: it
   sends patient context, even synthetic, to a third-party model API, which fits TCGrass's
   product story but not this one's zero-egress claim.
4. **No public hosted demo:** ship the local Docker one-command run and the demo video/GIF
   (already required by G-4/T-012), and finish the GCP reference architecture (REQ-013) in full
   detail as the documented, not-implemented, real deployment target.

## Decision
We will go with option 4: drop the opt-in hosted demo. OpenMedCheck v0.1 ships **only** as a
local run (`docker compose up`, or `uv run openmedcheck`) plus the demo video for the
submission, and the **only** documented non-local deployment target is the GCP reference
architecture (REQ-013, expanded in `docs/spec/design.md`, with a command-level walkthrough in
`docs/deploy/gcp-reference-architecture.md`), explicitly marked **not implemented**.

The Render blueprint (`render.yaml`) and the two provider guides (`docs/deploy/render.md`,
`docs/deploy/digitalocean-gemma.md`) are deleted, along with the README and script references
to them.

REQ-015's **mechanism** — the explicit `OPENMEDCHECK_ALLOW_NONLOCAL` / `OPENMEDCHECK_PUBLIC_HOSTS`
opt-in, the hosted-demo banner, and the bearer-key support for a remote model — stays in the
code: it is generic, already implemented and tested, and it is the same opt-in the GCP plan's
"Code changes this plan needs" table already relies on (`docs/spec/design.md`). Only AC-015.4,
the requirement to ship Render/DigitalOcean guides, and the "challenge judge" framing of the
requirement's story, are dropped.

## Consequences
- Positive: no public GPU endpoint or bearer key to generate, store or rotate before
  submission; no second provider bill; the deployment story is one consistent, fully documented
  plan (GCP) instead of two partial, differently-risky ones; less surface to secure and tear
  down under time pressure.
- Negative / risks: judges can only see the product running in the demo video, not try it live
  in a browser, unless the owner deploys the GCP plan later. Mitigation: the video shows presets
  A, B, C and the model-down fallback (T-012); the README and the DEV post link the documented
  GCP plan and the one-command local run. (Update 2026-10-18: no demo video will be published;
  the post shows the demo with screenshots.)
- Follow-ups: `README.md`, `docs/spec/requirements.md` (REQ-015), `docs/spec/tasks.md` (T-011,
  T-016 amendment notes), `docs/spec/design.md` (GCP section expanded), `scripts/eval_set.py`
  (stale doc reference), and `docs/adr/0007-hosted-demo-profile.md` (marked superseded) are
  updated in this same change. If OpenMedCheck is deployed after the challenge, follow the GCP
  plan with Terraform, a reviewed plan and a human
  `terraform apply` — AC-013.3 (no Terraform, no cloud resources) stays in force until then.

[DigitalOcean GPU Droplet pricing]: https://www.digitalocean.com/pricing/gpu-droplets
