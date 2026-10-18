from __future__ import annotations

from typing import Any

from openmedcheck.contracts import (
    ConflictType,
    Labs,
    Order,
    PatientContext,
    RiskLevel,
    Status,
)
from openmedcheck.presets import PRESET_A, PRESET_B, PRESET_C
from openmedcheck.rules_engine import evaluate


def _context(**overrides: Any) -> PatientContext:
    values: dict[str, Any] = {
        "patient_id": "SYN-1",
        "age": 50,
        "sex": "F",
        "weight_kg": 70,
        "allergies": [],
        "labs": Labs(creatinine_mg_dl=0.8, egfr_ml_min_1_73m2=100),
    }
    values.update(overrides)
    return PatientContext(**values)


def _order(drug_id: str) -> Order:
    return Order(drug_id=drug_id, dose_text="1 g", route="PO", frequency="every 8 hours")


def _ids(verdict: Any) -> list[str]:
    return [rule.rule_id for rule in verdict.fired_rules]


def test_ac_001_1_exact_allergy_match_is_blocked() -> None:
    verdict = evaluate(_context(allergies=["Naproxen"]), _order("naproxen"))

    assert verdict.status is Status.BLOCKED
    assert verdict.risk_level is RiskLevel.CRITICAL
    assert _ids(verdict) == ["ALLERGY_EXACT_MATCH"]


def test_ac_001_1_no_match_is_no_issue_low() -> None:
    verdict = evaluate(_context(allergies=["ibuprofen"]), _order("paracetamol"))

    assert verdict.status is Status.NO_ISSUE
    assert verdict.risk_level is RiskLevel.LOW
    assert verdict.fired_rules == []


def test_ac_002_5_class_allergy_matches_every_drug_of_the_class() -> None:
    verdict = evaluate(_context(allergies=["nsaid"]), _order("ibuprofen"))

    assert verdict.status is Status.BLOCKED
    assert verdict.fired_rules[0].conflict_type is ConflictType.ALLERGY


def test_ac_002_5_other_class_does_not_match() -> None:
    verdict = evaluate(_context(allergies=["OPIOID"]), _order("ibuprofen"))

    assert verdict.status is Status.NO_ISSUE


def test_ac_002_6_no_rule_fires_gives_no_issue_low() -> None:
    verdict = evaluate(_context(), _order("paracetamol"))

    assert (verdict.status, verdict.risk_level) == (Status.NO_ISSUE, RiskLevel.LOW)
    assert verdict.renal_adjustment_required is False


def test_ac_002_3_nsaid_antiplatelet_and_coded_acs_is_blocked() -> None:
    context = _context(chronic_medications=["aspirin"], diagnoses=["ACS"])

    verdict = evaluate(context, _order("ibuprofen"))

    assert verdict.status is Status.BLOCKED
    assert verdict.risk_level is RiskLevel.CRITICAL
    assert _ids(verdict) == ["NSAID_ANTIPLATELET_ACS"]
    assert verdict.fired_rules[0].conflict_type is ConflictType.ANTIPLATELET_ACS


def test_ac_002_3_clopidogrel_counts_as_antiplatelet() -> None:
    context = _context(chronic_medications=["clopidogrel"], diagnoses=["ACS"])

    assert evaluate(context, _order("naproxen")).status is Status.BLOCKED


def test_ac_002_3_acs_without_antiplatelet_does_not_fire() -> None:
    context = _context(chronic_medications=["metformin"], diagnoses=["ACS"])

    assert evaluate(context, _order("ibuprofen")).status is Status.NO_ISSUE


def test_ac_002_3_antiplatelet_without_coded_acs_does_not_fire() -> None:
    context = _context(chronic_medications=["aspirin"])

    assert evaluate(context, _order("ibuprofen")).status is Status.NO_ISSUE


def test_ac_002_3_non_nsaid_with_acs_and_antiplatelet_does_not_fire() -> None:
    context = _context(chronic_medications=["aspirin"], diagnoses=["ACS"])

    assert evaluate(context, _order("paracetamol")).status is Status.NO_ISSUE


