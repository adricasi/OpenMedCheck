"""Past medical history in the record (REQ-016, T-018, ADR 0009)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from openmedcheck import note_findings, prompt, rule_table, rules_engine
from openmedcheck.check_service import final_card, rules_card
from openmedcheck.contracts import (
    CheckRequest,
    ConflictType,
    FindingKind,
    NoteFinding,
    Order,
    PatientContext,
    Source,
    Status,
)
from openmedcheck.model_client import FakeModelClient, ModelOutput
from openmedcheck.presets import PRESET_C, PRESETS
from tests.model_helpers import verdict_json

PACKAGE = Path(__file__).parent.parent / "src" / "openmedcheck"
NSAIDS = [drug.drug_id for drug in rule_table.DRUGS if drug.drug_class == "NSAID"]
HISTORY_RULES = ("NSAID_HISTORY_GI_BLEED", "NSAID_HISTORY_ISCHAEMIC_HEART_DISEASE")


def context(**updates: Any) -> PatientContext:
    """A healthy adult (preset C) with the given changes."""
    return PRESET_C.request.context.model_copy(update=updates)


def order(drug_id: str) -> Order:
    return Order(drug_id=drug_id, dose_text="test", route="PO", frequency="test")


def fired(ctx: PatientContext, drug_id: str) -> list[str]:
    return [rule.rule_id for rule in rules_engine.evaluate(ctx, order(drug_id)).fired_rules]


# --- AC-016.1: the coded history field -------------------------------------------------------


def test_ac_016_1_history_defaults_to_empty_and_accepts_the_two_codes() -> None:
    assert PRESET_C.request.context.history == []
    ctx = PatientContext.model_validate(
        {
            **PRESET_C.request.context.model_dump(),
            "history": ["PAST_GI_BLEED", "ISCHAEMIC_HEART_DISEASE"],
        }
    )

    assert ctx.history == ["PAST_GI_BLEED", "ISCHAEMIC_HEART_DISEASE"]


def test_ac_016_1_history_rejects_an_unknown_code() -> None:
    with pytest.raises(ValidationError):
        PatientContext.model_validate(
            {**PRESET_C.request.context.model_dump(), "history": ["STROKE"]}
        )


def test_ac_016_1_the_model_sees_the_recorded_history() -> None:
    _, user = prompt.build_messages(
        context(history=["PAST_GI_BLEED"]),
        order("ibuprofen"),
        rules_engine.evaluate(context(history=["PAST_GI_BLEED"]), order("ibuprofen")),
        (),
    )

    assert "Past medical history: PAST_GI_BLEED." in user["content"]
    # Coded values only, outside the untrusted note block.
    assert user["content"].index("Past medical history") < user["content"].index(
        prompt.NOTE_OPEN_TAG
    )


def test_ac_016_1_the_record_shows_and_sends_the_history() -> None:
    html = (PACKAGE / "templates" / "index.html").read_text()
    script = (PACKAGE / "static" / "app.js").read_text()

    assert 'id="ro-history"' in html
    assert 'value="PAST_GI_BLEED" data-history' in html
    assert 'value="ISCHAEMIC_HEART_DISEASE" data-history' in html
    assert "history: state.hidden.history," in script
    assert '$("ro-history").textContent' in script


# --- AC-016.2: the two rules -----------------------------------------------------------------


@pytest.mark.parametrize("nsaid", NSAIDS)
def test_ac_016_2_nsaid_with_a_past_gi_bleed_warns(nsaid: str) -> None:
    ctx = context(history=["PAST_GI_BLEED"])

    assert fired(ctx, nsaid) == ["NSAID_HISTORY_GI_BLEED"]
    assert rules_engine.evaluate(ctx, order(nsaid)).status is Status.WARNING


@pytest.mark.parametrize("nsaid", NSAIDS)
def test_ac_016_2_nsaid_with_ischaemic_heart_disease_warns(nsaid: str) -> None:
    ctx = context(history=["ISCHAEMIC_HEART_DISEASE"])

    assert fired(ctx, nsaid) == ["NSAID_HISTORY_ISCHAEMIC_HEART_DISEASE"]
    assert rules_engine.evaluate(ctx, order(nsaid)).status is Status.WARNING


@pytest.mark.parametrize("drug", ["paracetamol", "aspirin", "clopidogrel", "tramadol"])
def test_ac_016_2_history_rules_ignore_drugs_outside_the_nsaid_class(drug: str) -> None:
    ctx = context(history=["PAST_GI_BLEED", "ISCHAEMIC_HEART_DISEASE"])

    assert not set(fired(ctx, drug)) & set(HISTORY_RULES)


def test_ac_016_2_without_history_no_history_rule_fires() -> None:
    assert not set(fired(context(), "ibuprofen")) & set(HISTORY_RULES)


def test_ac_016_2_history_never_lowers_a_current_conflict() -> None:
    """A current ACS with a home antiplatelet stays BLOCKED when history is added (REQ-004)."""
    current = context(diagnoses=["ACS"], chronic_medications=["aspirin"])
    with_history = current.model_copy(update={"history": ["ISCHAEMIC_HEART_DISEASE"]})

    before = rules_engine.evaluate(current, order("ibuprofen"))
    after = rules_engine.evaluate(with_history, order("ibuprofen"))

    assert before.status is Status.BLOCKED
    assert after.status is Status.BLOCKED
    assert after.risk_level.rank >= before.risk_level.rank
    assert {"NSAID_ANTIPLATELET_ACS", "NSAID_HISTORY_ISCHAEMIC_HEART_DISEASE"} <= {
        rule.rule_id for rule in after.fired_rules
    }


@pytest.mark.parametrize("preset_id", ["J", "K"])
def test_ac_016_2_history_templates_offer_paracetamol_after_the_recheck(preset_id: str) -> None:
    card = rules_card(PRESETS[preset_id].request)

    assert card.status is Status.WARNING
    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"
    recheck = rules_card(
        CheckRequest(
            context=PRESETS[preset_id].request.context,
            order=Order(
                drug_id="paracetamol", dose_text="1 g", route="PO", frequency="every 8 hours"
            ),
        )
    )
    assert recheck.status is Status.NO_ISSUE


# --- AC-016.3: cited, not reviewed yet -------------------------------------------------------


@pytest.mark.parametrize("rule_id", HISTORY_RULES)
def test_ac_016_3_history_rules_are_cited_and_await_review(rule_id: str) -> None:
    rule = rule_table.RULES_BY_ID[rule_id]

    assert rule.source.strip()
    assert not rule_table.is_reviewed(rule)
    assert rule.status is Status.WARNING
    assert rule.conflict_type in (
        ConflictType.PAST_GI_BLEED,
        ConflictType.ISCHAEMIC_HEART_DISEASE,
    )
    assert any(rule_id in question for question in rule_table.SPECIALIST_QUESTIONS)


# --- AC-016.4: past history read from the note (T-019) ---------------------------------------


def history_finding(code: str, quote: str) -> NoteFinding:
    return NoteFinding(kind=FindingKind.HISTORY, code=code, quote=quote)


def kept(note: str, code: str, quote: str) -> bool:
    ctx = context(ed_note=note)
    return bool(note_findings.verify([history_finding(code, quote)], ctx))


@pytest.mark.parametrize(
    ("note", "code", "quote"),
    [
        ("Previous GI bleed in 2015, none since.", "PAST_GI_BLEED", "Previous GI bleed"),
        ("Previous GI bleed in 2015, resolved.", "PAST_GI_BLEED", "Previous GI bleed in 2015"),
        ("Shoulder pain. h/o peptic ulcer 2018.", "PAST_GI_BLEED", "h/o peptic ulcer"),
        ("Prior perforated ulcer in 2012.", "PAST_GI_BLEED", "perforated ulcer"),
        ("History of ACS in 2019 with a stent.", "ISCHAEMIC_HEART_DISEASE", "History of ACS"),
        ("Back pain. PCI with a stent in 2021.", "ISCHAEMIC_HEART_DISEASE", "PCI with a stent"),
        ("Prior MI, on aspirin.", "ISCHAEMIC_HEART_DISEASE", "Prior MI"),
        ("Known IHD, stable angina.", "ISCHAEMIC_HEART_DISEASE", "Known IHD"),
        ("Heart attack in 2018.", "ISCHAEMIC_HEART_DISEASE", "Heart attack in 2018"),
    ],
)
def test_ac_016_4_past_history_in_the_note_is_kept(note: str, code: str, quote: str) -> None:
    assert kept(note, code, quote)


@pytest.mark.parametrize(
    ("note", "code", "quote"),
    [
        ("No history of GI bleeding or ulcers.", "PAST_GI_BLEED", "history of GI bleeding"),
        ("Denies previous MI or angina.", "ISCHAEMIC_HEART_DISEASE", "previous MI"),
        (
            "Never had a heart attack or angina.",
            "ISCHAEMIC_HEART_DISEASE",
            "heart attack or angina",
        ),
        ("His mother had a GI bleed on NSAIDs.", "PAST_GI_BLEED", "GI bleed"),
        ("Father had an MI at 50.", "ISCHAEMIC_HEART_DISEASE", "MI"),
        ("FHx of coronary disease.", "ISCHAEMIC_HEART_DISEASE", "coronary disease"),
        ("Previous MI ruled out by angiography.", "ISCHAEMIC_HEART_DISEASE", "Previous MI"),
        ("Mild chest wall tenderness.", "ISCHAEMIC_HEART_DISEASE", "Mild chest"),
    ],
)
def test_ac_016_4_denied_relative_or_unrelated_history_is_dropped(
    note: str, code: str, quote: str
) -> None:
    assert not kept(note, code, quote)


def test_ac_016_4_past_history_is_still_not_a_current_condition() -> None:
    """ADR 0009: "History of ACS" never becomes a current ACS (no BLOCKED for an old event)."""
    ctx = context(ed_note="History of ACS in 2019 with a stent.", chronic_medications=["aspirin"])
    acs = NoteFinding(kind=FindingKind.CONDITION, code="ACS", quote="History of ACS")

    assert note_findings.verify([acs], ctx) == ()


def test_ac_016_4_a_kept_history_finding_fires_the_rule_with_the_quote() -> None:
    ctx = context(ed_note="Low back pain. Previous GI bleed in 2015, none since.")
    findings = note_findings.verify([history_finding("PAST_GI_BLEED", "Previous GI bleed")], ctx)

    verdict = note_findings.evaluate(ctx, order("ibuprofen"), findings)

    assert note_findings.augment(ctx, findings).history == ["PAST_GI_BLEED"]
    assert verdict.status is Status.WARNING
    (rule,) = verdict.fired_rules
    assert rule.rule_id == "NSAID_HISTORY_GI_BLEED"
    assert rule.evidence == ["Previous GI bleed"]


def test_ac_016_4_the_model_answers_note_history_in_its_own_field() -> None:
    schema = prompt.build_schema(())
    history = schema["properties"]["note_history"]

    assert "note_history" in schema["required"]
    assert history["items"]["properties"]["code"]["enum"] == list(note_findings.HISTORY_CODES)
    assert "note_history" in prompt.SYSTEM_PROMPT
    output = ModelOutput.model_validate_json(
        json.dumps(
            {
                **verdict_json(status="NO_ISSUE", conflict_type=None, alternative_drug_id=None),
                "note_acs_quote": None,
                "note_history": [{"code": "PAST_GI_BLEED", "quote": "Previous GI bleed"}],
            }
        )
    )
    assert (
        history_finding("PAST_GI_BLEED", "Previous GI bleed") in output.to_verdict().note_findings
    )


def test_ac_016_4_full_check_warns_on_history_only_in_the_note() -> None:
    request = CheckRequest(
        context=context(ed_note="Low back pain. Previous GI bleed in 2015, none since."),
        order=order("ibuprofen"),
    )
    answer = {
        **verdict_json(status="NO_ISSUE", conflict_type=None, alternative_drug_id=None),
        "note_acs_quote": None,
        "note_history": [{"code": "PAST_GI_BLEED", "quote": "Previous GI bleed in 2015"}],
    }

    card = final_card(request, FakeModelClient([answer]))

    assert card.status is Status.WARNING
    (rule,) = card.fired_rules
    assert rule.rule_id == "NSAID_HISTORY_GI_BLEED"
    assert rule.evidence == ["Previous GI bleed in 2015"]
    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"


@pytest.mark.parametrize(
    ("note", "code", "quote"),
    [
        ("Two previous MIs, last in 2019.", "ISCHAEMIC_HEART_DISEASE", "Two previous MIs"),
        ("Hx PUD, on omeprazole.", "PAST_GI_BLEED", "Hx PUD"),
        ("Ischaemic heart disease, on aspirin.", "ISCHAEMIC_HEART_DISEASE", "Ischaemic heart"),
        ("No chest pain since MI in 2019.", "ISCHAEMIC_HEART_DISEASE", "MI in 2019"),
        ("Brought in by daughter, previous MI.", "ISCHAEMIC_HEART_DISEASE", "previous MI"),
        ("Previous MI; family history of diabetes.", "ISCHAEMIC_HEART_DISEASE", "Previous MI"),
        ("Upper  GI   bleed in 2016.", "PAST_GI_BLEED", "GI bleed"),
    ],
)
def test_ac_016_4_specific_history_wording_is_kept(note: str, code: str, quote: str) -> None:
    assert kept(note, code, quote)


@pytest.mark.parametrize(
    ("note", "code", "quote"),
    [
        ("Family history: MI.", "ISCHAEMIC_HEART_DISEASE", "MI"),
        ("Mother: MI at 60.", "ISCHAEMIC_HEART_DISEASE", "MI at 60"),
        ("Brothers both had MIs.", "ISCHAEMIC_HEART_DISEASE", "MIs"),
        ("Family history of diabetes and MI.", "ISCHAEMIC_HEART_DISEASE", "MI"),
        ("FH of peptic ulcer.", "PAST_GI_BLEED", "peptic ulcer"),
        ("No known history of peptic ulcer disease.", "PAST_GI_BLEED", "peptic ulcer disease"),
        ("Nil previous GI bleed.", "PAST_GI_BLEED", "GI bleed"),
        ("Diabetic foot ulcer, dressed.", "PAST_GI_BLEED", "foot ulcer"),
        ("Ulcerative colitis in remission.", "PAST_GI_BLEED", "Ulcerative colitis"),
        ("Perforated eardrum as a child.", "PAST_GI_BLEED", "Perforated eardrum"),
        ("Nose bleed last week.", "PAST_GI_BLEED", "Nose bleed"),
        ("Ureteric stent in 2020.", "ISCHAEMIC_HEART_DISEASE", "Ureteric stent"),
        ("Old cerebral infarct on CT.", "ISCHAEMIC_HEART_DISEASE", "cerebral infarct"),
        ("Angiogram: normal coronary arteries.", "ISCHAEMIC_HEART_DISEASE", "normal coronary"),
    ],
)
def test_ac_016_4_family_denied_or_other_organ_history_is_dropped(
    note: str, code: str, quote: str
) -> None:
    assert not kept(note, code, quote)


# --- AC-003.8: a history rule decides only its own conflict ----------------------------------


def _model(status: str, conflict_type: str) -> dict[str, Any]:
    return {
        **verdict_json(
            status=status, conflict_type=conflict_type, alternative_drug_id="paracetamol"
        ),
        "note_acs_quote": None,
    }


def test_ac_003_8_a_history_rule_does_not_unlock_a_blocked_current_conflict() -> None:
    """A past GI bleed (WARNING) does not confirm the model's BLOCKED active GI bleed."""
    request = CheckRequest(context=context(history=["PAST_GI_BLEED"]), order=order("ibuprofen"))

    card = final_card(request, FakeModelClient([_model("BLOCKED", "GI_BLEED")]))

    assert card.status is Status.WARNING
    assert [rule.rule_id for rule in card.fired_rules] == ["NSAID_HISTORY_GI_BLEED"]


