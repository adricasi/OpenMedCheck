"""Breadth of conflicts: anticoagulants, potassium, heart failure, platelets, pregnancy (T-014)."""

from __future__ import annotations

from typing import Any

import pytest

from openmedcheck import note_findings, rule_table, rules_engine
from openmedcheck.check_service import rules_card
from openmedcheck.contracts import (
    CheckRequest,
    FindingKind,
    NoteFinding,
    Order,
    PatientContext,
    Status,
)
from openmedcheck.presets import PRESET_C


def context(**updates: Any) -> PatientContext:
    """A healthy adult (preset C) with the given changes; labs are merged, not replaced."""
    labs = updates.pop("labs", {})
    base = PRESET_C.request.context
    return base.model_copy(update={**updates, "labs": base.labs.model_copy(update=labs)})


def order(drug_id: str) -> Order:
    return Order(drug_id=drug_id, dose_text="test", route="PO", frequency="test")


def fired(ctx: PatientContext, drug_id: str) -> list[str]:
    return [rule.rule_id for rule in rules_engine.evaluate(ctx, order(drug_id)).fired_rules]


def status(ctx: PatientContext, drug_id: str) -> Status:
    return rules_engine.evaluate(ctx, order(drug_id)).status


# --- AC-002.9: NSAID with an oral anticoagulant ---------------------------------------------


@pytest.mark.parametrize("anticoagulant", ["acenocoumarol", "warfarin"])
def test_ac_002_9_nsaid_with_an_oral_anticoagulant_is_blocked(anticoagulant: str) -> None:
    ctx = context(chronic_medications=[anticoagulant])

    assert fired(ctx, "ibuprofen") == ["NSAID_ORAL_ANTICOAGULANT"]
    assert status(ctx, "ibuprofen") is Status.BLOCKED
    assert status(ctx, "paracetamol") is Status.NO_ISSUE


def test_ac_002_9_alternative_paracetamol_passes_the_recheck() -> None:
    request = CheckRequest(
        context=context(chronic_medications=["warfarin"]), order=order("naproxen")
    )

    card = rules_card(request)

    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"


# --- AC-002.10: ACE inhibitor or potassium-sparing drug and potassium ------------------------


@pytest.mark.parametrize(
    ("potassium", "expected_rules", "expected_status"),
    [
        (5.6, ["POTASSIUM_RAAS_ABOVE_5_5"], Status.BLOCKED),  # strictest only
        (5.5, ["POTASSIUM_RAAS_ABOVE_5_0"], Status.WARNING),  # equal to 5.5 does not fire it
        (5.0, [], Status.NO_ISSUE),  # equal to 5.0 does not fire
        (4.2, [], Status.NO_ISSUE),
        (None, ["POTASSIUM_UNKNOWN_RAAS"], Status.WARNING),
    ],
)
@pytest.mark.parametrize("drug_id", ["enalapril", "ramipril", "spironolactone"])
def test_ac_002_10_potassium_thresholds(
    drug_id: str, potassium: float | None, expected_rules: list[str], expected_status: Status
) -> None:
    ctx = context(labs={"potassium_mmol_l": potassium})

    assert fired(ctx, drug_id) == expected_rules
    assert status(ctx, drug_id) is expected_status


def test_ac_002_10_other_classes_ignore_potassium() -> None:
    assert fired(context(labs={"potassium_mmol_l": 6.5}), "paracetamol") == []


# --- AC-002.11: NSAID with heart failure -----------------------------------------------------


def test_ac_002_11_nsaid_with_heart_failure_warns_and_offers_paracetamol() -> None:
    request = CheckRequest(context=context(diagnoses=["HEART_FAILURE"]), order=order("diclofenac"))

    card = rules_card(request)

    assert card.status is Status.WARNING
    assert [rule.rule_id for rule in card.fired_rules] == ["NSAID_HEART_FAILURE"]
    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"


# --- AC-002.12: low platelets ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("drug_id", "platelets", "expected"),
    [
        ("enoxaparin", 49_000, Status.BLOCKED),
        ("warfarin", 30_000, Status.BLOCKED),
        ("enoxaparin", 50_000, Status.NO_ISSUE),  # equal to the threshold does not fire
        ("ibuprofen", 40_000, Status.WARNING),
        ("ibuprofen", 50_000, Status.NO_ISSUE),
        ("paracetamol", 10_000, Status.NO_ISSUE),
    ],
)
def test_ac_002_12_platelet_threshold(drug_id: str, platelets: float, expected: Status) -> None:
    assert status(context(labs={"platelets_per_ul": platelets}), drug_id) is expected