def test_ac_002_4_nsaid_with_active_gi_bleed_is_blocked() -> None:
    verdict = evaluate(_context(diagnoses=["ACTIVE_GI_BLEED"]), _order("diclofenac"))

    assert verdict.status is Status.BLOCKED
    assert _ids(verdict) == ["NSAID_ACTIVE_GI_BLEED"]
    assert verdict.fired_rules[0].conflict_type is ConflictType.GI_BLEED


def test_ac_002_4_non_nsaid_with_active_gi_bleed_does_not_fire() -> None:
    verdict = evaluate(_context(diagnoses=["ACTIVE_GI_BLEED"]), _order("paracetamol"))

    assert verdict.status is Status.NO_ISSUE


def test_ac_002_1_all_matching_rules_fire_and_strictest_wins() -> None:
    context = _context(
        chronic_medications=["aspirin"],
        diagnoses=["ACS", "ACTIVE_GI_BLEED"],
        allergies=["ibuprofen"],
    )

    verdict = evaluate(context, _order("ibuprofen"))

    assert _ids(verdict) == [
        "ALLERGY_EXACT_MATCH",
        "NSAID_ANTIPLATELET_ACS",
        "NSAID_ACTIVE_GI_BLEED",
    ]
    assert verdict.status is Status.BLOCKED
    assert verdict.risk_level is RiskLevel.CRITICAL


def test_ac_002_2_crcl_below_threshold_fires_with_flag_and_computed_value() -> None:
    # age 78, 62 kg, F, creatinine 2.4 -> CrCl 18.9
    context = _context(age=78, weight_kg=62, labs=Labs(creatinine_mg_dl=2.4))

    verdict = evaluate(context, _order("ciprofloxacin"))

    assert verdict.status is Status.WARNING
    assert verdict.risk_level is RiskLevel.MODERATE
    assert verdict.renal_adjustment_required is True
    assert verdict.crcl_ml_min == 18.9
    assert _ids(verdict) == ["RENAL_CIPROFLOXACIN_CRCL_30"]
    assert "consult SmPC" in verdict.fired_rules[0].reason


def test_ac_002_2_crcl_equal_to_threshold_does_not_fire() -> None:
    # male, age 40, 72 kg: CrCl = 100 * 72 / (72 * creatinine) = 100 / creatinine
    # creatinine 3.3333 is not valid input; use weight to land exactly on 30.0:
    # (140 - 40) * w / (72 * 1.0) = 30 -> w = 21.6 (below input range), so use age.
    # (140 - age) * 72 / (72 * 1.0) = 140 - age = 30 -> age 110.
    context = _context(age=110, sex="M", weight_kg=72, labs=Labs(creatinine_mg_dl=1.0))

    verdict = evaluate(context, _order("ciprofloxacin"))

    assert verdict.crcl_ml_min == 30.0
    assert verdict.status is Status.NO_ISSUE
    assert verdict.renal_adjustment_required is False


def test_ac_002_2_crcl_just_below_threshold_fires() -> None:
    context = _context(age=110, sex="M", weight_kg=72, labs=Labs(creatinine_mg_dl=1.1))

    verdict = evaluate(context, _order("ciprofloxacin"))

    assert verdict.crcl_ml_min == 27.3
    assert verdict.status is Status.WARNING


def test_ac_002_2_egfr_rule_uses_egfr_not_crcl() -> None:
    context = _context(labs=Labs(creatinine_mg_dl=0.8, egfr_ml_min_1_73m2=29))

    verdict = evaluate(context, _order("metformin"))

    assert verdict.status is Status.BLOCKED
    assert verdict.risk_level is RiskLevel.HIGH
    assert _ids(verdict) == ["RENAL_METFORMIN_EGFR_30"]
    assert "consult SmPC" not in verdict.fired_rules[0].reason
    assert verdict.crcl_ml_min is None
    assert verdict.renal_adjustment_required is True


