"""Combiner tests (REQ-004, AC-001.2, AC-004.9, NFR-009)."""

from __future__ import annotations

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from openmedcheck.combiner import (
    MAX_HEADLINE_CHARS,
    MAX_RATIONALE_CHARS,
    NO_ISSUE_HEADLINE,
    NO_ISSUE_RATIONALE,
    RENAL_FLAG_HEADLINE,
    CombinedVerdict,
    combine,
    limit_headline,
    limit_rationale,
)
from openmedcheck.contracts import (
    ConflictType,
    FiredRule,
    ModelVerdict,
    RiskLevel,
    RulesVerdict,
    Source,
    Status,
)
from openmedcheck.rule_table import RULES_BY_ID

RULES_HEADLINE = "Order conflicts with patient context"
RULES_RATIONALE = "NSAID with an antiplatelet agent and a coded diagnosis of ACS."


def fired(rule_id: str) -> FiredRule:
    return FiredRule(
        rule_id=rule_id,
        reason=RULES_BY_ID[rule_id].reason,
        conflict_type=RULES_BY_ID[rule_id].conflict_type,
    )


def rules_verdict(*rule_ids: str, flag: bool = False) -> RulesVerdict:
    entries = [RULES_BY_ID[rule_id] for rule_id in rule_ids]
    if not entries:
        return RulesVerdict(status=Status.NO_ISSUE, risk_level=RiskLevel.LOW, fired_rules=[])
    return RulesVerdict(
        status=max((e.status for e in entries), key=lambda s: s.rank),
        risk_level=max((e.risk_level for e in entries), key=lambda r: r.rank),
        fired_rules=[fired(rule_id) for rule_id in rule_ids],
        renal_adjustment_required=flag,
    )


def model_verdict(
    status: Status = Status.NO_ISSUE,
    risk_level: RiskLevel = RiskLevel.LOW,
    *,
    headline: str = "Model headline",
    rationale: str = "Model rationale.",
    flag: bool = False,
    conflict_type: ConflictType | None = None,
    alternative_drug_id: str | None = None,
) -> ModelVerdict:
    return ModelVerdict(
        status=status,
        risk_level=risk_level,
        headline=headline,
        rationale=rationale,
        renal_adjustment_required=flag,
        conflict_type=conflict_type,
        alternative_drug_id=alternative_drug_id,
    )


NO_RULES = rules_verdict()
ACS_BLOCKED = rules_verdict("NSAID_ANTIPLATELET_ACS")
RENAL_WARNING = rules_verdict("RENAL_CIPROFLOXACIN_CRCL_30", flag=True)


def run(rules: RulesVerdict, model: ModelVerdict | None) -> CombinedVerdict:
    return combine(rules, RULES_HEADLINE, RULES_RATIONALE, model)


@pytest.mark.parametrize(
    ("rules_status", "rules_tier", "model_status", "model_tier"),
    list(itertools.product(Status, RiskLevel, Status, RiskLevel)),
)
def test_ac_004_1_final_is_the_stricter_status_and_higher_tier(
    rules_status: Status, rules_tier: RiskLevel, model_status: Status, model_tier: RiskLevel
) -> None:
    rules = RulesVerdict(status=rules_status, risk_level=rules_tier, fired_rules=[])
    result = run(rules, model_verdict(model_status, model_tier))
    assert result.status.rank >= max(rules_status.rank, model_status.rank)
    assert result.risk_level.rank == max(rules_tier.rank, model_tier.rank)


def test_ac_004_2_less_strict_model_keeps_rules_status_tier_and_text() -> None:
    model = model_verdict(Status.NO_ISSUE, RiskLevel.LOW, headline="All fine", rationale="Fine.")
    result = run(ACS_BLOCKED, model)
    assert result.downgrade_rejected
    assert (result.status, result.risk_level) == (Status.BLOCKED, RiskLevel.CRITICAL)
    assert (result.headline, result.rationale) == (RULES_HEADLINE, RULES_RATIONALE)
    assert result.source is Source.RULES_MODEL


def test_ac_004_2_same_status_lower_tier_is_a_rejected_downgrade() -> None:
    rules = rules_verdict("RENAL_CIPROFLOXACIN_CRCL_30", flag=True)
    result = run(rules, model_verdict(Status.WARNING, RiskLevel.LOW, flag=True))
    assert result.downgrade_rejected
    assert result.headline == RULES_HEADLINE
    assert result.risk_level is RiskLevel.MODERATE


