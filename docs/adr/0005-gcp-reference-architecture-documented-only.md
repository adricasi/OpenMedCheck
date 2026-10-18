# 0005. Document a Cloud Run + L4 GPU reference architecture; don't deploy it in v0.1

- Status: Accepted
- Date: 2026-10-17
- Deciders: adricasi

## Context
The product story is self-hosting inside a hospital's own cloud with zero egress of patient
context (G-3). For the challenge, the user decided (2026-10-17) to build and demo locally only
and to document, not implement, the GCP infrastructure (REQ-013, AC-013.3). The documented target
must be credible: least privilege, no public model endpoint, scale to zero, sourced cost.

## Options considered
1. **Cloud Run `web` (behind an HTTPS load balancer with IAP and Cloud Armor) + Cloud Run `gemma` with one L4 GPU running Ollama,
   internal-only ingress, reached via Direct VPC egress; scale to zero**: Pros: pay per use,
   Google's own Gemma-on-Cloud-Run tutorial, no VM ops, private model. Cons: GPU cold start
   (~19 s time to first token from zero for a 4B model, per Google's GA blog); internal ingress
   from another Cloud Run service needs Private Google Access/DNS set up correctly.
2. **Same as 1 with min-instances = 1**: no cold start, but always-on GPU cost (about US$1.05 per instance-hour, non-zonal, GPU plus 4 vCPU and 16 GiB, Q-1 closed with a caveat on
   2026-10-17, see design.md).
3. **Vertex AI endpoint + Private Service Connect**: managed, but an always-on node and no scale
   to zero.
4. **Compute Engine g2 + L4 (spot)**: cheapest per hour, but VM operations, preemption, no scale
   to zero.
5. **Hosted Gemma API**: rejected (multi-tenant public endpoint; violates NFR-001 in spirit).

## Decision
We will document option 1 as the reference architecture, with option 2 as a production
setting, in design.md together with a step-by-step human deployment plan, and we will not write
Terraform or create resources in this version.

## Consequences
- Positive: zero cloud cost and no deployment risk before the deadline; the post can still show
  a concrete, reviewable hospital deployment.
- Negative / risks: no hosted demo URL for judges; the plan is unverified (no `terraform plan`).
  Mitigation: repo + demo video; mark the plan "Not implemented"; check the challenge rules (Q-6).
- Follow-ups: when implemented, review the Terraform plan, and re-check the europe-west1 L4 price (Q-1 caveat) before applying.

- Status note (2026-10-17, T-011): still documentation only. design.md lists the code changes the
  plan needs (bind host, trusted hosts, ID-token call to `gemma`) as future spec changes.

- Status note (2026-10-18): revisited "why not a dedicated AI platform" (user question).
  **Correction to option 3:** Vertex AI endpoints now support scale-to-zero (minimum replica
  count 0 enrols a dedicated-resource GPU endpoint in it,
  [Vertex AI autoscaling docs](https://docs.cloud.google.com/vertex-ai/docs/predictions/autoscaling)),
  so "no scale to zero" is no longer accurate on its own. The deeper reasons option 1 still wins
  hold regardless:
  - **Cold-start failure shape.** A cold Vertex endpoint is reported to return 429 and drop the
    request while it scales back up (a third-party source, not confirmed in Google's own docs:
    [OneUptime, Feb 2026](https://oneuptime.com/blog/post/2026-02-17-how-to-enable-scale-to-zero-for-vertex-ai-prediction-endpoints-to-reduce-costs/markdown)).
    That doesn't fall back into this app's "rules-only card on timeout" fail-safe (REQ-005) the
    way a plain HTTP timeout does; adopting it would need new retry logic.
  - **Serving-stack mismatch.** Vertex AI's prebuilt Model Garden containers for Gemma serve via
    vLLM/TGI with an OpenAI-compatible API, not Ollama's. This project already committed to
    Ollama's own API (ADR 0004); moving to Vertex AI means replacing `model_client.py`'s client
    and re-validating the prompt/schema against a different serving stack, not a config change.
  - **One more networking construct for the same guarantee.** Vertex AI's private-endpoint story
    needs Private Service Connect on top of the VPC this plan already has; Cloud Run's
    `ingress: internal` plus an invoker-only IAM binding gets "never reachable except by `web`"
    directly.
  - **No use for the platform around the model.** Vertex AI's actual value is the MLOps surface
    around a model — registry, monitoring, evaluation, fine-tuning, multi-model governance.
    This plan serves exactly one open-weights model to exactly one caller, with no training
    pipeline; that surface would sit unused. The same reasoning rules out GKE for now: Google
    positions it for enterprise-scale orchestration, TPU serving and full control of the stack,
    which this single-model, demo-scale service doesn't need either, at the cost of operating a
    cluster.

  **Named triggers that would flip this decision** (so "we didn't pick Vertex AI/GKE" stays a
  reasoned, revisitable call rather than a fixed one):
  1. **Fine-tuning Gemma** on a hospital's own note style or formulary (floated as a possible
     next step in the DEV post, not done in this version) — Vertex AI's training/tuning
     pipeline and model registry are built for exactly that; Cloud Run could still serve the
     result afterward.
  2. **More than one model, or governance across model versions** (canary a new Gemma version,
     compare model outputs, track drift) — Vertex AI's registry and monitoring earn their keep
     once there is more than one model to manage.
  3. **Scale well beyond one model/one caller** (many replicas, higher throughput, TPUs) — that
     is GKE's territory (Google's own larger open-weights serving reference architectures run
     there), not Vertex AI's or Cloud Run's.

  None of the three apply today. Decision unchanged: option 1 (Cloud Run + L4, documented only).
