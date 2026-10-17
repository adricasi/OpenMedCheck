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
