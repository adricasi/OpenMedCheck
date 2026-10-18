# 0007. Add an opt-in hosted demo profile; keep local and on-premises as the product

- Status: Accepted
- Date: 2026-10-18
- Deciders: adricasi

## Context
The product story is "runs on-premises in the hospital, zero egress" (G-3, NFR-001). Challenge
judges, however, are unlikely to install Ollama and a 6.6 GB model to try it (G-4). ADR 0005
documented a GCP reference architecture and decided against a hosted demo for v0.1; the owner
has since decided (T-016, REQ-015) to offer a small, opt-in hosted demo with synthetic data only,
using Render for the app and a DigitalOcean GPU droplet for Gemma. The local default must not
change.

## Options considered
1. **App on Render + Gemma on a DigitalOcean GPU droplet behind Caddy with a bearer token**:
   Pros: judges need only a browser; the model stays self-hosted open-weights; small, understood
   components; the app code change is a few opt-in environment variables. Cons: a public GPU
   endpoint exists while judging; the droplet bills by the hour; prompts (synthetic) cross the
   public internet.
2. **Everything on the one GPU droplet (app + Ollama + Caddy)**: Pros: no key, no second
   provider, Ollama never leaves the host. Cons: the app then needs its own deployment
   mechanism on the VM; the owner chose a managed app host for the simplest hand-off.
3. **Hosted model API (not Gemma on our host)**: rejected, the point is self-hosted Gemma.
4. **No hosted demo, video only**: Pros: no exposure, no cost. Cons: judges cannot try it.
5. **The GCP reference architecture (ADR 0005)**: stays the documented hospital target; heavier
   to set up and own for a short demo.

## Decision
We will implement option 1 as an opt-in profile:
- The default stays local (`127.0.0.1`, loopback Ollama). The hosted profile is enabled only by
  `OPENMEDCHECK_ALLOW_NONLOCAL=1` plus `OPENMEDCHECK_PUBLIC_HOSTS`; the app then accepts only
  those Host headers, binds the platform `PORT`, and sends `Authorization: Bearer
  <OPENMEDCHECK_OLLAMA_API_KEY>` to the model. A key requires an `https://` Ollama URL (unless
  Ollama is on loopback). The key is excluded from `repr`, logs and responses.
- Every page of a hosted instance shows a notice: hosted for trying the demo, synthetic data
  only, the product is meant to run on-premises (AC-015.3).
- Ollama listens on the droplet's loopback only; Caddy provides HTTPS and forwards only requests
  with the bearer token; the firewall allows 22, 80 and 443.
- A Dockerfile and `docker compose` give a one-command local run for everyone else (AC-015.4).
  Nothing is deployed automatically; a human follows the guides in `docs/deploy/`.

## Consequences
- The app caps concurrent model calls (`OPENMEDCHECK_MAX_MODEL_CALLS`, default 4) and answers
  with the rules-only card beyond the cap; in the hosted profile it refuses a non-https or
  unauthenticated remote model URL; the proxy forwards only the four Ollama calls the app uses
  (security review).
- Positive: judges can try the demo in a browser; the local, zero-egress path is unchanged and
  still the default; the same image serves both local Docker and Render.
- Negative / risks:
  - A public GPU endpoint. Mitigation: bearer token (random 256-bit, root-only file, rotatable),
    TLS, narrow firewall, Ollama on loopback, power-off or destroy after judging, billing alert.
    A leaked key allows free inference until rotated.
  - The model host sees (synthetic) prompts. Mitigation: synthetic data only, shown on the
    banner and in the guides; no logging of context (NFR-002) in the app.
  - Cost while the droplet exists; the first request on an idle free-tier app host is slow;
    Gemma may be cold (card falls back to rules only, REQ-005).
  - NFR-001 now has the documented hosted exception; NFR-006 (zero cloud spend) does not hold
    while the demo runs.
- Follow-ups: tear everything down after judging; confirm in the consoles the provider-specific
  details marked "check in the console" in the guides.