# --- AC-002.13: pregnancy -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("drug_id", "rule_id", "expected"),
    [
        ("enalapril", "PREGNANCY_ACE_INHIBITOR", Status.BLOCKED),
        ("warfarin", "PREGNANCY_ORAL_ANTICOAGULANT", Status.BLOCKED),
        ("ibuprofen", "PREGNANCY_NSAID", Status.WARNING),
    ],
)
def test_ac_002_13_pregnancy_list(drug_id: str, rule_id: str, expected: Status) -> None:
    ctx = context(diagnoses=["PREGNANCY"], labs={"potassium_mmol_l": 4.2})

    assert rule_id in fired(ctx, drug_id)
    assert status(ctx, drug_id) is expected


def test_ac_002_13_pregnancy_does_not_flag_paracetamol() -> None:
    assert status(context(diagnoses=["PREGNANCY"]), "paracetamol") is Status.NO_ISSUE


# --- AC-002.14: governance, and the note finds the new conditions ----------------------------

NEW_RULES = (
    "NSAID_ORAL_ANTICOAGULANT",
    "NSAID_HEART_FAILURE",
    "PREGNANCY_ACE_INHIBITOR",
    "PREGNANCY_ORAL_ANTICOAGULANT",
    "PREGNANCY_NSAID",
    "POTASSIUM_RAAS_ABOVE_5_5",
    "POTASSIUM_RAAS_ABOVE_5_0",
    "PLATELETS_ANTICOAGULANT_BELOW_50000",
    "PLATELETS_NSAID_BELOW_50000",
    "POTASSIUM_UNKNOWN_RAAS",
)


@pytest.mark.parametrize("rule_id", NEW_RULES)
def test_ac_002_14_new_rules_are_cited_and_not_reviewed(rule_id: str) -> None:
    entry = rule_table.RULES_BY_ID[rule_id]

    assert entry.source.strip()
    assert not rule_table.is_reviewed(entry)


@pytest.mark.parametrize(
    ("note", "code", "quote", "drug_id", "rule_id"),
    [
        (
            "32 weeks pregnant, back pain.",
            "PREGNANCY",
            "32 weeks pregnant",
            "ibuprofen",
            "PREGNANCY_NSAID",
        ),
        (
            "Known heart failure (HFrEF), ankle swelling.",
            "HEART_FAILURE",
            "Known heart failure",
            "naproxen",
            "NSAID_HEART_FAILURE",
        ),
    ],
)
def test_ac_002_14_new_conditions_come_from_the_note_with_a_quote(
    note: str, code: str, quote: str, drug_id: str, rule_id: str
) -> None:
    ctx = context(ed_note=note)
    found = (NoteFinding(kind=FindingKind.CONDITION, code=code, quote=quote),)

    kept = note_findings.verify(found, ctx)
    verdict = note_findings.evaluate(ctx, order(drug_id), kept)

    assert [rule.rule_id for rule in verdict.fired_rules] == [rule_id]
    assert verdict.fired_rules[0].evidence == [quote]


def test_ac_002_14_negated_pregnancy_is_dropped() -> None:
    ctx = context(ed_note="Not pregnant; pregnancy test negative.")
    found = (NoteFinding(kind=FindingKind.CONDITION, code="PREGNANCY", quote="pregnant"),)

    assert note_findings.verify(found, ctx) == ()


def test_ac_002_14_note_medication_from_the_new_list_needs_no_prompt_change() -> None:
    ctx = context(ed_note="Takes warfarin for atrial fibrillation.")
    found = (NoteFinding(kind=FindingKind.MEDICATION, code="warfarin", quote="Takes warfarin"),)

    verdict = note_findings.evaluate(ctx, order("ibuprofen"), note_findings.verify(found, ctx))

    assert [rule.rule_id for rule in verdict.fired_rules] == ["NSAID_ORAL_ANTICOAGULANT"]
    assert verdict.fired_rules[0].evidence == ["Takes warfarin"]


def test_ac_002_14_pregnancy_test_negative_is_not_a_finding() -> None:
    ctx = context(ed_note="Abdominal pain; pregnancy test negative.")
    found = (NoteFinding(kind=FindingKind.CONDITION, code="PREGNANCY", quote="pregnancy"),)

    assert note_findings.verify(found, ctx) == ()


def test_ac_002_14_lab_rule_groups_never_put_a_higher_status_on_a_lower_tier() -> None:
    groups: dict[tuple[str, str], list[rule_table.LabRule]] = {}
    for rule in rule_table.LAB_RULES:
        groups.setdefault((rule.lab, rule.conflict_type), []).append(rule)
    for rules in groups.values():
        for a in rules:
            for b in rules:
                if a.status.rank > b.status.rank:
                    assert a.risk_level.rank >= b.risk_level.rank, (a.rule_id, b.rule_id)
