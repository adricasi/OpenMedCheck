"""Alternative selection with the Layer 1 re-check (AC-001.3, AC-004.6, AC-004.7).

Pure: no I/O, no logging. Candidates come only from the rule table's allowed alternatives for
(proposed drug, deciding conflict type); a model suggestion can only choose among them or be
discarded. Doses come from the rule table; an unreviewed dose is never shown (NFR-011).
"""

from __future__ import annotations

from openmedcheck import rule_table, rules_engine
from openmedcheck.contracts import Alternative, ConflictType, Order, PatientContext, Status
from openmedcheck.rule_table import AllowedAlternative


def _rewritten_order(alternative: AllowedAlternative) -> Order:
    return Order.model_validate(
        {
            "drug_id": alternative.drug_id,
            "dose_text": alternative.dose_text,
            "route": alternative.route,
            "frequency": alternative.frequency,
        }
    )


def _passes_layer_one(context: PatientContext, alternative: AllowedAlternative) -> bool:
    """AC-004.6 (c): NO_ISSUE, or WARNING when the rule-table dose is specialist-reviewed."""
    status = rules_engine.evaluate(context, _rewritten_order(alternative)).status
    return status is Status.NO_ISSUE or (
        status is Status.WARNING and rule_table.is_reviewed(alternative)
    )


def _to_card_alternative(alternative: AllowedAlternative) -> Alternative:
    reviewed = rule_table.is_reviewed(alternative)
    return Alternative(
        drug_id=alternative.drug_id,
        name=rule_table.DRUGS_BY_ID[alternative.drug_id].name,
        dose_text=alternative.dose_text if reviewed else rule_table.DOSE_FALLBACK_TEXT,
        route=alternative.route if reviewed else "",
        frequency=alternative.frequency if reviewed else "",
        reason=alternative.reason,
    )


def select_alternative(
    context: PatientContext,
    order: Order,
    *,
    status: Status,
    conflict_type: ConflictType | None,
    model_raised: bool,
    model_alternative_id: str | None,
) -> Alternative | None:
    """Return the first qualifying alternative, or None.

    Candidates: the model's pick (if it is on the allowed list; anything else is discarded),
    then the allowed list in table order. ``model_raised`` is true when the model lifted the
    final status above the rules status; then same-class alternatives are excluded.
    """
    if status is Status.NO_ISSUE or conflict_type is None:
        return None
    allowed = rule_table.ALLOWED_ALTERNATIVES.get((order.drug_id, conflict_type), ())
    preferred = [a for a in allowed if a.drug_id == model_alternative_id]
    proposed_class = rule_table.DRUGS_BY_ID[order.drug_id].drug_class
    for candidate in (*preferred, *allowed):
        if model_raised and rule_table.DRUGS_BY_ID[candidate.drug_id].drug_class == proposed_class:
            continue
        if _passes_layer_one(context, candidate):
            return _to_card_alternative(candidate)
    return None
