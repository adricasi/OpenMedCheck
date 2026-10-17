"""Builds decision cards. T-002: rules-only card; model and combiner arrive in T-004/T-005."""

from __future__ import annotations

import uuid

from openmedcheck import rules_engine
from openmedcheck.contracts import (
    CheckRequest,
    ConflictType,
    DecisionCard,
    RulesVerdict,
    Source,
    Status,
)

NO_ISSUE_HEADLINE = "No issue found by these checks"
NO_ISSUE_RATIONALE = "No rule in the current table conflicts with this order and context."
BLOCKED_HEADLINE = "Order conflicts with patient context"
WARNING_HEADLINE = "Review this order before signing"
ALLERGY_HEADLINE = "Order conflicts with recorded allergy"


def _headline(verdict: RulesVerdict) -> str:
    if any(rule.conflict_type is ConflictType.ALLERGY for rule in verdict.fired_rules):
        return ALLERGY_HEADLINE
    return BLOCKED_HEADLINE if verdict.status is Status.BLOCKED else WARNING_HEADLINE


def rules_card(request: CheckRequest) -> DecisionCard:
    """Run Layer 1 only and return the card (``source=rules``)."""
    verdict = rules_engine.evaluate(request.context, request.order)
    if verdict.status is Status.NO_ISSUE:
        headline, rationale = NO_ISSUE_HEADLINE, NO_ISSUE_RATIONALE
    else:
        headline = _headline(verdict)
        rationale = " ".join(rule.reason for rule in verdict.fired_rules)
    return DecisionCard(
        status=verdict.status,
        risk_level=verdict.risk_level,
        headline=headline,
        rationale=rationale,
        fired_rules=verdict.fired_rules,
        renal_adjustment_required=verdict.renal_adjustment_required,
        crcl_ml_min=verdict.crcl_ml_min,
        alternative=None,
        source=Source.RULES,
        model_note=None,
        request_id=uuid.uuid4().hex,
    )
