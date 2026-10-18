from __future__ import annotations

from openmedcheck.check_service import rules_card
from openmedcheck.contracts import Status
from openmedcheck.presets import PRESETS, SYNTHETIC_LABEL


def test_ac_006_4_every_preset_is_labelled_synthetic() -> None:
    assert set(PRESETS) == {"A", "B", "C"}
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
