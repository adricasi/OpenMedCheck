"""Run the open evaluation set (evals/cases.jsonl) and write a report (AC-012.4, T-015).

For every case the full check runs with the real local model (``check_service.final_card``)
and, as a baseline, with the rules alone on the coded record. The report gives, per finding
type, precision and recall of the kept note findings; final-status accuracy; the false-alarm
rate (cases expected NO_ISSUE that got a card) and the miss rate (cases expected WARNING or
BLOCKED that stayed silent); the silence rate; first-try validity; and latency. Aggregates and
case IDs only: no note text or model output is printed or written.

    uv run python scripts/eval_set.py                       # configured model (gemma4:e4b)
    uv run python scripts/eval_set.py --model gemma4:e2b    # compare another local model
    uv run python scripts/eval_set.py --rules-only          # no model: the rules baseline
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from openmedcheck import check_service, note_findings, rule_table, rules_engine
from openmedcheck.config import Config
from openmedcheck.contracts import CheckRequest, Status
from openmedcheck.model_client import (
    ModelOutcome,
    ModelRequest,
    ModelResult,
    OllamaClient,
    parse_model_output,
)

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "evals" / "cases.jsonl"


class RecordingClient(OllamaClient):
    """OllamaClient that keeps the last result and whether the first attempt was valid."""

    def __init__(
        self, base_url: str, model: str, *, deadline_s: float, api_key: str | None
    ) -> None:
        kwargs: dict[str, Any] = {"deadline_s": deadline_s}
        if api_key:
            kwargs["api_key"] = api_key
        super().__init__(base_url, model, **kwargs)
        self.last_result: ModelResult | None = None
        self.first_raw: str | None = None

    def assess(self, request: ModelRequest) -> ModelResult:
        self.first_raw = None
        self.last_result = super().assess(request)
        return self.last_result

    def _chat(self, request: ModelRequest, remaining_s: float) -> str:
        raw = super()._chat(request, remaining_s)
        if self.first_raw is None:
            self.first_raw = raw
        return raw


@dataclass
class Tally:
    expected_findings: Counter[str] = field(default_factory=Counter)
    kept_findings: Counter[str] = field(default_factory=Counter)
    true_positives: Counter[str] = field(default_factory=Counter)
    correct: int = 0
    total: int = 0
    false_alarms: int = 0
    expected_silent: int = 0
    misses: int = 0
    expected_card: int = 0
    silent: int = 0
    first_try_valid: int = 0
    model_calls: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    latencies_ms: list[float] = field(default_factory=list)
    wrong_cases: list[str] = field(default_factory=list)
    by_tag: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def finding_type(item: str) -> str:
    """CONDITION:<code> keeps its code; medications and allergies are grouped by kind."""
    kind = item.split(":")[0]
    return item if kind == "CONDITION" else kind


def record(tally: Tally, case: dict[str, Any], final: Status, kept: set[str]) -> None:
    expected = case["expected"]
    want = Status(expected["final_status"])
    tally.total += 1
    ok = final is want
    tally.correct += ok
    if not ok:
        tally.wrong_cases.append(f"{case['id']} (expected {want.value}, got {final.value})")
    for tag in case["tags"]:
        tally.by_tag[tag][0] += ok
        tally.by_tag[tag][1] += 1
    if want is Status.NO_ISSUE:
        tally.expected_silent += 1
        tally.false_alarms += final is not Status.NO_ISSUE
    else:
        tally.expected_card += 1
        tally.misses += final is Status.NO_ISSUE
    tally.silent += final is Status.NO_ISSUE
    expected_set = set(expected["findings"])
    for item in expected_set:
        tally.expected_findings[finding_type(item)] += 1
    for item in kept:
        tally.kept_findings[finding_type(item)] += 1
        if item in expected_set:
            tally.true_positives[finding_type(item)] += 1


def run_rules_only(cases: list[dict[str, Any]]) -> Tally:
    tally = Tally()
    for case in cases:
        request = CheckRequest.model_validate({"context": case["context"], "order": case["order"]})
        verdict = rules_engine.evaluate(request.context, request.order)
        record(tally, case, verdict.status, set())
    return tally


def run_model(cases: list[dict[str, Any]], client: RecordingClient, warmup: int) -> Tally:
    tally = Tally()
    requests = [
        CheckRequest.model_validate({"context": case["context"], "order": case["order"]})
        for case in cases
    ]
    for request in requests[:warmup]:
        check_service.final_card(request, client)
    for case, request in zip(cases, requests, strict=True):
        card = check_service.final_card(request, client)
        result = client.last_result
        if result is None:
            raise RuntimeError("final_card did not call the model client")
        tally.model_calls += 1
        tally.outcomes[result.outcome.value] += 1
        tally.latencies_ms.append(result.latency_ms)
        if client.first_raw is not None:
            model_request = ModelRequest(
                context=request.context,
                order=request.order,
                rules_verdict=rules_engine.evaluate(request.context, request.order),
                allowed_alternatives=check_service._allowed_alternatives(request.order.drug_id),
                drug_list=rule_table.DRUG_IDS,
            )
            try:
                parse_model_output(client.first_raw, model_request)
                tally.first_try_valid += 1
            except ValueError:
                pass
        kept: set[str] = set()
        if result.outcome is ModelOutcome.OK and result.verdict is not None:
            verified = note_findings.verify(result.verdict.note_findings, request.context)
            kept = {f"{item.kind.value}:{item.code}" for item in verified}
        record(tally, case, card.status, kept)
    return tally


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def ratio(part: int, whole: int) -> str:
    return f"{part}/{whole} = {part / whole:.0%}" if whole else "n/a"


def summary_rows(tally: Tally) -> list[tuple[str, str]]:
    rows = [
        ("Final status correct", ratio(tally.correct, tally.total)),
        (
            "False alarms (expected NO_ISSUE, got a card)",
            ratio(tally.false_alarms, tally.expected_silent),
        ),
        ("Misses (expected a card, stayed silent)", ratio(tally.misses, tally.expected_card)),
        ("Silence rate (all cases)", ratio(tally.silent, tally.total)),
    ]
    if tally.model_calls:
        latencies = tally.latencies_ms
        rows += [
            ("First-try valid model output", ratio(tally.first_try_valid, tally.model_calls)),
            ("Model outcomes", ", ".join(f"{k} {v}" for k, v in sorted(tally.outcomes.items()))),
            (
                "Model step latency",
                f"p50 {statistics.median(latencies):.0f} ms, "
                f"p95 {percentile(latencies, 95):.0f} ms",
            ),
        ]
    return rows


def finding_rows(tally: Tally) -> list[tuple[str, str, str]]:
    types = sorted(set(tally.expected_findings) | set(tally.kept_findings))
    return [
        (
            kind,
            ratio(tally.true_positives[kind], tally.kept_findings[kind]),
            ratio(tally.true_positives[kind], tally.expected_findings[kind]),
        )
        for kind in types
    ]


def ollama_version(url: str) -> str:
    """The Ollama server version for the report, or "unknown"."""
    try:
        with httpx.Client(base_url=url, timeout=5, trust_env=False) as http:
            return str(http.get("/api/version").json().get("version", "unknown"))
    except (httpx.HTTPError, ValueError):
        return "unknown"


def write_report(
    path: Path, model: str, cases: list[dict[str, Any]], baseline: Tally, gemma: Tally | None
) -> None:
    lines = [
        f"# Evaluation set report: {model} ({date.today().isoformat()})",
        "",
        "Spec: AC-012.3, AC-012.4, AC-003.6 to AC-003.8; task T-015. Generated by "
        "`scripts/eval_set.py` over `evals/cases.jsonl` "
        f"({len(cases)} synthetic cases). Aggregates and case IDs only: no note text or model "
        "output. Temperature 0, so repeated runs are nearly identical; this measures coverage of "
        "wordings, not sampling noise.",
        "",
        "## Summary",
        "",
        "| Measure | Rules only (coded record) | Rules + Gemma |",
        "|---|---|---|",
    ]
    base_rows = dict(summary_rows(baseline))
    model_rows = dict(summary_rows(gemma)) if gemma else {}
    for key in dict.fromkeys([*base_rows, *model_rows]):
        lines.append(f"| {key} | {base_rows.get(key, 'n/a')} | {model_rows.get(key, 'not run')} |")
    if gemma:
        lines += [
            "",
            "## Note findings (kept after quote verification)",
            "",
            "| Finding type | Precision | Recall |",
            "|---|---|---|",
        ]
        lines += [
            f"| {kind} | {precision} | {recall} |"
            for kind, precision, recall in finding_rows(gemma)
        ]
    lines += [
        "",
        "## Final-status accuracy by tag",
        "",
        "| Tag | Rules only | Rules + Gemma |",
        "|---|---|---|",
    ]
    for tag in sorted(baseline.by_tag):
        base_ok, base_n = baseline.by_tag[tag]
        model_cell = "not run"
        if gemma:
            model_ok, model_n = gemma.by_tag[tag]
            model_cell = ratio(model_ok, model_n)
        lines.append(f"| {tag} | {ratio(base_ok, base_n)} | {model_cell} |")
    if gemma:
        lines += ["", "## Cases with a wrong final status (Rules + Gemma)", ""]
        lines += [f"- {item}" for item in gemma.wrong_cases] or ["- none"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", help="local Ollama model tag (default: configured model)")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--rules-only", action="store_true", help="skip the model (CI-safe)")
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--out", type=Path, help="report path (default: docs/measurements/...)")
    args = parser.parse_args()

    import os

    config = Config.from_env(os.environ)
    model = args.model or config.model
    cases = load_cases(args.cases)
    baseline = run_rules_only(cases)
    gemma = None
    if not args.rules_only:
        client = RecordingClient(
            config.ollama_url,
            model,
            deadline_s=config.model_timeout_s,
            api_key=getattr(config, "ollama_api_key", None),
        )
        try:
            gemma = run_model(cases, client, args.warmup)
        finally:
            client.close()
    label = "rules-only" if args.rules_only else model.replace(":", "-")
    out = (
        args.out
        or ROOT / "docs" / "measurements" / f"{date.today().isoformat()}-eval-set-{label}.md"
    )
    write_report(out, model if gemma else "rules only", cases, baseline, gemma)
    used = model if gemma else "none"
    print(f"cases={len(cases)} model={used} ollama={ollama_version(config.ollama_url)}")
    for key, value in summary_rows(gemma or baseline):
        print(f"{key}: {value}")
    if gemma:
        for kind, precision, recall in finding_rows(gemma):
            print(f"findings {kind}: precision {precision}, recall {recall}")
        print("wrong:", ", ".join(gemma.wrong_cases) or "none")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
