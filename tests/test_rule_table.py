from __future__ import annotations

import re
from dataclasses import replace
from datetime import date

from openmedcheck import rule_table
from openmedcheck.contracts import ConflictType, Labs
from openmedcheck.rule_table import (
    ALLERGY_RULE,
    ALLOWED_ALTERNATIVES,
    CLASS_IDS,
    CONTEXT_RULES,
    DOSE_FALLBACK_TEXT,
    DRUG_IDS,
    DRUGS,
    LAB_RULES,
    LAB_UNKNOWN_RULES,
    RENAL_FALLBACK_GUIDANCE,
    RENAL_RULES,
    RENAL_UNKNOWN_RULES,
    is_reviewed,
    shown_alternative_dose,
    shown_dose_guidance,
)

_BANNED = re.compile(r"\b(approved?|safe|safely)\b", re.IGNORECASE)
_DOSE_PATTERN = re.compile(r"\d\s*(mg|g|mcg|µg|iu|ui|ml/h)\b", re.IGNORECASE)
_SIGNED = {"reviewed_by": "Dr Example", "reviewed_on": date(2026, 10, 17)}


def _all_entries() -> list[rule_table.RuleEntry]:
    return [ALLERGY_RULE, *CONTEXT_RULES, *RENAL_RULES, *RENAL_UNKNOWN_RULES.values()]


def test_ac_002_8_every_entry_has_a_source_citation() -> None:
    for entry in _all_entries():
        assert entry.source.strip(), entry.rule_id
    for alternatives in ALLOWED_ALTERNATIVES.values():
        for alternative in alternatives:
            assert alternative.source.strip(), alternative.drug_id


def test_ac_002_8_entries_are_complete_and_unique() -> None:
    ids = [entry.rule_id for entry in _all_entries()]
    assert len(ids) == len(set(ids))
    for entry in _all_entries():
        assert entry.reason.strip()
        assert isinstance(entry.conflict_type, ConflictType)


def test_nfr_011_nothing_is_marked_reviewed_before_the_specialist_review() -> None:
    for entry in _all_entries():
        assert not is_reviewed(entry), entry.rule_id
    for alternatives in ALLOWED_ALTERNATIVES.values():
        assert not any(is_reviewed(a) for a in alternatives)


def test_nfr_011_review_mark_needs_both_fields() -> None:
    base = ALLOWED_ALTERNATIVES[("naproxen", ConflictType.GI_BLEED)][0]
    assert not is_reviewed(replace(base, reviewed_by="Dr Example"))
    assert not is_reviewed(replace(base, reviewed_on=date(2026, 10, 17)))
    assert is_reviewed(replace(base, **_SIGNED))


def test_nfr_011_reasons_have_no_doses_or_banned_words() -> None:
    for entry in _all_entries():
        assert not _BANNED.search(entry.reason), entry.rule_id
        assert not _DOSE_PATTERN.search(entry.reason), entry.rule_id
        assert len(entry.reason) <= 120, entry.rule_id


def test_nfr_011_unreviewed_dose_guidance_is_hidden() -> None:
    ciprofloxacin = next(r for r in RENAL_RULES if r.drug_id == "ciprofloxacin")
    assert ciprofloxacin.dose_guidance is not None
    assert shown_dose_guidance(ciprofloxacin) == RENAL_FALLBACK_GUIDANCE


def test_nfr_011_reviewed_dose_guidance_is_shown() -> None:
    base = next(r for r in RENAL_RULES if r.drug_id == "ciprofloxacin")
    assert shown_dose_guidance(replace(base, **_SIGNED)) == base.dose_guidance


def test_nfr_011_reviewed_rule_without_numeric_guidance_uses_fallback() -> None:
    base = next(r for r in RENAL_RULES if r.drug_id == "levofloxacin")
    assert shown_dose_guidance(replace(base, **_SIGNED)) == RENAL_FALLBACK_GUIDANCE


def test_nfr_011_alternative_dose_hidden_until_reviewed() -> None:
    base = ALLOWED_ALTERNATIVES[("naproxen", ConflictType.GI_BLEED)][0]
    assert shown_alternative_dose(base) == DOSE_FALLBACK_TEXT
    assert shown_alternative_dose(replace(base, **_SIGNED)) == "1 g, PO, every 8 hours"


def test_drug_list_has_twenty_known_drugs() -> None:
    assert len(DRUGS) == 20
    assert len(set(DRUG_IDS)) == 20
    assert {"NSAID", "ANTICOAGULANT", "ACE_INHIBITOR", "POTASSIUM_SPARING"} <= set(CLASS_IDS)


def test_rules_reference_known_drugs_and_classes() -> None:
    for rule in RENAL_RULES:
        assert rule.drug_id in DRUG_IDS
        assert rule.threshold > 0
    for rule in CONTEXT_RULES:
        assert rule.applies_to_class in CLASS_IDS
        assert rule.chronic_class is None or rule.chronic_class in CLASS_IDS
    assert set(RENAL_UNKNOWN_RULES) == {r.basis for r in RENAL_RULES}
    for lab in (*LAB_RULES, *LAB_UNKNOWN_RULES):
        assert lab.lab in Labs.model_fields
        assert set(lab.applies_to_classes) <= set(CLASS_IDS)


def test_allowed_alternatives_are_on_the_drug_list_and_outside_the_class() -> None:
    classes = {drug.drug_id: drug.drug_class for drug in DRUGS}
    for (proposed, conflict), alternatives in ALLOWED_ALTERNATIVES.items():
        assert proposed in DRUG_IDS
        assert alternatives
        for alternative in alternatives:
            assert alternative.proposed_drug_id == proposed
            assert alternative.conflict_type is conflict
            assert alternative.drug_id in DRUG_IDS
            assert classes[alternative.drug_id] != classes[proposed]


def test_ac_006_1_paracetamol_is_the_alternative_for_nsaid_with_acs() -> None:
    options = ALLOWED_ALTERNATIVES[("dexketoprofen", ConflictType.ANTIPLATELET_ACS)]
    assert [a.drug_id for a in options] == ["paracetamol"]
