"""Layer 1: deterministic rules. Pure: no I/O, no logging of patient context (REQ-002).

Applies every rule of the rule table to one context and order and returns the rules verdict.
It never calls the model (AC-002.1).
"""

from __future__ import annotations

from openmedcheck import rule_table
from openmedcheck.contracts import (
    ConflictType,
    FiredRule,
    Order,
    PatientContext,
    RiskLevel,
    RulesVerdict,
    Status,
)
from openmedcheck.renal import cockcroft_gault
from openmedcheck.rule_table import (
    LabComparison,
    LabRule,
    RenalBasis,
    RenalRule,
    RenalUnknownRule,
    RuleEntry,
)

_STATUS_RANK = {Status.NO_ISSUE: 0, Status.WARNING: 1, Status.BLOCKED: 2}
_RISK_RANK = {RiskLevel.LOW: 0, RiskLevel.MODERATE: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


def _allergy_matches(context: PatientContext, order: Order) -> bool:
    drug = rule_table.DRUGS_BY_ID[order.drug_id]
    allergies = {allergy.casefold() for allergy in context.allergies}
    return bool(
        {drug.drug_id.casefold(), drug.active_ingredient.casefold(), drug.drug_class.casefold()}
        & allergies
    )


def _context_rules(context: PatientContext, order: Order) -> list[rule_table.ContextRule]:
    drug_class = rule_table.DRUGS_BY_ID[order.drug_id].drug_class
    chronic_classes = {rule_table.DRUGS_BY_ID[d].drug_class for d in context.chronic_medications}
    return [
        rule
        for rule in rule_table.CONTEXT_RULES
        if rule.applies_to_class == drug_class
        and (rule.diagnosis is None or rule.diagnosis in context.diagnoses)
        and (rule.chronic_class is None or rule.chronic_class in chronic_classes)
    ]


def _beyond(rule: LabRule, value: float) -> bool:
    if rule.comparison is LabComparison.ABOVE:
        return value > rule.threshold
    return value < rule.threshold


def _lab_rules(context: PatientContext, order: Order) -> list[RuleEntry]:
    """Strictest firing lab rule per lab, or the unknown-lab rule (AC-002.10, AC-002.12)."""
    drug_class = rule_table.DRUGS_BY_ID[order.drug_id].drug_class
    fired: dict[str, list[LabRule]] = {}
    for rule in rule_table.LAB_RULES:
        value = getattr(context.labs, rule.lab)
        if drug_class in rule.applies_to_classes and value is not None and _beyond(rule, value):
            fired.setdefault(rule.lab, []).append(rule)
    entries: list[RuleEntry] = [
        max(rules, key=lambda r: (_STATUS_RANK[r.status], _RISK_RANK[r.risk_level]))
        for rules in fired.values()
    ]
    entries += [
        rule
        for rule in rule_table.LAB_UNKNOWN_RULES
        if drug_class in rule.applies_to_classes and getattr(context.labs, rule.lab) is None
    ]
    return entries


def _renal_measure(basis: RenalBasis, context: PatientContext, crcl: float | None) -> float | None:
    return context.labs.egfr_ml_min_1_73m2 if basis is RenalBasis.EGFR else crcl


def _strictest(rules: list[RenalRule]) -> RenalRule:
    return max(rules, key=lambda rule: (_STATUS_RANK[rule.status], _RISK_RANK[rule.risk_level]))


def _renal_reason(rule: RenalRule) -> str:
    # A contraindication has no dose to adjust, so the guidance only goes with warnings.
    if rule.status is Status.BLOCKED:
        return rule.reason
    return f"{rule.reason} {rule_table.shown_dose_guidance(rule)}."


def evaluate(context: PatientContext, order: Order) -> RulesVerdict:
    """Apply all rules to ``context`` and ``order`` and return the rules verdict."""
    fired: list[tuple[RuleEntry, str]] = []
    if _allergy_matches(context, order):
        fired.append((rule_table.ALLERGY_RULE, rule_table.ALLERGY_RULE.reason))
    fired.extend((rule, rule.reason) for rule in _context_rules(context, order))
    fired.extend((rule, rule.reason) for rule in _lab_rules(context, order))

    renal_rules = [rule for rule in rule_table.RENAL_RULES if rule.drug_id == order.drug_id]
    crcl: float | None = None
    creatinine = context.labs.creatinine_mg_dl
    if creatinine is not None and any(rule.basis is RenalBasis.CRCL for rule in renal_rules):
        crcl = cockcroft_gault(context.age, context.weight_kg, context.sex, creatinine)

    unknown: dict[RenalBasis, RenalUnknownRule] = {}
    below: dict[RenalBasis, list[RenalRule]] = {}
    for rule in renal_rules:
        measure = _renal_measure(rule.basis, context, crcl)
        if measure is None:
            unknown[rule.basis] = rule_table.RENAL_UNKNOWN_RULES[rule.basis]
        elif measure < rule.threshold:
            below.setdefault(rule.basis, []).append(rule)
    # Overlapping thresholds on one lab (e.g. metformin eGFR 30 and 45): show the strictest only.
    fired.extend((rule, _renal_reason(rule)) for rule in map(_strictest, below.values()))
    fired.extend((rule, rule.reason) for rule in unknown.values())
    displayed_crcl = None if crcl is None else round(crcl, 1)

    if not fired:
        return RulesVerdict(
            status=Status.NO_ISSUE,
            risk_level=RiskLevel.LOW,
            fired_rules=[],
            crcl_ml_min=displayed_crcl,
        )
    return RulesVerdict(
        status=max((entry.status for entry, _ in fired), key=_STATUS_RANK.__getitem__),
        risk_level=max((entry.risk_level for entry, _ in fired), key=_RISK_RANK.__getitem__),
        fired_rules=[
            FiredRule(rule_id=entry.rule_id, reason=reason, conflict_type=entry.conflict_type)
            for entry, reason in fired
        ],
        renal_adjustment_required=any(
            entry.conflict_type is ConflictType.RENAL for entry, _ in fired
        ),
        crcl_ml_min=displayed_crcl,
    )
