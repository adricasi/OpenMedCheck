"""Note findings: verbatim-quote verification and rules on the augmented context (T-013)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from openmedcheck import note_findings, rules_engine
from openmedcheck.check_service import final_card
from openmedcheck.contracts import (
    CheckRequest,
    FindingKind,
    NoteFinding,
    Order,
    PatientContext,
    Source,
    Status,
)
from openmedcheck.logging_setup import ALLOWED_FIELDS
from openmedcheck.model_client import FakeModelClient
from openmedcheck.presets import PRESET_A, PRESET_C, PRESET_E
from tests.model_helpers import verdict_json
from tests.test_check_service import captured_log, parsed

ACS_QUOTE = "Suspected ACS"
PARACETAMOL = Order(drug_id="paracetamol", dose_text="1 g", route="PO", frequency="every 8 hours")
NO_ISSUE_WITH: dict[str, Any] = {
    "status": "NO_ISSUE",
    "risk_level": "LOW",
    "headline": "No conflict found",
    "rationale": "Nothing conflicts.",
    "conflict_type": None,
    "alternative_drug_id": None,
    "note_acs_quote": None,
}


def finding(kind: FindingKind, code: str, quote: str) -> NoteFinding:
    return NoteFinding(kind=kind, code=code, quote=quote)


def acs(quote: str = ACS_QUOTE) -> NoteFinding:
    return finding(FindingKind.CONDITION, "ACS", quote)


def context_with_note(note: str, **updates: Any) -> PatientContext:
    return PRESET_A.request.context.model_copy(update={"ed_note": note, **updates})


def model_json(*findings: NoteFinding, **overrides: Any) -> dict[str, Any]:
    data = verdict_json(**{**NO_ISSUE_WITH, **overrides})
    data["note_findings"] = [item.model_dump(mode="json") for item in findings]
    return data


def run(request: CheckRequest, *script: Any) -> Any:
    return final_card(request, FakeModelClient(list(script)))


# --- AC-003.6: verification --------------------------------------------------------------


def test_ac_003_6_keeps_a_verbatim_quote_ignoring_case_and_spacing() -> None:
    kept = note_findings.verify([acs("suspected   acs")], PRESET_A.request.context)

    # The card shows the note's own words, not the model's copy of them.
    assert kept == (acs("Suspected ACS"),)


def test_ac_003_6_accepts_a_quote_from_the_reason_for_consult() -> None:
    context = context_with_note("Pain since this morning.", reason_for_consult="Suspected ACS")

    assert note_findings.verify([acs()], context) == (acs(),)


@pytest.mark.parametrize(
    ("note", "item"),
    [
        ("Suspected ACS, no ST elevation on ECG.", acs()),
        ("Chest pain, likely NSTEMI.", acs("likely NSTEMI")),
        (
            "Stopped aspirin and started warfarin last week.",
            finding(FindingKind.MEDICATION, "warfarin", "started warfarin"),
        ),
        ("Chest pain on and off typical of angina.", acs("typical of angina")),
        ("Chest pain on and off angina.", acs("angina")),
        ("ACS not ruled out yet.", acs("ACS")),
        ("ACS hasn\u2019t been ruled out.", acs("ACS")),
        ("ACS isn't fully excluded.", acs("ACS")),
        ("Suspected ACS with troponin test negative so far.", acs()),
        (
            "Plan reviewed, meds stopped\nWarfarin daily for AF.",
            finding(FindingKind.MEDICATION, "warfarin", "Warfarin daily"),
        ),
        ("Warfarin not stopped.", finding(FindingKind.MEDICATION, "warfarin", "Warfarin")),
        ("Aspirin to be stopped tomorrow.", finding(FindingKind.MEDICATION, "aspirin", "Aspirin")),
        (
            "Coffee-ground vomiting this morning.",
            finding(FindingKind.CONDITION, "ACTIVE_GI_BLEED", "Coffee-ground vomiting"),
        ),
        ("Suspected ACS in a man with previous PCI.", acs()),
        ("Chest pain not relieved by rest, likely ACS.", acs("likely ACS")),
        (
            "No known allergies except anaphylaxis to ibuprofen.",
            finding(FindingKind.ALLERGY, "ibuprofen", "anaphylaxis to ibuprofen"),
        ),
        (
            "Takes clopidogrel daily, no other medication.",
            finding(FindingKind.MEDICATION, "clopidogrel", "Takes clopidogrel daily"),
        ),
    ],
)
def test_ac_003_6_negation_is_local_to_the_term(note: str, item: NoteFinding) -> None:
    """Safety review: a negation elsewhere in the sentence must not drop a real finding."""
    assert len(note_findings.verify([item], context_with_note(note))) == 1


@pytest.mark.parametrize(
    ("note", "item"),
    [
        ("Rash with tranexamic acid.", finding(FindingKind.ALLERGY, "aspirin", "tranexamic acid")),
        ("Pain over the sacs area.", acs("sacs area")),  # a term must start a word
        ("Chest pain since this morning.", acs("Chest pain")),  # names no ACS term
        ("Chest pain. ACS ruled out by troponin.", acs("ACS")),  # negated in its sentence
        (
            "No signs of GI bleeding.",
            finding(FindingKind.CONDITION, "ACTIVE_GI_BLEED", "GI bleeding"),
        ),
        ("History of ACS in 2019.", acs("ACS")),  # past history only
        ("Not on aspirin.", finding(FindingKind.MEDICATION, "aspirin", "aspirin")),
        (
            "Stopped warfarin two years ago.",
            finding(FindingKind.MEDICATION, "warfarin", "warfarin"),
        ),
        ("Off warfarin since surgery.", finding(FindingKind.MEDICATION, "warfarin", "warfarin")),
        ("Warfarin stopped last month.", finding(FindingKind.MEDICATION, "warfarin", "Warfarin")),
        ("Warfarin was discontinued.", finding(FindingKind.MEDICATION, "warfarin", "Warfarin")),
        ("Takes something daily.", finding(FindingKind.MEDICATION, "aspirin", "Takes something")),
    ],
)
def test_ac_003_6_drops_quotes_that_do_not_support_the_code(note: str, item: NoteFinding) -> None:
    assert note_findings.verify([item], context_with_note(note)) == ()


def test_ac_003_6_keeps_a_finding_described_without_st_elevation() -> None:
    context = context_with_note("Suspected ACS without ST elevation; troponin negative so far.")

    assert note_findings.verify([acs()], context) == (acs(),)


@pytest.mark.parametrize(
    "item",
    [
        acs("Confirmed STEMI on ECG"),  # invented: not in the note
        finding(FindingKind.CONDITION, "aspirin", ACS_QUOTE),  # code not valid for the kind
        finding(FindingKind.MEDICATION, "ACS", ACS_QUOTE),
        finding(FindingKind.MEDICATION, "warfarin", "On daily aspirin"),  # not on the drug list
        acs("AC"),  # too short
        acs(PRESET_A.request.context.ed_note),  # longer than 120 characters
    ],
)
def test_ac_003_6_drops_invented_or_invalid_findings(item: NoteFinding) -> None:
    assert note_findings.verify([item], PRESET_A.request.context) == ()


def test_ac_003_6_keeps_distinct_findings_up_to_the_cap() -> None:
    codes = note_findings.MEDICATION_CODES
    context = context_with_note(" ".join(f"Takes {code}." for code in codes))
    meds = [finding(FindingKind.MEDICATION, code, f"Takes {code}") for code in ("aspirin", *codes)]

    kept = note_findings.verify(meds, context)

    assert len(kept) == note_findings.MAX_FINDINGS
    assert len({item.code for item in kept}) == len(kept)


# --- AC-003.7: rules on the augmented context ----------------------------------------------


def test_ac_003_7_note_acs_makes_the_rules_block_preset_a_with_the_quote() -> None:
    request = PRESET_A.request

    verdict = note_findings.evaluate(request.context, request.order, (acs(),))

    assert verdict.status is Status.BLOCKED
    (rule,) = verdict.fired_rules
    assert rule.rule_id == "NSAID_ANTIPLATELET_ACS"
    assert rule.evidence == [ACS_QUOTE]


def test_ac_003_7_note_acs_does_not_fire_for_a_non_nsaid() -> None:
    verdict = note_findings.evaluate(PRESET_A.request.context, PARACETAMOL, (acs(),))

    assert verdict.status is Status.NO_ISSUE


def test_ac_003_7_rule_already_supported_by_the_record_carries_no_quote() -> None:
    context = PRESET_A.request.context.model_copy(update={"diagnoses": ["ACS"]})

    verdict = note_findings.evaluate(context, PRESET_A.request.order, (acs(),))

    assert [rule.evidence for rule in verdict.fired_rules] == [[]]


def test_ac_003_7_note_medication_completes_a_coded_rule_and_is_quoted() -> None:
    context = context_with_note(
        "Takes clopidogrel after a stent.", diagnoses=["ACS"], chronic_medications=[]
    )
    medication = finding(FindingKind.MEDICATION, "clopidogrel", "takes clopidogrel")

    verdict = note_findings.evaluate(context, PRESET_A.request.order, (medication,))

    (rule,) = verdict.fired_rules
    assert rule.rule_id == "NSAID_ANTIPLATELET_ACS"
    assert rule.evidence == ["takes clopidogrel"]


def test_ac_003_7_note_allergy_blocks_and_is_quoted() -> None:
    context = PRESET_C.request.context.model_copy(
        update={"ed_note": "Allergic to paracetamol (hives)."}
    )
    allergy = finding(FindingKind.ALLERGY, "paracetamol", "Allergic to paracetamol")

    verdict = note_findings.evaluate(context, PRESET_C.request.order, (allergy,))

    assert verdict.status is Status.BLOCKED
    assert verdict.fired_rules[0].evidence == ["Allergic to paracetamol"]


def test_ac_003_7_augment_only_adds() -> None:
    context = PRESET_E.request.context
    allergy = finding(FindingKind.ALLERGY, "NSAID", "NSAID")

    augmented = note_findings.augment(context, (allergy, acs()))

    assert set(context.allergies) <= set(augmented.allergies)
    assert augmented.allergies[-1] == "NSAID"
    assert augmented.diagnoses == ["ACS"]
    assert augmented.chronic_medications == context.chronic_medications


_findings = st.lists(
    st.one_of(
        st.builds(
            finding,
            st.just(FindingKind.CONDITION),
            st.sampled_from(note_findings.CONDITION_CODES),
            st.just("x"),
        ),
        st.builds(
            finding,
            st.just(FindingKind.MEDICATION),
            st.sampled_from(note_findings.MEDICATION_CODES),
            st.just("x"),
        ),
        st.builds(
            finding,
            st.just(FindingKind.ALLERGY),
            st.sampled_from(note_findings.ALLERGY_CODES),
            st.just("x"),
        ),
        st.builds(
            finding,
            st.just(FindingKind.HISTORY),
            st.sampled_from(note_findings.HISTORY_CODES),
            st.just("x"),
        ),
    ),
    max_size=4,
)
_orders = st.sampled_from(note_findings.MEDICATION_CODES)
_contexts = st.builds(
    lambda diagnoses, chronic, allergies, creatinine, egfr, age, weight, potassium, platelets, history: (  # noqa: E501
        PRESET_A.request.context.model_copy(
            update={
                "diagnoses": diagnoses,
                "history": history,
                "chronic_medications": chronic,
                "allergies": allergies,
                "age": age,
                "weight_kg": weight,
                "labs": PRESET_A.request.context.labs.model_copy(
                    update={
                        "creatinine_mg_dl": creatinine,
                        "egfr_ml_min_1_73m2": egfr,
                        "potassium_mmol_l": potassium,
                        "platelets_per_ul": platelets,
                    }
                ),
            }
        )
    ),
    st.lists(st.sampled_from(note_findings.CONDITION_CODES), unique=True),
    st.lists(st.sampled_from(note_findings.MEDICATION_CODES), max_size=3, unique=True),
    st.lists(st.sampled_from(note_findings.ALLERGY_CODES), max_size=2, unique=True),
    st.one_of(st.none(), st.floats(min_value=0.3, max_value=8)),
    st.one_of(st.none(), st.floats(min_value=5, max_value=120)),
    st.integers(min_value=18, max_value=100),
    st.floats(min_value=35, max_value=150),
    st.one_of(st.none(), st.floats(min_value=1.5, max_value=9)),
    st.one_of(st.none(), st.floats(min_value=1_000, max_value=2_000_000)),
    st.lists(st.sampled_from(note_findings.HISTORY_CODES), unique=True),
)


@given(context=_contexts, findings=_findings, drug_id=_orders)
def test_req_004_findings_never_make_the_rules_verdict_less_strict(
    context: PatientContext, findings: list[NoteFinding], drug_id: str
) -> None:
    order = PRESET_A.request.order.model_copy(update={"drug_id": drug_id})

    coded = rules_engine.evaluate(context, order)
    augmented = note_findings.evaluate(context, order, findings)

    assert augmented.status.rank >= coded.status.rank
    assert augmented.risk_level.rank >= coded.risk_level.rank
    assert {r.rule_id for r in coded.fired_rules} <= {r.rule_id for r in augmented.fired_rules}
    assert augmented.renal_adjustment_required >= coded.renal_adjustment_required


_model_status = st.sampled_from(["NO_ISSUE", "WARNING", "BLOCKED"])


_conflicts = st.sampled_from(["ANTIPLATELET_ACS", "GI_BLEED", "ALLERGY", "RENAL", "OTHER"])
_tiers = st.sampled_from(["LOW", "MODERATE", "HIGH", "CRITICAL"])


@given(
    context=_contexts,
    findings=_findings,
    drug_id=_orders,
    model_status=_model_status,
    conflict=_conflicts,
    tier=_tiers,
    renal=st.booleans(),
    negated=st.booleans(),
)
def test_req_004_full_check_with_findings_is_never_below_the_coded_rules(
    context: PatientContext,
    findings: list[NoteFinding],
    drug_id: str,
    model_status: str,
    conflict: str,
    tier: str,
    renal: bool,
    negated: bool,
) -> None:
    order = PRESET_A.request.order.model_copy(update={"drug_id": drug_id})
    # Quotes that exist in the note, so some findings survive verification.
    prefix = "No " if negated else ""
    note = " ".join(f"{prefix}{item.code} noted." for item in findings) or "Nothing else."
    context = context.model_copy(update={"ed_note": note})
    quoted = [item.model_copy(update={"quote": f"{item.code} noted"}) for item in findings]
    overrides: dict[str, Any] = {
        "status": model_status,
        "risk_level": "LOW" if model_status == "NO_ISSUE" else tier,
        "conflict_type": None if model_status == "NO_ISSUE" else conflict,
        "renal_adjustment_required": renal,
        "alternative_drug_id": None,
    }
    request = CheckRequest(context=context, order=order)

    card = run(request, model_json(*quoted, **overrides))
    coded = rules_engine.evaluate(context, order)

    assert card.status.rank >= coded.status.rank
    assert card.risk_level.rank >= coded.risk_level.rank
    assert card.renal_adjustment_required >= coded.renal_adjustment_required
    assert {r.rule_id for r in coded.fired_rules} <= {r.rule_id for r in card.fired_rules}


# --- the full check with a scripted model ---------------------------------------------------


def test_ac_003_7_full_check_blocks_preset_a_from_the_quote_even_if_the_model_says_no_issue() -> (
    None
):
    card = run(PRESET_A.request, model_json(acs()))

    assert card.status is Status.BLOCKED
    assert card.source is Source.RULES_MODEL
    assert card.fired_rules[0].evidence == [ACS_QUOTE]
    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"


def test_ac_003_6_full_check_ignores_an_invented_quote() -> None:
    card = run(PRESET_A.request, model_json(acs("Troponin positive, STEMI")))

    assert card.status is Status.NO_ISSUE
    assert card.fired_rules == []


def test_ac_003_7_alternative_is_rechecked_against_note_findings() -> None:
    note = PRESET_A.request.context.ed_note + " Allergic to paracetamol."
    request = CheckRequest(context=context_with_note(note), order=PRESET_A.request.order)
    allergy = finding(FindingKind.ALLERGY, "paracetamol", "Allergic to paracetamol")

    card = run(request, model_json(acs(), allergy))

    assert card.status is Status.BLOCKED
    assert card.alternative is None


def test_req_005_invalid_model_output_uses_no_findings() -> None:
    card = run(PRESET_A.request, "not json", "still not json")

    assert card.source is Source.RULES
    assert card.status is Status.WARNING  # note not checked (AC-005.3), no findings used
    assert card.fired_rules == []


def test_nfr_002_finding_counts_are_logged_and_quotes_are_not() -> None:
    invented = acs("Troponin positive, STEMI")
    with captured_log() as stream:
        run(PRESET_A.request, model_json(acs(), invented))

    (line,) = parsed(stream)
    assert {"note_findings_kept", "note_findings_dropped"} <= ALLOWED_FIELDS
    assert line["note_findings_kept"] == 1
    assert line["note_findings_dropped"] == 1
    assert ACS_QUOTE not in stream.getvalue()
    assert "STEMI" not in stream.getvalue()


# --- AC-003.8: rule-decided conflicts need the rules' confirmation -------------------------


def test_ac_003_8_unconfirmed_model_acs_escalation_is_set_aside() -> None:
    escalation = {**NO_ISSUE_WITH, "status": "BLOCKED", "risk_level": "HIGH"}
    escalation |= {"conflict_type": "ANTIPLATELET_ACS", "headline": "NSAID with suspected ACS"}
    escalation["rationale"] = "The note suggests ACS."
    with captured_log() as stream:
        card = run(PRESET_A.request, model_json(**escalation))

    assert card.status is Status.NO_ISSUE
    assert card.source is Source.RULES_MODEL
    (line,) = parsed(stream)
    assert line["model_escalation_gated"] is True


def test_ac_003_8_negated_note_does_not_block_even_if_the_model_says_acs() -> None:
    note = "Chest pain after lifting boxes. ACS ruled out: ECG and troponin normal."
    request = CheckRequest(context=context_with_note(note), order=PRESET_A.request.order)
    escalation = {**NO_ISSUE_WITH, "status": "BLOCKED", "risk_level": "HIGH"}
    escalation |= {"conflict_type": "ANTIPLATELET_ACS", "headline": "NSAID with suspected ACS"}
    escalation["rationale"] = "The note mentions ACS."

    card = run(request, model_json(acs("ACS ruled out"), **escalation))

    assert card.status is Status.NO_ISSUE
    assert card.fired_rules == []


def test_ac_003_8_model_escalation_confirmed_by_a_rule_is_kept() -> None:
    context = PRESET_A.request.context.model_copy(update={"diagnoses": ["ACS"]})
    request = CheckRequest(context=context, order=PRESET_A.request.order)
    escalation = {**NO_ISSUE_WITH, "status": "BLOCKED", "risk_level": "HIGH"}
    escalation |= {"conflict_type": "ANTIPLATELET_ACS", "headline": "NSAID with ACS"}
    escalation["rationale"] = "Coded ACS with an antiplatelet."

    card = run(request, model_json(**escalation))

    assert card.status is Status.BLOCKED


def test_ac_003_8_model_escalation_of_another_kind_still_counts() -> None:
    other = {**NO_ISSUE_WITH, "status": "WARNING", "risk_level": "MODERATE"}
    other |= {"conflict_type": "OTHER", "headline": "Review this order", "rationale": "Check it."}

    card = run(PRESET_C.request, model_json(**other))

    assert card.status is Status.WARNING


def test_ac_003_8_model_only_escalation_of_another_kind_reaches_the_card() -> None:
    other = {**NO_ISSUE_WITH, "status": "BLOCKED", "risk_level": "HIGH", "conflict_type": "OTHER"}
    other |= {"headline": "Order needs review now", "rationale": "The note raises a concern."}

    card = run(PRESET_A.request, model_json(**other))

    assert card.status is Status.BLOCKED
    assert card.source is Source.RULES_MODEL
    assert card.headline == "Order needs review now"


_GATE_CASES = {
    # conflict type: (request where no rule of that type fires, request where one does)
    "ANTIPLATELET_ACS": (
        PRESET_A.request,
        CheckRequest(
            context=PRESET_A.request.context.model_copy(update={"diagnoses": ["ACS"]}),
            order=PRESET_A.request.order,
        ),
    ),
    "GI_BLEED": (
        PRESET_C.request.model_copy(
            update={"order": Order(drug_id="ibuprofen", dose_text="x", route="PO", frequency="x")}
        ),
        CheckRequest(
            context=PRESET_C.request.context.model_copy(update={"diagnoses": ["ACTIVE_GI_BLEED"]}),
            order=Order(drug_id="ibuprofen", dose_text="x", route="PO", frequency="x"),
        ),
    ),
    "ALLERGY": (
        PRESET_C.request,
        CheckRequest(
            context=PRESET_C.request.context.model_copy(update={"allergies": ["paracetamol"]}),
            order=PRESET_C.request.order,
        ),
    ),
    "BLEEDING": (
        PRESET_C.request.model_copy(
            update={"order": Order(drug_id="ibuprofen", dose_text="x", route="PO", frequency="x")}
        ),
        CheckRequest(
            context=PRESET_C.request.context.model_copy(
                update={"chronic_medications": ["warfarin"]}
            ),
            order=Order(drug_id="ibuprofen", dose_text="x", route="PO", frequency="x"),
        ),
    ),
    "HYPERKALAEMIA": (
        CheckRequest(
            context=PRESET_C.request.context.model_copy(
                update={
                    "labs": PRESET_C.request.context.labs.model_copy(
                        update={"potassium_mmol_l": 4.2}
                    )
                }
            ),
            order=Order(drug_id="enalapril", dose_text="x", route="PO", frequency="x"),
        ),
        CheckRequest(
            context=PRESET_C.request.context.model_copy(
                update={
                    "labs": PRESET_C.request.context.labs.model_copy(
                        update={"potassium_mmol_l": 5.8}
                    )
                }
            ),
            order=Order(drug_id="enalapril", dose_text="x", route="PO", frequency="x"),
        ),
    ),
    "HEART_FAILURE": (
        PRESET_C.request.model_copy(
            update={"order": Order(drug_id="naproxen", dose_text="x", route="PO", frequency="x")}
        ),
        CheckRequest(
            context=PRESET_C.request.context.model_copy(update={"diagnoses": ["HEART_FAILURE"]}),
            order=Order(drug_id="naproxen", dose_text="x", route="PO", frequency="x"),
        ),
    ),
    "PREGNANCY": (
        PRESET_C.request,
        CheckRequest(
            context=PRESET_C.request.context.model_copy(update={"diagnoses": ["PREGNANCY"]}),
            order=Order(drug_id="ibuprofen", dose_text="x", route="PO", frequency="x"),
        ),
    ),
}


def _escalation(conflict: str) -> dict[str, Any]:
    data = {**NO_ISSUE_WITH, "status": "BLOCKED", "risk_level": "HIGH", "conflict_type": conflict}
    return data | {"headline": "Conflict found", "rationale": "The note raises a conflict."}


def test_ac_003_8_gate_cases_cover_every_rule_decided_conflict() -> None:
    from openmedcheck.check_service import RULE_DECIDED_CONFLICTS

    assert {c.value for c in RULE_DECIDED_CONFLICTS} == set(_GATE_CASES)


@pytest.mark.parametrize("conflict", sorted(_GATE_CASES))
def test_ac_003_8_unconfirmed_escalation_is_set_aside_for_each_type(conflict: str) -> None:
    unconfirmed, _ = _GATE_CASES[conflict]
    coded = rules_engine.evaluate(unconfirmed.context, unconfirmed.order)

    card = run(unconfirmed, model_json(**_escalation(conflict)))

    assert card.status is coded.status


@pytest.mark.parametrize("conflict", sorted(_GATE_CASES))
def test_ac_003_8_escalation_confirmed_by_a_rule_is_kept_for_each_type(conflict: str) -> None:
    _, confirmed = _GATE_CASES[conflict]

    card = run(confirmed, model_json(**_escalation(conflict)))

    assert card.status is Status.BLOCKED


@pytest.mark.parametrize(
    ("note", "item"),
    [
        (
            "Denies chest pain and GI bleeding.",
            finding(FindingKind.CONDITION, "ACTIVE_GI_BLEED", "GI bleeding"),
        ),
        ("No fever and melaena.", finding(FindingKind.CONDITION, "ACTIVE_GI_BLEED", "melaena")),
    ],
)
def test_ac_003_6_coordinated_negation_is_not_carried_across_and(
    note: str, item: NoteFinding
) -> None:
    """Known limit, kept on purpose: carrying a negator across "and" would also drop real
    findings ("No fever and suspected ACS"), a fail-open path. Over-alerting is the safe side."""
    assert len(note_findings.verify([item], context_with_note(note))) == 1


@pytest.mark.parametrize("note", ["Non-pregnant woman, migraine.", "Nonpregnant, headache."])
def test_ac_003_6_non_pregnant_is_negated(note: str) -> None:
    item = finding(FindingKind.CONDITION, "PREGNANCY", "pregnant")
    assert note_findings.verify([item], context_with_note(note)) == ()


def test_ac_003_6_non_st_elevation_acs_is_kept() -> None:
    assert (
        len(
            note_findings.verify(
                [acs("Non-ST elevation ACS")], context_with_note("Non-ST elevation ACS on ECG.")
            )
        )
        == 1
    )