def test_model_at_least_as_strict_supplies_the_text() -> None:
    model = model_verdict(Status.BLOCKED, RiskLevel.CRITICAL, headline="Model says no")
    result = run(NO_RULES, model)
    assert not result.downgrade_rejected
    assert result.headline == "Model says no"
    assert result.rationale == "Model rationale."
    assert result.model_raised
    assert result.source is Source.RULES_MODEL


def test_equal_verdicts_use_the_model_text_without_a_downgrade() -> None:
    model = model_verdict(Status.BLOCKED, RiskLevel.CRITICAL, headline="Model says no")
    result = run(ACS_BLOCKED, model)
    assert not result.downgrade_rejected
    assert result.headline == "Model says no"
    assert not result.model_raised


def test_ac_004_3_rules_blocked_stays_blocked_for_every_model_verdict() -> None:
    for status, tier, flag in itertools.product(Status, RiskLevel, (False, True)):
        assert run(ACS_BLOCKED, model_verdict(status, tier, flag=flag)).status is Status.BLOCKED


def test_ac_004_4_model_can_set_but_not_clear_the_renal_flag() -> None:
    assert run(RENAL_WARNING, model_verdict(flag=False)).renal_adjustment_required
    assert run(NO_RULES, model_verdict(Status.WARNING, flag=True)).renal_adjustment_required
    assert not run(NO_RULES, model_verdict(flag=False)).renal_adjustment_required


def test_ac_004_4_renal_flag_alone_lifts_a_clean_verdict_to_warning() -> None:
    result = run(NO_RULES, model_verdict(Status.NO_ISSUE, RiskLevel.LOW, flag=True))
    assert result.status is Status.WARNING
    assert result.headline == RENAL_FLAG_HEADLINE
    assert result.conflict_type is ConflictType.RENAL
    assert result.model_raised


def test_ac_004_4_flag_without_model_still_forces_warning() -> None:
    flagged = RulesVerdict(
        status=Status.NO_ISSUE,
        risk_level=RiskLevel.LOW,
        fired_rules=[],
        renal_adjustment_required=True,
    )
    result = run(flagged, None)
    assert result.status is Status.WARNING
    assert result.headline == RENAL_FLAG_HEADLINE


def test_ac_004_5_fired_rules_are_always_carried_over() -> None:
    model = model_verdict(Status.BLOCKED, RiskLevel.CRITICAL, rationale="Omits every rule.")
    result = run(ACS_BLOCKED, model)
    assert result.fired_rules == ACS_BLOCKED.fired_rules
    assert result.fired_rules is not ACS_BLOCKED.fired_rules


def test_ac_004_9_no_issue_uses_the_fixed_text_and_no_model_text() -> None:
    model = model_verdict(Status.NO_ISSUE, headline="Looks great", rationale="Totally safe.")
    result = run(NO_RULES, model)
    assert result.status is Status.NO_ISSUE
    assert (result.headline, result.rationale) == (NO_ISSUE_HEADLINE, NO_ISSUE_RATIONALE)
    assert result.conflict_type is None
    assert not result.model_raised


def test_without_a_model_the_verdict_is_the_rules_verdict() -> None:
    result = run(ACS_BLOCKED, None)
    assert result.source is Source.RULES
    assert not result.downgrade_rejected
    assert (result.status, result.headline) == (Status.BLOCKED, RULES_HEADLINE)
    assert result.conflict_type is ConflictType.ANTIPLATELET_ACS


def test_deciding_conflict_is_the_strongest_fired_rule_when_rules_set_the_status() -> None:
    rules = rules_verdict("RENAL_UNKNOWN_CRCL", "NSAID_ACTIVE_GI_BLEED", "RENAL_UNKNOWN_EGFR")
    result = run(rules, model_verdict(Status.WARNING, conflict_type=ConflictType.OTHER))
    assert result.conflict_type is ConflictType.GI_BLEED


def test_deciding_conflict_is_the_models_when_the_model_raised_the_status() -> None:
    model = model_verdict(Status.BLOCKED, conflict_type=ConflictType.ANTIPLATELET_ACS)
    assert run(RENAL_WARNING, model).conflict_type is ConflictType.ANTIPLATELET_ACS


def test_deciding_conflict_is_unknown_when_the_model_gives_none() -> None:
    assert run(NO_RULES, model_verdict(Status.BLOCKED)).conflict_type is None


