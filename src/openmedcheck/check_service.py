"""Builds decision cards: rules-only, combined and the full check (REQ-001, REQ-003 to REQ-005).

``final_card`` runs rules, the model client (retry and deadline live there), the escalate-only
combiner and the alternative re-check. Any model failure yields the rules-only card (fail-safe,
REQ-005). It writes one allowlisted log line per check and never logs context or model text.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable

from openmedcheck import prompt, rule_table, rules_engine
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
from openmedcheck.logging_setup import CHECK_EVENT, LOGGER_NAME, log_event
from openmedcheck.model_client import (
    ModelClient,
    ModelOutcome,
    ModelRequest,
    ModelResult,
    content_violation,
)

LOGGER = logging.getLogger(f"{LOGGER_NAME}.check")
MODEL_UNAVAILABLE_NOTE = "Model check unavailable — rules only"

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
    request: CheckRequest,
    model: ModelVerdict | None,
    request_id: str | None = None,
    *,
    verdict: RulesVerdict | None = None,
    model_note: str | None = None,
) -> tuple[DecisionCard, bool]:
    """Rules, then the escalate-only combiner, then the alternative re-check.

    Returns the card and whether a less strict model verdict was rejected (AC-004.2: the caller
    logs it). With ``model=None`` the card is the rules-only card (``source=rules``), which
    still carries a rule-table alternative when AC-001.3 allows one. ``verdict`` is the
    already computed Layer 1 verdict, if the caller has one.
    """
    if verdict is None:
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
        model_note=model_note,
        request_id=uuid.uuid4().hex if request_id is None else request_id,
    )
    return card, combined.downgrade_rejected


def rules_card(request: CheckRequest) -> DecisionCard:
    """Run Layer 1 only and return the card (``source=rules``)."""
    return combined_card(request, None)[0]


def _allowed_alternatives(drug_id: str) -> tuple[str, ...]:
    """Drugs the rule table allows as alternatives to ``drug_id`` (any conflict type)."""
    found = dict.fromkeys(
        alternative.drug_id
        for (proposed, _conflict), alternatives in rule_table.ALLOWED_ALTERNATIVES.items()
        if proposed == drug_id
        for alternative in alternatives
    )
    return tuple(found)


def _names_unshown_drug(model: ModelVerdict, card: DecisionCard, request: CheckRequest) -> bool:
    """True if the model text names its alternative although the card does not show it."""
    pick = model.alternative_drug_id
    if pick is None or (card.alternative is not None and card.alternative.drug_id == pick):
        return False
    shown = [request.order.drug_id]
    if card.alternative is not None:
        shown.append(card.alternative.drug_id)
    return any(
        content_violation(text, allowed_drug_ids=shown, drug_list=rule_table.DRUG_IDS) is not None
        for text in (model.headline, model.rationale)
    )


def _assess(client: ModelClient, model_request: ModelRequest) -> ModelResult:
    try:
        return client.assess(model_request)
    except Exception:
        # Fail-safe boundary (REQ-005): the client should never raise, but if it does the
        # check still returns the rules-only card. The message may carry context: dropped.
        return ModelResult(
            outcome=ModelOutcome.UNAVAILABLE,
            verdict=None,
            attempts=0,
            latency_ms=0,
            invalid_reason="exception",
        )


def final_card(
    request: CheckRequest,
    client: ModelClient,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> DecisionCard:
    """Full check: rules, model, escalate-only combiner, alternative re-check, one log line."""
    started = clock()
    rules_verdict = rules_engine.evaluate(request.context, request.order)
    rules_latency_ms = round((clock() - started) * 1000)
    result = _assess(
        client,
        ModelRequest(
            context=request.context,
            order=request.order,
            rules_verdict=rules_verdict,
            allowed_alternatives=_allowed_alternatives(request.order.drug_id),
            drug_list=rule_table.DRUG_IDS,
        ),
    )
    model = result.verdict if result.outcome is ModelOutcome.OK else None
    card, downgrade_rejected = combined_card(
        request,
        model,
        verdict=rules_verdict,
        model_note=None if model is not None else MODEL_UNAVAILABLE_NOTE,
    )
    if model is not None and _names_unshown_drug(model, card, request):
        # The model's text recommends a drug the card does not offer (the Layer 1 re-check
        # rejected it): keep its escalation but use the rules/fallback text (AC-003.5).
        card, downgrade_rejected = combined_card(
            request,
            model.model_copy(update={"headline": "", "rationale": ""}),
            card.request_id,
            verdict=rules_verdict,
        )
    log_event(
        LOGGER,
        CHECK_EVENT,
        request_id=card.request_id,
        rule_ids=[rule.rule_id for rule in rules_verdict.fired_rules],
        rules_status=rules_verdict.status.value,
        rules_risk_level=rules_verdict.risk_level.value,
        model_status=None if model is None else model.status.value,
        model_risk_level=None if model is None else model.risk_level.value,
        final_status=card.status.value,
        final_risk_level=card.risk_level.value,
        source=card.source.value,
        rules_latency_ms=rules_latency_ms,
        model_latency_ms=result.latency_ms,
        total_latency_ms=round((clock() - started) * 1000),
        model_outcome=result.outcome.value,
        model_attempts=result.attempts,
        invalid_reason=result.invalid_reason,
        downgrade_rejected=downgrade_rejected,
        prompt_version=prompt.PROMPT_VERSION,
    )
    return card