def test_ac_002_2_egfr_equal_to_threshold_does_not_fire() -> None:
    context = _context(labs=Labs(egfr_ml_min_1_73m2=45))

    verdict = evaluate(context, _order("metformin"))

    assert verdict.status is Status.NO_ISSUE


def test_ac_002_2_egfr_between_thresholds_is_warning_only() -> None:
    context = _context(labs=Labs(egfr_ml_min_1_73m2=44))

    verdict = evaluate(context, _order("metformin"))

    assert verdict.status is Status.WARNING
    assert _ids(verdict) == ["RENAL_METFORMIN_EGFR_45"]


def test_ac_002_2_renal_block_for_dexketoprofen() -> None:
    # male, age 70, 70 kg, creatinine 1.5 -> CrCl 45.4
    context = _context(age=70, sex="M", weight_kg=70, labs=Labs(creatinine_mg_dl=1.5))

    verdict = evaluate(context, _order("dexketoprofen"))

    assert verdict.status is Status.BLOCKED
    assert verdict.renal_adjustment_required is True
    assert verdict.crcl_ml_min == 45.4


def test_ac_002_7_crcl_is_reported_when_a_crcl_rule_exists_and_not_otherwise() -> None:
    labs = Labs(creatinine_mg_dl=1.0, egfr_ml_min_1_73m2=90)

    assert evaluate(_context(labs=labs), _order("enoxaparin")).crcl_ml_min is not None
    assert evaluate(_context(labs=labs), _order("paracetamol")).crcl_ml_min is None


def test_ac_001_5_missing_creatinine_for_crcl_rule_is_warning_unknown() -> None:
    verdict = evaluate(_context(labs=Labs(egfr_ml_min_1_73m2=90)), _order("levofloxacin"))

    assert verdict.status is Status.WARNING
    assert verdict.renal_adjustment_required is True
    assert verdict.crcl_ml_min is None
    assert _ids(verdict) == ["RENAL_UNKNOWN_CRCL"]
    assert "Renal function unknown" in verdict.fired_rules[0].reason


def test_ac_001_5_missing_egfr_for_egfr_rule_is_warning_unknown_once() -> None:
    verdict = evaluate(_context(labs=Labs(creatinine_mg_dl=0.8)), _order("metformin"))

    assert verdict.status is Status.WARNING
    assert _ids(verdict) == ["RENAL_UNKNOWN_EGFR"]


def test_ac_001_5_missing_lab_does_not_matter_without_a_renal_rule() -> None:
    verdict = evaluate(_context(labs=Labs()), _order("paracetamol"))

    assert verdict.status is Status.NO_ISSUE


def test_ac_001_5_unknown_renal_function_does_not_lower_a_block() -> None:
    context = _context(allergies=["tramadol"], labs=Labs())

    verdict = evaluate(context, _order("tramadol"))

    assert verdict.status is Status.BLOCKED
    assert _ids(verdict) == ["ALLERGY_EXACT_MATCH", "RENAL_UNKNOWN_CRCL"]


def test_ac_006_presets_have_the_expected_rules_verdicts() -> None:
    a = evaluate(PRESET_A.request.context, PRESET_A.request.order)
    b = evaluate(PRESET_B.request.context, PRESET_B.request.order)
    c = evaluate(PRESET_C.request.context, PRESET_C.request.order)

    assert (a.status, a.fired_rules) == (Status.NO_ISSUE, [])
    assert (b.status, b.renal_adjustment_required) == (Status.WARNING, True)
    assert (c.status, c.fired_rules) == (Status.NO_ISSUE, [])


def test_ac_002_2_unrounded_crcl_just_below_threshold_still_fires() -> None:
    # age 110, M, creatinine 1.0: 71.9 kg gives CrCl 29.96, which is displayed as 30.0
    context = _context(age=110, sex="M", weight_kg=71.9, labs=Labs(creatinine_mg_dl=1.0))

    verdict = evaluate(context, _order("ciprofloxacin"))

    assert verdict.crcl_ml_min == 30.0
    assert verdict.status is Status.WARNING
