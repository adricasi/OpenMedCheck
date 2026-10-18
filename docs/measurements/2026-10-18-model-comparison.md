# Open-model comparison on the evaluation set (2026-10-18)

Spec: AC-012.3, AC-012.4; task T-015. Same 74 synthetic cases (`evals/cases.jsonl`), same prompt
(v6), same verifier and rules, same machine: NVIDIA RTX 3000 Ada Generation Laptop GPU (8 GB),
Ollama 0.35.1, temperature 0, 10 s model deadline with one retry. Per-model reports:
[gemma4:e4b](2026-10-18-eval-set-gemma4-e4b.md), [gemma4:12b](2026-10-18-eval-set-gemma4-12b.md),
[gemma3:4b](2026-10-18-eval-set-gemma3-4b.md). Reproduce with
`uv run python scripts/eval_set.py --model <tag>`.

| | Final status correct | False alarms (should stay silent) | Misses (should flag) | First-try valid | Model step p50 / p95 |
|---|---|---|---|---|---|
| Rules only (coded record) | 55/74 = 74% | 0/34 | 19/40 = 48% | n/a | n/a |
| **Gemma 4 E4B** (shipped) | **72/74 = 97%** | **0/34** | **1/40 = 2%** | **73/74** | **1.96 s / 2.36 s** |
| Gemma 4 12B | 62/74 = 84% | 0/34 | 10/40 = 25% | 54/74 | 8.74 s / 10.01 s (20 timeouts) |
| Gemma 3 4B | 50/74 = 68% | 12/34 = 35% | 11/40 = 28% | 33/74 | 5.63 s / 7.75 s |

Gemma 4 E4B finding precision was 100% for every type; recall 100% except active GI bleed (3/4:
"coffee-ground vomiting" was not extracted).

## What it shows
- **What the model adds.** The rules alone miss every case where the conflict is only in the
  free text (19/40). With Gemma 4 E4B reading the note and the rules deciding from its quoted
  findings, misses drop to 1/40 with no false alarm: the check stays silent on all 34 clean or
  negated cases.
- **Bigger is not better on this hardware.** Gemma 4 12B does not fit the 8 GB GPU comfortably:
  20 of 74 calls hit the 10 s deadline and fell back to the rules-only card (fail-safe, but the
  note-only conflicts are lost). On a larger GPU it may well do better; that is the point of
  measuring locally.
- **Older small models are noisier.** Gemma 3 4B produced invalid output on its first try in
  41 of 74 calls and raised 12 false alarms (its own escalations on conflicts the rules do not
  decide), which is exactly the alert fatigue the product is meant to avoid.
- **Open weights make this a decision, not a guess.** The same harness, data and code compare any
  local model; a hospital could re-run it on its own hardware and notes before choosing.

## Caveats
1. Synthetic notes written by the authors; temperature 0, so each model was run once per case.
   This measures coverage of wordings, not clinical validity.
2. The Gemma 4 12B and Gemma 3 4B runs used the verifier as it was before the last negation
   fixes of 2026-10-18 (stop cues and negators); the Gemma 4 E4B row is from the final code. The
   fixes only change which mentions count as negated; re-run the two models for an exact
   comparison.
3. The two Gemma 4 E4B misses: `gi-coffee-ground` (finding not extracted) and
   `pregnancy-note-nsaid` (expected WARNING, got BLOCKED: stricter, from the model's own
   escalation under a label the gate does not cover, ADR 0006).
