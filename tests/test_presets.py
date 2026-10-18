from __future__ import annotations

from openmedcheck.check_service import rules_card
from openmedcheck.contracts import Status
from openmedcheck.presets import PRESETS, SYNTHETIC_LABEL


def test_ac_006_4_every_preset_is_labelled_synthetic() -> None:
    assert set(PRESETS) == set("ABCDEFGHI")
    for preset in PRESETS.values():
        assert preset.synthetic_label == SYNTHETIC_LABEL
        assert preset.request.context.patient_id.startswith("SYN-")


def test_ac_003_4_preset_a_has_suspected_acs_only_in_the_note() -> None:
    context = PRESETS["A"].request.context

    assert context.diagnoses == []
    assert "Suspected ACS" in context.ed_note
    assert context.chronic_medications == ["aspirin"]
    assert PRESETS["A"].request.order.drug_id == "dexketoprofen"


def test_ac_006_2_preset_b_rules_card_is_warning_with_renal_flag_and_no_number() -> None:
    card = rules_card(PRESETS["B"].request)

    assert card.status is Status.WARNING
    assert card.renal_adjustment_required is True
    assert card.crcl_ml_min == 18.9
    assert "consult SmPC" in card.rationale
    assert "500 mg" not in card.rationale


def test_ac_006_3_preset_c_rules_card_is_no_issue_without_alternative() -> None:
    card = rules_card(PRESETS["C"].request)

    assert card.status is Status.NO_ISSUE
    assert card.alternative is None


def test_expected_rules_status_matches_the_engine() -> None:
    for preset in PRESETS.values():
        assert rules_card(preset.request).status is preset.expected_rules_status


def test_ac_006_6_template_d_coded_gi_bleed_blocks_ibuprofen_with_paracetamol() -> None:
    card = rules_card(PRESETS["D"].request)

    assert card.status is Status.BLOCKED
    assert [rule.rule_id for rule in card.fired_rules] == ["NSAID_ACTIVE_GI_BLEED"]
    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"


def test_ac_006_6_template_e_penicillin_allergy_blocks_amoxicillin_clavulanate() -> None:
    card = rules_card(PRESETS["E"].request)

    assert card.status is Status.BLOCKED
    assert [rule.rule_id for rule in card.fired_rules] == ["ALLERGY_EXACT_MATCH"]
    assert card.alternative is None


def test_ac_006_6_template_f_low_crcl_blocks_dexketoprofen_with_renal_flag() -> None:
    card = rules_card(PRESETS["F"].request)

    assert card.status is Status.BLOCKED
    assert [rule.rule_id for rule in card.fired_rules] == ["RENAL_DEXKETOPROFEN_CRCL_60"]
    assert card.renal_adjustment_required
    assert card.crcl_ml_min is not None
    assert card.crcl_ml_min < 60
    assert card.alternative is not None
    assert card.alternative.drug_id == "paracetamol"


def test_ac_006_5_only_presets_a_b_c_are_predefined_rooms() -> None:
    rooms = {pid for pid, preset in PRESETS.items() if preset.bed is not None}

    assert rooms == {"A", "B", "C"}


def test_ac_006_6_breadth_templates_fire_the_new_rules() -> None:
    assert [r.rule_id for r in rules_card(PRESETS["G"].request).fired_rules] == [
        "NSAID_ORAL_ANTICOAGULANT"
    ]
    assert [r.rule_id for r in rules_card(PRESETS["H"].request).fired_rules] == [
        "POTASSIUM_RAAS_ABOVE_5_5"
    ]
    # I: the pregnancy is only in the note, so the rules alone stay silent (the model decides).
    assert rules_card(PRESETS["I"].request).status is Status.NO_ISSUE
    assert "PREGNANCY" not in PRESETS["I"].request.context.diagnoses
