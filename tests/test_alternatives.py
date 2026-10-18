"""Alternative selection and combined-card tests (AC-001.3, AC-004.5 to AC-004.7, AC-004.9)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from openmedcheck import note_findings, rule_table, rules_engine
from openmedcheck.alternatives import select_alternative
from openmedcheck.check_service import combined_card, rules_card
from openmedcheck.combiner import NO_ISSUE_HEADLINE
from openmedcheck.contracts import (
    Alternative,
    CheckRequest,
    ConflictType,
    ModelVerdict,
    Order,
    PatientContext,
    RiskLevel,
    Source,
    Status,
)
from openmedcheck.presets import PRESETS
from openmedcheck.rule_table import (
    ALLOWED_ALTERNATIVES,
    CLASS_IDS,
    DOSE_FALLBACK_TEXT,
    DRUG_IDS,
    DRUGS_BY_ID,
    AllowedAlternative,
)

SIGNED = {"reviewed_by": "Dr Test", "reviewed_on": date(2026, 10, 17)}


def request_for(drug_id: str = "ibuprofen", **context: Any) -> CheckRequest:
    base: dict[str, Any] = {
        "patient_id": "SYN-T",
        "age": 50,
        "sex": "M",
        "weight_kg": 80,
        "labs": {"creatinine_mg_dl": 1.0, "egfr_ml_min_1_73m2": 90},
    }
    return CheckRequest.model_validate(
        {
            "context": {**base, **context},
            "order": {
                "drug_id": drug_id,
                "dose_text": "400 mg",
                "route": "PO",
                "frequency": "every 8 hours",
            },
        }
    )


def verdict(
    status: Status,
    *,
    conflict_type: ConflictType | None = None,
    alternative_drug_id: str | None = None,
    flag: bool = False,
    risk_level: RiskLevel = RiskLevel.HIGH,
) -> ModelVerdict:
    return ModelVerdict(
        status=status,
        risk_level=risk_level,
        headline="Model headline",
        rationale="Model rationale.",
        renal_adjustment_required=flag,
        conflict_type=conflict_type,
        alternative_drug_id=alternative_drug_id,
    )


def alternative_for(
    drug_id: str,
    proposed: str = "ibuprofen",
    conflict: ConflictType = ConflictType.GI_BLEED,
    **kw: Any,
) -> AllowedAlternative:
    return AllowedAlternative(
        proposed_drug_id=proposed,
        conflict_type=conflict,
        drug_id=drug_id,
        dose_text="1 g",
        route="PO",
        frequency="every 8 hours",
        reason="Test alternative.",
        source="test",
        **kw,
    )


def select(request: CheckRequest, **kwargs: Any) -> Any:
    defaults: dict[str, Any] = {
        "status": Status.BLOCKED,
        "conflict_type": ConflictType.GI_BLEED,
        "model_raised": False,
        "model_alternative_id": None,
    }
    return select_alternative(request.context, request.order, **{**defaults, **kwargs})


# --- AC-001.3 -------------------------------------------------------------------------------


def test_ac_001_3_blocked_card_offers_the_reviewed_rule_table_alternative() -> None:
    card = rules_card(request_for(diagnoses=["ACTIVE_GI_BLEED"]))
    assert card.status is Status.BLOCKED
    assert card.source is Source.RULES
    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"
    assert card.alternative.name == "Paracetamol"
    assert (card.alternative.dose_text, card.alternative.route, card.alternative.frequency) == (
        "1 g",
        "PO",
        "every 8 hours",
    )


def test_nfr_011_unreviewed_alternative_is_offered_by_name_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = ("ibuprofen", ConflictType.GI_BLEED)
    unsigned = tuple(
        replace(a, reviewed_by=None, reviewed_on=None) for a in ALLOWED_ALTERNATIVES[key]
    )
    monkeypatch.setitem(rule_table.ALLOWED_ALTERNATIVES, key, unsigned)

    card = rules_card(request_for(diagnoses=["ACTIVE_GI_BLEED"]))

    assert card.alternative is not None
    assert card.alternative.dose_text == DOSE_FALLBACK_TEXT
    assert (card.alternative.route, card.alternative.frequency) == ("", "")


def test_ac_001_3_no_issue_card_has_no_alternative() -> None:
    card = rules_card(PRESETS["C"].request)
    assert card.status is Status.NO_ISSUE
    assert card.alternative is None


def test_ac_001_3_no_alternative_exists_for_this_conflict() -> None:
    card = rules_card(PRESETS["B"].request)
    assert card.status is Status.WARNING
    assert card.alternative is None


def test_ac_001_3_alternative_that_fails_layer_one_is_not_included() -> None:
    request = request_for(diagnoses=["ACTIVE_GI_BLEED"], allergies=["paracetamol"])
    assert rules_card(request).alternative is None


def test_unknown_deciding_conflict_gives_no_alternative() -> None:
    assert select(request_for(), conflict_type=None) is None


# --- AC-004.6: reviewed doses, class, Layer 1 re-check ---------------------------------------


def test_nfr_011_reviewed_alternative_shows_its_dose(monkeypatch: pytest.MonkeyPatch) -> None:
    key = ("ibuprofen", ConflictType.GI_BLEED)
    monkeypatch.setitem(ALLOWED_ALTERNATIVES, key, (alternative_for("paracetamol", **SIGNED),))
    shown = select(request_for())
    assert (shown.dose_text, shown.route, shown.frequency) == ("1 g", "PO", "every 8 hours")


def test_ac_004_6b_same_class_alternative_is_excluded_only_when_the_model_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = ("ibuprofen", ConflictType.GI_BLEED)
    monkeypatch.setitem(ALLOWED_ALTERNATIVES, key, (alternative_for("naproxen"),))
    assert select(request_for(), model_raised=True) is None
    assert select(request_for(), model_raised=False).drug_id == "naproxen"


def test_ac_004_6c_warning_alternative_needs_a_reviewed_dose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = request_for(labs={"creatinine_mg_dl": 5.0, "egfr_ml_min_1_73m2": 90})
    key = ("ibuprofen", ConflictType.GI_BLEED)
    monkeypatch.setitem(ALLOWED_ALTERNATIVES, key, (alternative_for("ciprofloxacin"),))
    assert select(request) is None
    monkeypatch.setitem(ALLOWED_ALTERNATIVES, key, (alternative_for("ciprofloxacin", **SIGNED),))
    assert select(request).drug_id == "ciprofloxacin"


def test_ac_004_6c_blocked_alternative_is_never_shown_even_if_reviewed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = request_for(labs={"creatinine_mg_dl": 1.0, "egfr_ml_min_1_73m2": 20})
    key = ("ibuprofen", ConflictType.GI_BLEED)
    monkeypatch.setitem(ALLOWED_ALTERNATIVES, key, (alternative_for("metformin", **SIGNED),))
    assert select(request) is None


def test_ac_004_6_first_qualifying_candidate_in_table_order_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = ("ibuprofen", ConflictType.GI_BLEED)
    request = request_for(allergies=["paracetamol"])
    monkeypatch.setitem(
        ALLOWED_ALTERNATIVES,
        key,
        (
            alternative_for("paracetamol"),
            alternative_for("metamizole"),
            alternative_for("tramadol"),
        ),
    )
    assert select(request).drug_id == "metamizole"


def test_ac_004_6_the_models_pick_is_tried_first(monkeypatch: pytest.MonkeyPatch) -> None:
    key = ("ibuprofen", ConflictType.GI_BLEED)
    monkeypatch.setitem(
        ALLOWED_ALTERNATIVES, key, (alternative_for("paracetamol"), alternative_for("metamizole"))
    )
    assert select(request_for(), model_alternative_id="metamizole").drug_id == "metamizole"


def test_ac_004_6_the_models_pick_is_skipped_when_it_fails_layer_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = ("ibuprofen", ConflictType.GI_BLEED)
    monkeypatch.setitem(
        ALLOWED_ALTERNATIVES, key, (alternative_for("paracetamol"), alternative_for("metamizole"))
    )
    request = request_for(allergies=["metamizole"])
    assert select(request, model_alternative_id="metamizole").drug_id == "paracetamol"


# --- AC-004.7 and preset A -------------------------------------------------------------------


@pytest.mark.parametrize("suggestion", [*DRUG_IDS, "not_a_drug", "", "paracetamol 99 g"])
def test_ac_004_7_only_allowed_alternatives_are_ever_shown_for_preset_a(suggestion: str) -> None:
    model = verdict(
        Status.BLOCKED,
        conflict_type=ConflictType.ANTIPLATELET_ACS,
        alternative_drug_id=suggestion,
    )
    card, _ = combined_card(PRESETS["A"].request, model)
    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"
    assert DRUGS_BY_ID[card.alternative.drug_id].drug_class != "NSAID"


def test_ac_001_3_preset_a_final_card_is_blocked_with_reviewed_paracetamol() -> None:
    model = verdict(Status.BLOCKED, conflict_type=ConflictType.ANTIPLATELET_ACS)
    card, rejected = combined_card(PRESETS["A"].request, model, request_id="req-1")
    assert (card.status, card.source, card.request_id) == (
        Status.BLOCKED,
        Source.RULES_MODEL,
        "req-1",
    )
    assert not rejected
    assert card.alternative is not None
    assert (card.alternative.drug_id, card.alternative.dose_text) == ("paracetamol", "1 g")


# --- AC-004.2, AC-004.5, AC-004.9 end to end --------------------------------------------------


def test_ac_004_2_preset_b_keeps_warning_and_reports_the_rejected_downgrade() -> None:
    model = verdict(Status.NO_ISSUE, risk_level=RiskLevel.LOW)
    card, rejected = combined_card(PRESETS["B"].request, model)
    assert rejected
    assert card.status is Status.WARNING
    assert card.renal_adjustment_required
    assert card.headline != "Model headline"


def test_ac_004_5_rule_reasons_appear_even_if_the_model_text_omits_them() -> None:
    request = request_for(diagnoses=["ACTIVE_GI_BLEED"])
    card, _ = combined_card(
        request,
        verdict(Status.BLOCKED, conflict_type=ConflictType.GI_BLEED, risk_level=RiskLevel.CRITICAL),
    )
    reasons = [rule.reason for rule in card.fired_rules]
    assert reasons == [rule_table.RULES_BY_ID["NSAID_ACTIVE_GI_BLEED"].reason]
    assert card.rationale == "Model rationale."


def test_ac_004_9_no_issue_card_has_fixed_text_and_no_alternative() -> None:
    card, _ = combined_card(
        PRESETS["C"].request, verdict(Status.NO_ISSUE, risk_level=RiskLevel.LOW)
    )
    assert card.headline == NO_ISSUE_HEADLINE
    assert card.alternative is None
    assert card.source is Source.RULES_MODEL


def test_ac_001_2_multi_rule_rules_card_text_is_within_the_limits() -> None:
    request = request_for(
        diagnoses=["ACS", "ACTIVE_GI_BLEED"],
        chronic_medications=["aspirin"],
        allergies=["ibuprofen"],
    )
    card = rules_card(request)
    assert len(card.fired_rules) == 3
    assert len(card.rationale) <= 300
    assert card.rationale.count(". ") <= 1


# --- Property tests over the whole pipeline (AC-004.8, AC-004.6) ------------------------------

_labs = st.fixed_dictionaries(
    {},
    optional={
        "creatinine_mg_dl": st.floats(min_value=0.1, max_value=20),
        "egfr_ml_min_1_73m2": st.floats(min_value=0, max_value=200),
        "potassium_mmol_l": st.floats(min_value=1.5, max_value=9),
        "platelets_per_ul": st.floats(min_value=1_000, max_value=2_000_000),
    },
)

requests = st.builds(
    lambda drug, age, sex, weight, diagnoses, history, chronic, allergies, labs: (
        CheckRequest.model_validate(
            {
                "context": {
                    "patient_id": "SYN-P",
                    "age": age,
                    "sex": sex,
                    "weight_kg": weight,
                    "diagnoses": diagnoses,
                    "history": history,
                    "chronic_medications": chronic,
                    "allergies": allergies,
                    "labs": labs,
                },
                "order": {
                    "drug_id": drug,
                    "dose_text": "1 dose",
                    "route": "PO",
                    "frequency": "daily",
                },
            }
        )
    ),
    drug=st.sampled_from(DRUG_IDS),
    age=st.integers(18, 110),
    sex=st.sampled_from(["M", "F"]),
    weight=st.floats(30, 250),
    diagnoses=st.lists(st.sampled_from(note_findings.CONDITION_CODES), max_size=4, unique=True),
    history=st.lists(st.sampled_from(note_findings.HISTORY_CODES), unique=True),
    chronic=st.lists(st.sampled_from(DRUG_IDS), max_size=3, unique=True),
    allergies=st.lists(st.sampled_from([*DRUG_IDS, *CLASS_IDS]), max_size=2, unique=True),
    labs=_labs,
)

model_verdicts = st.none() | st.builds(
    ModelVerdict,
    status=st.sampled_from(Status),
    risk_level=st.sampled_from(RiskLevel),
    headline=st.text(),
    rationale=st.text(),
    renal_adjustment_required=st.booleans(),
    conflict_type=st.none() | st.sampled_from(ConflictType),
    alternative_drug_id=st.none() | st.sampled_from([*DRUG_IDS, "unknown"]) | st.text(),
)


@settings(max_examples=300)
@given(request=requests, model=model_verdicts)
def test_property_pipeline_invariants_hold_for_any_model_verdict(
    request: CheckRequest, model: ModelVerdict | None
) -> None:
    rules = rules_engine.evaluate(request.context, request.order)
    card, _ = combined_card(request, model)

    assert card.status.rank >= rules.status.rank
    assert card.risk_level.rank >= rules.risk_level.rank
    if rules.status is Status.BLOCKED:
        assert card.status is Status.BLOCKED
    if rules.renal_adjustment_required:
        assert card.renal_adjustment_required
    if card.renal_adjustment_required:
        assert card.status.rank >= Status.WARNING.rank
    assert [r.reason for r in card.fired_rules] == [r.reason for r in rules.fired_rules]  # AC-004.5
    assert card.headline
    assert card.rationale
    assert len(card.headline) <= 60
    assert len(card.rationale) <= 300
    if card.status is Status.NO_ISSUE:
        assert card.headline == NO_ISSUE_HEADLINE  # AC-004.9
        assert card.alternative is None  # AC-001.3

    alternative = card.alternative
    if alternative is None:
        return
    # AC-004.6 (a): listed for the proposed drug and a conflict type that can have raised it.
    if card.status is rules.status:
        conflicts = {r.conflict_type for r in rules.fired_rules}
    elif model is not None and model.status is card.status:
        conflicts = {model.conflict_type} if model.conflict_type else set()
    else:
        conflicts = {ConflictType.RENAL}
    allowed = [
        a
        for conflict in conflicts
        for a in ALLOWED_ALTERNATIVES.get((request.order.drug_id, conflict), ())
        if a.drug_id == alternative.drug_id
    ]
    assert allowed
    # AC-004.6 (b): outside the proposed class when the model raised the status.
    proposed_class = DRUGS_BY_ID[request.order.drug_id].drug_class
    if card.status.rank > rules.status.rank:
        assert DRUGS_BY_ID[alternative.drug_id].drug_class != proposed_class
    # AC-004.6 (c) and NFR-011: some listed entry explains the card. Its Layer 1 re-check is
    # NO_ISSUE, or WARNING with a reviewed dose; the dose appears only when that entry is
    # reviewed, and only from it. Several fired conflicts can list the same drug.
    assert any(_entry_explains(request.context, alternative, entry) for entry in allowed)


def _entry_explains(
    context: PatientContext, alternative: Alternative, entry: AllowedAlternative
) -> bool:
    rewritten = Order.model_validate(
        {
            "drug_id": entry.drug_id,
            "dose_text": entry.dose_text,
            "route": entry.route,
            "frequency": entry.frequency,
        }
    )
    recheck = rules_engine.evaluate(context, rewritten).status
    reviewed = rule_table.is_reviewed(entry)
    if not (recheck is Status.NO_ISSUE or (recheck is Status.WARNING and reviewed)):
        return False
    if reviewed:
        return (alternative.dose_text, alternative.route, alternative.frequency) == (
            entry.dose_text,
            entry.route,
            entry.frequency,
        )
    return alternative.dose_text == DOSE_FALLBACK_TEXT and (
        alternative.route,
        alternative.frequency,
    ) == ("", "")


def test_nfr_011_unreviewed_alternative_after_model_escalation_has_no_dose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = ("dexketoprofen", ConflictType.ANTIPLATELET_ACS)
    unsigned = tuple(
        replace(a, reviewed_by=None, reviewed_on=None) for a in ALLOWED_ALTERNATIVES[key]
    )
    monkeypatch.setitem(rule_table.ALLOWED_ALTERNATIVES, key, unsigned)
    model = verdict(Status.BLOCKED, conflict_type=ConflictType.ANTIPLATELET_ACS)

    card, _ = combined_card(PRESETS["A"].request, model)

    assert card.alternative is not None
    assert card.alternative.dose_text == DOSE_FALLBACK_TEXT
    assert not any(ch.isdigit() for ch in card.alternative.model_dump_json())


HISTORY_CONFLICTS = {ConflictType.PAST_GI_BLEED, ConflictType.ISCHAEMIC_HEART_DISEASE}


def test_nfr_011_every_alternative_is_reviewed_after_t_006() -> None:
    """The T-006 alternatives are signed; the history ones (REQ-016) await the specialist."""
    for (_, conflict), group in ALLOWED_ALTERNATIVES.items():
        for alternative in group:
            assert rule_table.is_reviewed(alternative) is (conflict not in HISTORY_CONFLICTS)