@pytest.mark.parametrize(
    ("history", "conflict"),
    [("PAST_GI_BLEED", "PAST_GI_BLEED"), ("ISCHAEMIC_HEART_DISEASE", "ISCHAEMIC_HEART_DISEASE")],
)
def test_ac_003_8_model_blocked_for_a_history_conflict_is_capped_at_warning(
    history: str, conflict: str
) -> None:
    request = CheckRequest(context=context(history=[history]), order=order("ibuprofen"))

    card = final_card(request, FakeModelClient([_model("BLOCKED", conflict)]))

    assert card.status is Status.WARNING
    assert card.alternative is not None
    assert card.alternative.dose_text == rule_table.DOSE_FALLBACK_TEXT


def test_ac_016_4_invalid_note_history_twice_gives_the_rules_only_card() -> None:
    request = CheckRequest(context=context(history=["PAST_GI_BLEED"]), order=order("ibuprofen"))
    bad = {**_model("WARNING", "PAST_GI_BLEED"), "note_history": [{"code": "PAST_GI_BLEED"}]}

    card = final_card(request, FakeModelClient([bad, bad]))

    assert card.source is Source.RULES
    assert card.status is Status.WARNING


def test_ac_016_4_an_unknown_history_code_is_dropped_by_the_verifier() -> None:
    request = CheckRequest(context=context(ed_note="Stroke in 2019."), order=order("ibuprofen"))
    answer = {
        **_model("NO_ISSUE", "PAST_GI_BLEED"),
        "conflict_type": None,
        "alternative_drug_id": None,
        "note_history": [{"code": "STROKE", "quote": "Stroke in 2019"}],
    }

    card = final_card(request, FakeModelClient([answer]))

    assert card.source is Source.RULES_MODEL
    assert card.status is Status.NO_ISSUE


