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

from openmedcheck import note_findings, prompt, rule_table, rules_engine
from openmedcheck.alternatives import select_alternative
from openmedcheck.combiner import combine
from openmedcheck.contracts import (
    CheckRequest,
    ConflictType,
    DecisionCard,
    ModelVerdict,
    PatientContext,
    RiskLevel,
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
# AC-005.3: without the model the note was not read, so a clean rules verdict is not a pass.
NOTE_UNCHECKED_HEADLINE = "Free-text note not checked"
NOTE_UNCHECKED_RATIONALE = (
    "The model check was unavailable, so the free-text note was not checked. The rules found no "
    "conflict in the coded data; review the note before signing."
)
# Conflicts the rules decide from coded data and kept note findings (AC-003.8, ADR 0006): the
# model's own escalation with one of these counts only if a rule of that type fired.
RULE_DECIDED_CONFLICTS = frozenset(
    {
        ConflictType.ANTIPLATELET_ACS,
        ConflictType.GI_BLEED,
        ConflictType.ALLERGY,
        ConflictType.BLEEDING,
        ConflictType.HYPERKALAEMIA,
        ConflictType.HEART_FAILURE,
        ConflictType.PREGNANCY,
        ConflictType.PAST_GI_BLEED,
        ConflictType.ISCHAEMIC_HEART_DISEASE,
    }
)

# Past-history conflicts (ADR 0009): a confirmed escalation counts only up to the status and tier
# of the history rules, which are WARNING until the specialist decides. Not for the current
# types: note lab values are never findings, so a model BLOCKED for "K 6.9" in the note would
# otherwise drop to the missing-lab WARNING.
CAPPED_CONFLICTS = frozenset({ConflictType.PAST_GI_BLEED, ConflictType.ISCHAEMIC_HEART_DISEASE})

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
    context: PatientContext | None = None,
) -> tuple[DecisionCard, bool]:
    """Rules, then the escalate-only combiner, then the alternative re-check.

    Returns the card and whether a less strict model verdict was rejected (AC-004.2: the caller
    logs it). With ``model=None`` the card is the rules-only card (``source=rules``), which
    still carries a rule-table alternative when AC-001.3 allows one. ``verdict`` is the
    already computed Layer 1 verdict, if the caller has one; ``context`` is the context that
    verdict was computed on (the coded context plus kept note findings, AC-003.7), which the
    alternative re-check must also use.
    """
    if context is None:
        context = request.context
    if verdict is None:
        verdict = rules_engine.evaluate(context, request.order)
    headline, rationale = _rules_text(verdict)
    combined = combine(verdict, headline, rationale, model)
    alternative = select_alternative(
        context,
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


def allowed_alternatives(drug_id: str) -> tuple[str, ...]:
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


def _gate_rule_decided(
    model: ModelVerdict | None, verdict: RulesVerdict
) -> tuple[ModelVerdict | None, bool]:
    """Set aside or cap the model's own escalation for a rule-decided conflict (AC-003.8).

    Without a fired rule of the same type the escalation is dropped ("ACS ruled out" read as
    ACS, prompt v5 eval); with one it counts, capped at that rule's status and tier for the
    past-history types. The rules floor
    is untouched: the combiner still never goes below ``verdict``. Returns the gated verdict and
    whether anything was set aside.
    """
    if model is None or model.conflict_type not in RULE_DECIDED_CONFLICTS:
        return model, False
    same_type = [
        rule_table.RULES_BY_ID[rule.rule_id]
        for rule in verdict.fired_rules
        if rule.conflict_type is model.conflict_type
    ]
    if same_type and model.conflict_type not in CAPPED_CONFLICTS:
        return model, False
    if same_type:
        status = max((rule.status for rule in same_type), key=lambda item: item.rank)
        tier = max((rule.risk_level for rule in same_type), key=lambda item: item.rank)
        if model.status.rank <= status.rank and model.risk_level.rank <= tier.rank:
            return model, False
        capped = model.model_copy(
            update={
                "status": min((model.status, status), key=lambda item: item.rank),
                "risk_level": min((model.risk_level, tier), key=lambda item: item.rank),
                "headline": "",
                "rationale": "",
            }
        )
        return capped, True
    neutral = model.model_copy(
        update={
            "status": Status.NO_ISSUE,
            "risk_level": RiskLevel.LOW,
            "headline": "",
            "rationale": "",
            "conflict_type": None,
            "alternative_drug_id": None,
        }
    )
    return neutral, True


def _flag_unchecked_note(card: DecisionCard) -> DecisionCard:
    """A rules-only NO_ISSUE card becomes a WARNING: the note was never read (AC-005.3)."""
    if card.status is not Status.NO_ISSUE:
        return card
    return card.model_copy(
        update={
            "status": Status.WARNING,
            "risk_level": RiskLevel.MODERATE,
            "headline": NOTE_UNCHECKED_HEADLINE,
            "rationale": NOTE_UNCHECKED_RATIONALE,
        }
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
            allowed_alternatives=allowed_alternatives(request.order.drug_id),
            drug_list=rule_table.DRUG_IDS,
        ),
    )
    model = result.verdict if result.outcome is ModelOutcome.OK else None
    # Gemma reads the note, the rules decide (ADR 0006): kept findings only add facts.
    found = () if model is None else model.note_findings
    findings_unapplied = False
    try:
        kept = note_findings.verify(found, request.context)
        context = note_findings.augment(request.context, kept)
        verdict = note_findings.evaluate(request.context, request.order, kept, coded=rules_verdict)
    except Exception:
        # Fail-safe (REQ-005): a finding that cannot be applied never costs the coded verdict,
        # and the note then counts as not checked (AC-005.3).
        kept, context, verdict = (), request.context, rules_verdict
        findings_unapplied = True
    # AC-004.2 is about the model trying to go below the rules it was shown (the coded verdict),
    # not below facts added after it answered.
    downgrade_attempted = model is not None and (
        model.status.rank < rules_verdict.status.rank
        or model.risk_level.rank < rules_verdict.risk_level.rank
    )
    try:
        # Without the findings the rules cannot confirm anything, so the gate would discard a
        # real escalation; keep the model's own verdict instead (safety review).
        if not findings_unapplied:
            model, escalation_gated = _gate_rule_decided(model, verdict)
        else:
            escalation_gated = False
        card, _ = combined_card(
            request,
            model,
            verdict=verdict,
            model_note=None if model is not None else MODEL_UNAVAILABLE_NOTE,
            context=context,
        )
        if model is not None and _names_unshown_drug(model, card, request):
            # The model's text recommends a drug the card does not offer (the Layer 1 re-check
            # rejected it): keep its escalation but use the rules/fallback text (AC-003.5).
            card, _ = combined_card(
                request,
                model.model_copy(update={"headline": "", "rationale": ""}),
                card.request_id,
                verdict=verdict,
                context=context,
            )
    except Exception:
        # Fail-safe (REQ-005): anything that goes wrong after the model call yields the rules-only
        # card on the coded context, never an error. The message may carry context: dropped.
        model, escalation_gated, kept, verdict = None, False, (), rules_verdict
        card, _ = combined_card(
            request, None, verdict=rules_verdict, model_note=MODEL_UNAVAILABLE_NOTE
        )
    if model is None or findings_unapplied:
        card = _flag_unchecked_note(card)
    log_event(
        LOGGER,
        CHECK_EVENT,
        request_id=card.request_id,
        rule_ids=[rule.rule_id for rule in verdict.fired_rules],
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
        downgrade_rejected=downgrade_attempted,
        prompt_version=prompt.PROMPT_VERSION,
        note_findings_kept=len(kept),
        model_escalation_gated=escalation_gated,
        note_findings_dropped=len(found) - len(kept),
    )
    return card
