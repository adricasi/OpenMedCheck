"""Builds decision cards: the rules-only card and the combined card (REQ-001, REQ-004).

The model call, retry, deadline and logging are added in T-005; ``combined_card`` takes the
validated ``ModelVerdict`` (or None when the model is unavailable).
"""

from __future__ import annotations

import uuid

from openmedcheck import rules_engine
from openmedcheck.alternatives import select_alternative
from openmedcheck.combiner import combine
from openmedcheck.contracts import (
    CheckRequest,
    ConflictType,
    DecisionCard,
    ModelVerdict,
    RulesVerdict,
    Status,
)

BLOCKED_HEADLINE = "Order conflicts with patient context"
WARNING_HEADLINE = "Review this order before signing"
ALLERGY_HEADLINE = "Order conflicts with recorded allergy"


def _headline(verdict: RulesVerdict) -> str:
    if any(rule.conflict_type is ConflictType.ALLERGY for rule in verdict.fired_rules):
        return ALLERGY_HEADLINE
    return BLOCKED_HEADLINE if verdict.status is Status.BLOCKED else WARNING_HEADLINE


def _rules_text(verdict: RulesVerdict) -> tuple[str, str]:
    """Headline and rationale of the rules-only card (empty for NO_ISSUE: the combiner's fixed
    text is used)."""
    if verdict.status is Status.NO_ISSUE:
        return "", ""
    return _headline(verdict), " ".join(rule.reason for rule in verdict.fired_rules)


def combined_card(
    request: CheckRequest, model: ModelVerdict | None, request_id: str | None = None
) -> tuple[DecisionCard, bool]:
    """Rules, then the escalate-only combiner, then the alternative re-check.

    Returns the card and whether a less strict model verdict was rejected (AC-004.2: the caller
    logs it). With ``model=None`` the card is the rules-only card (``source=rules``), which
    still carries a rule-table alternative when AC-001.3 allows one.
    """
    verdict = rules_engine.evaluate(request.context, request.order)
    headline, rationale = _rules_text(verdict)
    combined = combine(verdict, headline, rationale, model)
    alternative = select_alternative(
        request.context,
        request.order,
        status=combined.status,
        conflict_type=combined.conflict_type,
        model_raised=combined.model_raised,
        model_alternative_id=None if model is None else model.alternative_drug_id,
    )
    card = DecisionCard(
        status=combined.status,
        risk_level=combined.risk_level,
        headline=combined.headline,
        rationale=combined.rationale,
        fired_rules=combined.fired_rules,
        renal_adjustment_required=combined.renal_adjustment_required,
        crcl_ml_min=combined.crcl_ml_min,
        alternative=alternative,
        source=combined.source,
        model_note=None,
        request_id=uuid.uuid4().hex if request_id is None else request_id,
    )
    return card, combined.downgrade_rejected


def rules_card(request: CheckRequest) -> DecisionCard:
    """Run Layer 1 only and return the card (``source=rules``)."""
    return combined_card(request, None)[0]
