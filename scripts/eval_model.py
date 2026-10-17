"""Measure the real Ollama model path with the shipped prompt (T-005/T-009).

Runs cases A, A-alt (preset A re-checked with the paracetamol alternative), B and C through
``check_service.final_card`` with the real ``OllamaClient`` and prints aggregate statistics only:
outcome counts, first-try validity, invalid-reason codes, status/conflict distribution and
latency. All patients are synthetic presets; no patient context or model text is printed or
stored. Needs a local Ollama with the model tag.

    uv run python scripts/eval_model.py --calls 40 --warmup 3

The script reads the raw text of each attempt in memory (never printed) to recover the
first-try invalid reason and which drug ID tripped the AC-003.5 check; this uses two private
helpers of ``model_client`` and is therefore a measurement tool, not production code.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field

from openmedcheck import check_service, prompt, rule_table, rules_engine
from openmedcheck.config import Config
from openmedcheck.contracts import CheckRequest, Order
from openmedcheck.model_client import (
    InvalidModelOutput,
    ModelOutcome,
    ModelRequest,
    ModelResult,
    OllamaClient,
    _drug_name_patterns,
    _normalize,
    parse_model_output,
)
from openmedcheck.presets import PRESETS


class CapturingClient(OllamaClient):
    """OllamaClient that keeps the raw text of each attempt in memory for reason analysis."""

    def __init__(self, base_url: str, model: str, *, deadline_s: float) -> None:
        super().__init__(base_url, model, deadline_s=deadline_s)
        self.raw_attempts: list[str] = []
        self.last_result: ModelResult | None = None

    def assess(self, request: ModelRequest) -> ModelResult:
        self.last_result = super().assess(request)
        return self.last_result

    def _chat(self, request: ModelRequest, remaining_s: float) -> str:
        raw = super()._chat(request, remaining_s)
        self.raw_attempts.append(raw)
        return raw


@dataclass
class PresetStats:
    results: list[ModelResult] = field(default_factory=list)
    first_try_reasons: Counter[str] = field(default_factory=Counter)
    offending_drugs: Counter[str] = field(default_factory=Counter)
    verdicts: Counter[str] = field(default_factory=Counter)
    first_try_ok: int = 0
    final_cards: Counter[str] = field(default_factory=Counter)


def allowed_alternatives(drug_id: str) -> tuple[str, ...]:
    found = dict.fromkeys(
        alt.drug_id
        for (proposed, _), alts in rule_table.ALLOWED_ALTERNATIVES.items()
        if proposed == drug_id
        for alt in alts
    )
    return tuple(found)


def build_cases() -> dict[str, CheckRequest]:
    """Presets A, B, C plus A-alt: preset A's patient with the paracetamol alternative ordered.

    The dose text is user-entered and never sent to the model (data minimisation).
    """
    cases = {pid: preset.request for pid, preset in PRESETS.items()}
    alt = Order(drug_id="paracetamol", dose_text="1 g", route="PO", frequency="every 8 hours")
    cases["A-alt"] = cases["A"].model_copy(update={"order": alt})
    return {key: cases[key] for key in ("A", "A-alt", "B", "C")}


def build_request(check: CheckRequest) -> ModelRequest:
    order = check.order
    return ModelRequest(
        context=check.context,
        order=order,
        rules_verdict=rules_engine.evaluate(check.context, order),
        allowed_alternatives=allowed_alternatives(order.drug_id),
        drug_list=rule_table.DRUG_IDS,
    )


def percentile(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def other_drug_names(raw: str, request: ModelRequest) -> list[str]:
    """Drug IDs from the list that the (invalid) output names; IDs only, never text."""
    try:
        data = json.loads(raw)
        text = " ".join(str(data.get(key, "")) for key in ("headline", "rationale"))
        allowed = {request.order.drug_id, str(data.get("alternative_drug_id"))}
    except (ValueError, AttributeError):
        return []
    normalized = _normalize(text)
    return [
        drug_id
        for drug_id in request.drug_list
        if drug_id not in allowed
        and any(p.search(normalized) for p in _drug_name_patterns(drug_id))
    ]


def first_try_reason(raw: str, request: ModelRequest) -> str | None:
    try:
        parse_model_output(raw, request)
    except InvalidModelOutput as exc:
        return exc.reason
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=60, help="timed calls, cycling A, A-alt, B, C")
    parser.add_argument("--warmup", type=int, default=3)
    args = parser.parse_args()
    config = Config()
    client = CapturingClient(config.ollama_url, config.model, deadline_s=config.model_timeout_s)
    cases = build_cases()
    requests = {pid: build_request(check) for pid, check in cases.items()}
    order = list(cases)
    print(f"prompt_version={prompt.PROMPT_VERSION} model={config.model}")

    for index in range(args.warmup):
        check_service.final_card(cases[order[index % len(order)]], client)
    stats = {pid: PresetStats() for pid in order}
    for index in range(args.calls):
        pid = order[index % len(order)]
        request = requests[pid]
        client.raw_attempts.clear()
        card = check_service.final_card(cases[pid], client)
        result = client.last_result
        if result is None:
            raise RuntimeError("final_card did not call the model client")
        stat = stats[pid]
        verdict = result.verdict
        model_conflict = "n/a"
        if verdict is not None:
            model_conflict = verdict.conflict_type.value if verdict.conflict_type else "null"
        stat.final_cards[f"{card.status.value}/model:{model_conflict}/{card.source.value}"] += 1
        stat.results.append(result)
        if client.raw_attempts:
            reason = first_try_reason(client.raw_attempts[0], request)
            if reason is None:
                stat.first_try_ok += 1
            else:
                stat.first_try_reasons[reason] += 1
                if reason == "content:other_drug":
                    stat.offending_drugs.update(other_drug_names(client.raw_attempts[0], request))
        if result.verdict is not None:
            conflict = result.verdict.conflict_type
            label = conflict.value if conflict else "null"
            stat.verdicts[f"{result.verdict.status.value}/{label}"] += 1
    client.close()

    for pid in order:
        stat = stats[pid]
        n = len(stat.results)
        outcomes = Counter(r.outcome.value for r in stat.results)
        latencies = [r.latency_ms for r in stat.results]
        final_reasons = Counter(r.invalid_reason for r in stat.results if r.invalid_reason)
        print(f"\n== case {pid} ({n} calls), rules={requests[pid].rules_verdict.status.value}")
        shown = {k.value: outcomes.get(k.value, 0) for k in ModelOutcome}
        print("outcomes:", shown)
        print(f"first-try valid: {stat.first_try_ok}/{n} = {stat.first_try_ok / n:.0%}")
        print("first-try invalid reasons:", dict(stat.first_try_reasons))
        print("offending drug ids (other_drug, first try):", dict(stat.offending_drugs))
        print("final invalid reasons:", dict(final_reasons))
        print("verdicts (ok only):", dict(stat.verdicts))
        print("final card (status/model conflict/source):", dict(stat.final_cards))
        print(
            f"latency ms: p50={percentile(latencies, 50)} p95={percentile(latencies, 95)} "
            f"max={max(latencies)} mean={statistics.fmean(latencies):.0f}"
        )
        print("attempts:", dict(Counter(r.attempts for r in stat.results)))


if __name__ == "__main__":
    main()