def test_ac_001_2_model_text_is_cut_to_the_limits() -> None:
    model = model_verdict(
        Status.BLOCKED,
        headline="one two three four five six seven eight nine ten",
        rationale="First sentence. Second one! Third? " + "x" * 400,
    )
    result = run(NO_RULES, model)
    assert result.headline == "one two three four five six seven eight"
    assert result.rationale == "First sentence. Second one!"


def test_empty_model_text_falls_back_to_the_rules_text() -> None:
    model = model_verdict(Status.BLOCKED, headline="  ", rationale="")
    result = run(ACS_BLOCKED, model)
    assert (result.headline, result.rationale) == (RULES_HEADLINE, RULES_RATIONALE)


def test_ac_001_2_long_multi_rule_rules_text_is_cut_but_reasons_stay_in_fired_rules() -> None:
    rule_ids = ("NSAID_ANTIPLATELET_ACS", "NSAID_ACTIVE_GI_BLEED", "ALLERGY_EXACT_MATCH")
    rules = rules_verdict(*rule_ids)
    rationale = " ".join(r.reason for r in rules.fired_rules) + " " + "y" * 300
    result = combine(rules, RULES_HEADLINE, rationale, None)
    assert len(result.rationale) <= MAX_RATIONALE_CHARS
    assert result.rationale.count(".") <= 2
    assert [r.reason for r in result.fired_rules] == [r.reason for r in rules.fired_rules]


def test_limit_headline_cuts_words_and_characters() -> None:
    assert limit_headline("short headline") == "short headline"
    assert limit_headline("  spaced \n out  ") == "spaced out"
    assert limit_headline("a b c d e f g h i j") == "a b c d e f g h"
    long_words = limit_headline("abcdefghij " * 8)
    assert len(long_words) <= MAX_HEADLINE_CHARS
    assert long_words.endswith("…")
    assert len(limit_headline("x" * 200)) == MAX_HEADLINE_CHARS


def test_limit_rationale_cuts_sentences_and_characters() -> None:
    assert limit_rationale("One. Two. Three.") == "One. Two."
    assert limit_rationale("No period at all") == "No period at all"
    assert len(limit_rationale("word " * 200)) <= MAX_RATIONALE_CHARS


# --- Property tests over the full ModelVerdict (AC-004.8) ----------------------------------

_rule_ids = st.lists(st.sampled_from(sorted(RULES_BY_ID)), max_size=4, unique=True)


@st.composite
def rules_verdicts(draw: st.DrawFn) -> RulesVerdict:
    rule_ids = draw(_rule_ids)
    flag = draw(st.booleans()) or any(
        RULES_BY_ID[r].conflict_type is ConflictType.RENAL for r in rule_ids
    )
    return rules_verdict(*rule_ids, flag=flag)


model_verdicts = st.builds(
    ModelVerdict,
    status=st.sampled_from(Status),
    risk_level=st.sampled_from(RiskLevel),
    headline=st.text(),
    rationale=st.text(),
    renal_adjustment_required=st.booleans(),
    conflict_type=st.none() | st.sampled_from(ConflictType),
    alternative_drug_id=st.none() | st.text(),
)


@given(rules=rules_verdicts(), model=st.none() | model_verdicts)
def test_property_combined_is_never_below_rules_and_never_clears_flags(
    rules: RulesVerdict, model: ModelVerdict | None
) -> None:
    result = run(rules, model)
    assert result.status.rank >= rules.status.rank
    assert result.risk_level.rank >= rules.risk_level.rank
    if rules.status is Status.BLOCKED:
        assert result.status is Status.BLOCKED
    if rules.renal_adjustment_required:
        assert result.renal_adjustment_required
    if result.renal_adjustment_required:
        assert result.status.rank >= Status.WARNING.rank
    if model is not None:
        assert result.status.rank >= model.status.rank
        assert result.renal_adjustment_required >= model.renal_adjustment_required
    assert result.fired_rules == rules.fired_rules
    assert len(result.headline.split()) <= 8
    assert len(result.headline) <= MAX_HEADLINE_CHARS
    assert result.headline
    assert len(result.rationale) <= MAX_RATIONALE_CHARS
    if result.status is Status.NO_ISSUE:
        assert (result.headline, result.rationale) == (NO_ISSUE_HEADLINE, NO_ISSUE_RATIONALE)


@given(text=st.text())
def test_property_limits_always_hold(text: str) -> None:
    assert len(limit_headline(text).split()) <= 8
    assert len(limit_headline(text)) <= MAX_HEADLINE_CHARS
    assert len(limit_rationale(text)) <= MAX_RATIONALE_CHARS
