"""The open evaluation set stays valid and consistent with the rules (AC-012.3, T-015).

Runs without a model, so contributed cases are checked in CI: every case is a valid request,
its expected findings use valid codes, its expected rules status matches the rules on the coded
record, and its expected final status matches the rules on the record plus the expected findings.
It checks the labels' arithmetic, not whether real note text yields those findings: that is what
the model run (scripts/eval_set.py) and the verifier tests in test_note_findings.py measure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openmedcheck import note_findings, rule_table, rules_engine
from openmedcheck.contracts import CheckRequest, FindingKind, NoteFinding, RulesVerdict

CASES_PATH = Path(__file__).parent.parent / "evals" / "cases.jsonl"
CASES: list[dict[str, Any]] = [
    json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()
]
CASE_KEYS = {"id", "tags", "description", "context", "order", "expected"}
EXPECTED_KEYS = {"findings", "rules_status", "final_status"}


def request_of(case: dict[str, Any]) -> CheckRequest:
    return CheckRequest.model_validate({"context": case["context"], "order": case["order"]})


def expected_findings(case: dict[str, Any]) -> tuple[NoteFinding, ...]:
    return tuple(
        NoteFinding(kind=FindingKind(item.split(":")[0]), code=item.split(":")[1], quote="x")
        for item in case["expected"]["findings"]
    )


def augmented_verdict(case: dict[str, Any]) -> RulesVerdict:
    request = request_of(case)
    context = note_findings.augment(request.context, expected_findings(case))
    return rules_engine.evaluate(context, request.order)


def test_ac_012_3_set_has_at_least_sixty_cases_with_unique_ids() -> None:
    assert len(CASES) >= 60
    assert len({case["id"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_ac_012_3_case_shape_and_codes(case: dict[str, Any]) -> None:
    assert set(case) == CASE_KEYS
    assert set(case["expected"]) == EXPECTED_KEYS
    assert case["tags"]
    assert case["context"]["patient_id"].startswith("SYN-")
    request_of(case)
    for item in case["expected"]["findings"]:
        kind, code = item.split(":")
        assert code in note_findings.CODES_BY_KIND[FindingKind(kind)], item


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_ac_012_3_expected_statuses_match_the_rules(case: dict[str, Any]) -> None:
    request = request_of(case)

    coded = rules_engine.evaluate(request.context, request.order)

    assert coded.status.value == case["expected"]["rules_status"]
    assert augmented_verdict(case).status.value == case["expected"]["final_status"]


def test_ac_012_3_every_rule_fires_in_at_least_one_case() -> None:
    fired = {rule.rule_id for case in CASES for rule in augmented_verdict(case).fired_rules}

    assert set(rule_table.RULES_BY_ID) - fired == set()


@pytest.mark.parametrize(
    "tag", ["note_only", "negation", "past_history", "abbreviation", "clean", "coded", "wording"]
)
def test_ac_012_3_set_covers_the_hard_kinds_of_wording(tag: str) -> None:
    assert any(tag in case["tags"] for case in CASES)