def test_ac_003_6_max_findings_matches_the_prompt_limits() -> None:
    """One quote per condition plus three items for each of the three listed note fields."""
    expected = len(note_findings.CONDITION_CODES) + 3 * prompt._MAX_LISTED
    assert expected == note_findings.MAX_FINDINGS


# --- AC-016.6: Bed 15, a past GI bleed buried in a long history -------------------------------

BED_15_QUOTE = "upper GI bleed from a duodenal ulcer in 2021"


def test_ac_016_6_bed_15_looks_routine_to_the_rules() -> None:
    preset = PRESETS["L"]
    request = preset.request

    assert preset.bed == "Bed 15"
    assert request.context.history == []
    assert request.context.diagnoses == []
    assert BED_15_QUOTE in request.context.ed_note
    assert rules_card(request).status is Status.NO_ISSUE


def test_ac_016_6_bed_15_warns_once_the_model_finds_the_history() -> None:
    answer = {
        **verdict_json(status="NO_ISSUE", conflict_type=None, alternative_drug_id=None),
        "note_acs_quote": None,
        "note_history": [{"code": "PAST_GI_BLEED", "quote": BED_15_QUOTE}],
    }

    card = final_card(PRESETS["L"].request, FakeModelClient([answer]))

    assert card.status is Status.WARNING
    (rule,) = card.fired_rules
    assert rule.rule_id == "NSAID_HISTORY_GI_BLEED"
    assert rule.evidence == [BED_15_QUOTE]
    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"
    assert card.alternative.dose_text == rule_table.DOSE_FALLBACK_TEXT


