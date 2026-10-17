"""Layer 3: the escalate-only combiner (REQ-004, ADR 0003). Pure: no I/O, no logging.

Merges the rules verdict with an optional model verdict. The model can only make the result
stricter: status and tier are the maximum of the two, the renal flag is the union, and fired
rule reasons are always carried over. Whatever the model returns (any status, tier, flag,
conflict type or text), the result is never below the rules verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from openmedcheck import rule_table
from openmedcheck.contracts import (
    ConflictType,
    FiredRule,
    ModelVerdict,
    RiskLevel,
    RulesVerdict,
    Source,
    Status,
)

NO_ISSUE_HEADLINE = "No issue found by these checks"
NO_ISSUE_RATIONALE = "No rule in the current table conflicts with this order and context."
# Used only when the renal flag alone lifts a NO_ISSUE verdict to WARNING (AC-004.4).
RENAL_FLAG_HEADLINE = "Check renal function for this order"
RENAL_FLAG_RATIONALE = "Renal dose adjustment may be needed for this order."
# Last-resort text when a model headline or rationale is blank and the rules have none.
FALLBACK_HEADLINES = {
    Status.WARNING: "Review this order before signing",
    Status.BLOCKED: "Order conflicts with patient context",
}
FALLBACK_RATIONALE = "See the model check; the rule table reasons, if any, are listed below."

MAX_HEADLINE_WORDS = 8
MAX_HEADLINE_CHARS = 60
MAX_RATIONALE_SENTENCES = 2
MAX_RATIONALE_CHARS = 300

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class CombinedVerdict:
    """The merged verdict; ``conflict_type`` is the deciding one for alternative selection."""

    status: Status
    risk_level: RiskLevel
    headline: str
    rationale: str
    renal_adjustment_required: bool
    fired_rules: list[FiredRule]
    crcl_ml_min: float | None
    conflict_type: ConflictType | None
    model_raised: bool
    downgrade_rejected: bool
    source: Source


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "…"


def limit_headline(text: str) -> str:
    """Cut ``text`` to at most 8 words and 60 characters (AC-001.2)."""
    return _truncate(" ".join(text.split()[:MAX_HEADLINE_WORDS]), MAX_HEADLINE_CHARS)


def limit_rationale(text: str) -> str:
    """Cut ``text`` to at most 2 sentences and 300 characters (AC-001.2)."""
    sentences = _SENTENCE_BREAK.split(" ".join(text.split()))[:MAX_RATIONALE_SENTENCES]
    return _truncate(" ".join(sentences), MAX_RATIONALE_CHARS)


def _deciding_conflict(
    rules: RulesVerdict, model: ModelVerdict | None, status: Status
) -> ConflictType | None:
    """Conflict type that set the final status (AC-004.6 a).

    The strongest fired rule's when the rules set it; the model's when the model set it
    (None means no alternative); RENAL when only the renal-flag floor lifted the status.
    """
    if rules.status is status and rules.fired_rules:

        def strength(rule: FiredRule) -> tuple[int, int]:
            entry = rule_table.RULES_BY_ID[rule.rule_id]
            return entry.status.rank, entry.risk_level.rank

        return max(rules.fired_rules, key=strength).conflict_type
    if model is not None and model.status is status:
        return model.conflict_type
    return ConflictType.RENAL


def combine(
    rules: RulesVerdict,
    rules_headline: str,
    rules_rationale: str,
    model: ModelVerdict | None,
) -> CombinedVerdict:
    """Merge the rules verdict (with its card text) and an optional model verdict.

    ``rules_headline`` and ``rules_rationale`` are the text of the rules-only card. Model text
    is used only when the model's status equals the final one and its verdict is at least as
    strict as the rules'; a less strict model verdict is rejected (AC-004.2). Both texts are cut
    to the AC-001.2 limits; the full rule reasons stay in ``fired_rules`` (AC-004.5).
    """
    status, risk_level = rules.status, rules.risk_level
    renal_flag = rules.renal_adjustment_required
    downgrade_rejected = False
    if model is not None:
        # Any lower component counts as a downgrade attempt (AC-004.2); the result still takes
        # the maximum of each (AC-004.1), so the tier is never below the rules' tier.
        downgrade_rejected = (
            model.status.rank < rules.status.rank or model.risk_level.rank < rules.risk_level.rank
        )
        status = max(status, model.status, key=lambda s: s.rank)
        risk_level = max(risk_level, model.risk_level, key=lambda r: r.rank)
        renal_flag = renal_flag or model.renal_adjustment_required
    if renal_flag and status is Status.NO_ISSUE:
        status = Status.WARNING
    if status is Status.NO_ISSUE:
        risk_level = RiskLevel.LOW  # a clean card never carries an elevated tier

    if status is Status.NO_ISSUE:
        headline, rationale = NO_ISSUE_HEADLINE, NO_ISSUE_RATIONALE
    elif (
        model is not None
        and model.status is status
        and (status.rank > rules.status.rank or model.risk_level.rank >= rules.risk_level.rank)
    ):
        headline = limit_headline(model.headline) or limit_headline(rules_headline)
        rationale = limit_rationale(model.rationale) or limit_rationale(rules_rationale)
    elif rules.status is status:
        headline, rationale = limit_headline(rules_headline), limit_rationale(rules_rationale)
    else:
        headline, rationale = RENAL_FLAG_HEADLINE, RENAL_FLAG_RATIONALE
    if status is not Status.NO_ISSUE:
        headline = headline or FALLBACK_HEADLINES[status]
        rationale = rationale or FALLBACK_RATIONALE

    return CombinedVerdict(
        status=status,
        risk_level=risk_level,
        headline=headline,
        rationale=rationale,
        renal_adjustment_required=renal_flag,
        fired_rules=list(rules.fired_rules),
        crcl_ml_min=rules.crcl_ml_min,
        conflict_type=_deciding_conflict(rules, model, status),
        model_raised=status.rank > rules.status.rank,
        downgrade_rejected=downgrade_rejected,
        source=Source.RULES if model is None else Source.RULES_MODEL,
    )
