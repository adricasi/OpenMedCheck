# Open-model comparison on the evaluation set (2026-10-18)

Spec: AC-012.3, AC-012.4; task T-015. Synthetic cases from `evals/cases.jsonl` (76 cases after
the clinical review; 74 before), same verifier and rules, same machine: NVIDIA RTX 3000 Ada Generation Laptop GPU (8 GB),
Ollama 0.35.1, temperature 0, 10 s model deadline with one retry. Per-model reports:
[gemma4:e4b](2026-10-18-eval-set-gemma4-e4b.md), [gemma4:12b](2026-10-18-eval-set-gemma4-12b.md),
[gemma3:4b](2026-10-18-eval-set-gemma3-4b.md). Reproduce with
`uv run python scripts/eval_set.py --model <tag>`.

| | Final status matches label | False alarms (should stay silent) | Misses (should flag) | First-try valid | Model step p50 / p95 |
|---|---|---|---|---|---|
| Rules only (coded record), v7 set | 55/76 = 72% | 0/34 | 21/42 = 50% | n/a | n/a |
| **Gemma 4 E4B** (shipped), prompt v7 | **74/76 = 97%** | **0/34** | **1/42 = 2%** | **75/76** | **1.87 s / 2.49 s** |
| Gemma 3 4B, prompt v7 | 59/76 = 78% | 5/34 = 15% | 11/42 = 26% | 33/76 | 5.59 s / 7.13 s |
| Gemma 4 12B, prompt v7 | 61/76 = 80% | 0/34 | 14/42 = 33% | 45/76 | 9.62 s / 10.02 s (32 timeouts) |

Gemma 4 E4B note-finding precision was 100% for every type; recall was 100% except allergy
(5/6: the ibuprofen reaction inside an NSAID-allergy note) and active GI bleed (3/4:
"coffee-ground vomiting" was not extracted). Both new prompt-v7 cases (`acs-note-r-o`,
`hf-note-suspected`) were correct.

## What it shows
- **What the model adds.** The rules alone miss every case where the conflict is only in the
  free text (21/42). With Gemma 4 E4B reading the note and the rules deciding from its quoted
  findings, misses drop to 1/42 with no false alarm: the check stays silent on all 34 cases labelled
  NO_ISSUE (some are conflicts the rules do not cover, e.g. the known limit
  `allergy-cross-reactivity`).
- **Bigger is not better on this hardware.** Gemma 4 12B does not fit the 8 GB GPU comfortably:
  32 of 76 calls hit the 10 s deadline and fell back to the rules-only card (fail-safe, but the
  note-only conflicts are lost); on the shorter prompt v6 it was 20 of 74. On a larger GPU it may well do better; that is the point of
  measuring locally.
- **Older small models are noisier.** Gemma 3 4B produced invalid output on its first try in
  43 of 76 calls and raised 5 false alarms (its own escalations on conflicts the rules do not
  decide), which is exactly the alert fatigue the product is meant to avoid.
- **Open weights make this a decision, not a guess.** The same harness, data and code compare any
  local model; a hospital could re-run it on its own hardware and governed cases before choosing.

## Caveats
1. Synthetic notes written by the authors; temperature 0, so each model was run once per case.
   This measures coverage of wordings, not clinical validity.
2. **Development-set figure.** The cases, the prompt and the verifier were developed together by
   the same authors, so 97% is not a held-out estimate.
3. A first prompt-v7 run of Gemma 4 12B overlapped with a real-model test that swapped Gemma 4
   E4B onto the same 8 GB GPU (42 of 76 timeouts) and is not reported; the row above is a re-run
   with no other evaluation on the GPU (the local app was running but idle).
4. The two Gemma 4 E4B errors: one miss (`gi-coffee-ground`) and one stricter than the label
   (`pregnancy-note-nsaid`, expected WARNING, got BLOCKED, from the model's own escalation under
   a label the gate does not cover, ADR 0006).
