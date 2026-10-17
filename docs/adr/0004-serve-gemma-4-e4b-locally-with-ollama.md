# 0004. Serve Gemma 4 E4B locally with Ollama and JSON-schema-constrained output

- Status: Accepted
- Date: 2026-10-17
- Deciders: adricasi

## Context
Gemma 4 is mandated ("Best Use of Gemma"). The model must run on the developer's machine (NVIDIA
GPU, ≥ 8 GB VRAM; product Q-4) with zero egress (NFR-001), return a valid card ≥ 95% of the time
(NFR-012) and answer within p95 < 3 s warm (NFR-004). The documented GCP target (ADR 0005) uses
the same Ollama image on Cloud Run, so local and cloud share one serving stack.

## Options considered
1. **Ollama, `gemma4:e4b`, `/api/chat` with `format` = the card's JSON schema, temperature 0**:
   Pros: one-command install, schema-constrained decoding, same stack as Google's Cloud Run
   tutorial. Cons: less throughput than vLLM; tag/size naming to confirm (Q-3).
2. **vLLM with guided JSON decoding**: Pros: higher throughput. Cons: heavier setup on a desktop
   GPU, larger memory needs; not needed for one user.
3. **llama.cpp server with a GBNF grammar**: Pros: light. Cons: grammar to maintain; no advantage
   over Ollama for this scope.
4. **Hosted Gemma API (AI Studio / Vertex)**: Rejected: violates zero egress (NFR-001).
5. **Gemma 4 E2B or larger 26B/31B**: E2B is the fallback if E4B misses the latency target;
   26B/31B don't fit 8 GB VRAM.

## Decision
We will call a local Ollama server over HTTP (`httpx`, no Ollama SDK) with `gemma4:e4b`,
temperature 0, the card JSON schema as `format`, a 10 s timeout and one retry on invalid output.
Host, model tag and timeout come from environment variables. The client sits behind a small
`ModelClient` protocol so tests use a fake.

## Consequences
- Positive: no extra SDK dependency; easy to fake; identical serving stack for the documented
  cloud deployment.
- Negative / risks: model availability and naming (Q-3) are verified in the first task (spike);
  if p95 or validity misses NFR-004/NFR-012, try E2B or few-shot examples before cutting scope.
- Follow-ups: record measured numbers in `docs/measurements/` (REQ-012).