def test_ac_016_6_bed_15_past_bleed_is_not_a_current_bleed() -> None:
    """Misread as a current bleed, the list item would make the card BLOCKED (AC-016.7)."""
    answer = {
        **verdict_json(status="NO_ISSUE", conflict_type=None, alternative_drug_id=None),
        "note_acs_quote": None,
        "note_gi_bleed_quote": BED_15_QUOTE,
    }

    card = final_card(PRESETS["L"].request, FakeModelClient([answer]))

    assert card.status is Status.NO_ISSUE


# --- AC-016.7: past-history labels ----------------------------------------------------------


@pytest.mark.parametrize(
    ("note", "code", "quote"),
    [
        ("PMH: hypertension, GI bleed in 2019.", "ACTIVE_GI_BLEED", "GI bleed in 2019"),
        ("Past medical history: asthma, NSTEMI 2020.", "ACS", "NSTEMI 2020"),
        ("Background: angina, CABG in 2016.", "ACS", "angina"),
    ],
)
def test_ac_016_7_a_past_history_list_item_is_not_a_current_condition(
    note: str, code: str, quote: str
) -> None:
    item = NoteFinding(kind=FindingKind.CONDITION, code=code, quote=quote)
    assert note_findings.verify([item], context(ed_note=note)) == ()


@pytest.mark.parametrize(
    ("note", "code", "quote"),
    [
        ("Background: COPD, heart failure.", "HEART_FAILURE", "heart failure"),
        ("Background: asthma, 28 weeks pregnant.", "PREGNANCY", "28 weeks pregnant"),
    ],
)
def test_ac_016_7_a_chronic_condition_in_a_history_list_still_counts(
    note: str, code: str, quote: str
) -> None:
    item = NoteFinding(kind=FindingKind.CONDITION, code=code, quote=quote)
    assert note_findings.verify([item], context(ed_note=note)) == (item,)


def test_ac_016_7_the_label_does_not_reach_the_next_sentence() -> None:
    item = NoteFinding(kind=FindingKind.CONDITION, code="ACTIVE_GI_BLEED", quote="melaena")
    note = "PMH: hypertension. Today two episodes of melaena."
    assert note_findings.verify([item], context(ed_note=note)) == (item,)
