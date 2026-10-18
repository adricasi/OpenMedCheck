"""Past medical history in the record (REQ-016, T-018, ADR 0009)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from openmedcheck import prompt, rule_table, rules_engine
from openmedcheck.check_service import rules_card
from openmedcheck.contracts import CheckRequest, ConflictType, Order, PatientContext, Status
from openmedcheck.presets import PRESET_C, PRESETS

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
    assert rule.conflict_type in (ConflictType.GI_BLEED, ConflictType.ANTIPLATELET_ACS)
    assert any(rule_id in question for question in rule_table.SPECIALIST_QUESTIONS)
