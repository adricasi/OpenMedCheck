"""Note findings: verify the model's quotes and let the rules decide (AC-003.6, AC-003.7).

Pure: no I/O, no logging of patient context. The model reads the free text and returns
findings (a kind, a code and a quote); a finding is kept only if its code is valid for its kind
and its quote appears word for word in the ED note or the reason for consult. Kept findings are
added to the coded context and Layer 1 runs again. Findings only add facts, so the result is
never less strict than the verdict on the coded context alone (ADR 0006).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

from openmedcheck import rule_table, rules_engine
from openmedcheck.contracts import (
    FindingKind,
    FiredRule,
    NoteFinding,
    Order,
    PatientContext,
    RulesVerdict,
)
from openmedcheck.rule_table import ContextRule

MAX_FINDINGS = 10  # the prompt asks for at most 4 conditions, 3 medications and 3 allergies
MIN_QUOTE_CHARS = 3
MAX_QUOTE_CHARS = 120

CONDITION_CODES: tuple[str, ...] = ("ACS", "ACTIVE_GI_BLEED", "HEART_FAILURE", "PREGNANCY")
MEDICATION_CODES: tuple[str, ...] = rule_table.DRUG_IDS
ALLERGY_CODES: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            *rule_table.DRUG_IDS,
            *(drug.active_ingredient for drug in rule_table.DRUGS),
            *rule_table.CLASS_IDS,
        ]
    )
)
CODES_BY_KIND: dict[FindingKind, tuple[str, ...]] = {
    FindingKind.CONDITION: CONDITION_CODES,
    FindingKind.MEDICATION: MEDICATION_CODES,
    FindingKind.ALLERGY: ALLERGY_CODES,
}
ALL_CODES: tuple[str, ...] = tuple(
    dict.fromkeys(code for codes in CODES_BY_KIND.values() for code in codes)
)

# A verbatim quote proves the words exist, not that they mean the code, so the quote must also
# name what it is coded as (safety review, ADR 0006).
CONDITION_TERMS: dict[str, tuple[str, ...]] = {
    "ACS": ("acs", "coronary", "stemi", "nstemi", "angina", "myocardial infarction"),
    "ACTIVE_GI_BLEED": (
        "bleed",
        "melena",
        "melaena",
        "haematemesis",
        "hematemesis",
        "haemorrhage",
        "hemorrhage",
        "coffee-ground",
        "coffee ground",
    ),
    "HEART_FAILURE": ("heart failure", "cardiac failure", "hfref", "hfpef", "chf", "ccf"),
    "PREGNANCY": ("pregnan", "gestation", "weeks pregnant"),
}
# Negation is local (safety review): a cue counts only inside the clause of the matched term,
# a few words before it ("no GI bleeding", "history of ACS", "not on aspirin") or right after it
# ("ACS ruled out"). Clauses end at punctuation, "but", "except", "although" and "however", so
# "Suspected ACS, no ST elevation" and "No known allergies except ... ibuprofen" keep the finding.
_PRE_NEGATION = re.compile(
    r"\b(?:no|not|denies|denied|negative\s+for|free\s+of|history\s+of|h/o|previous|prior)\b",
    re.IGNORECASE,
)
_POST_NEGATION = re.compile(
    r"^\W*(?:\w+\W+){0,2}?(?:ruled\s+out|rules\s+out|excluded|resolved|unlikely|stopped|"
    r"discontinued)\b",
    re.IGNORECASE,
)
# "Stopped", "discontinued" and "off" negate only when right before the term ("stopped taking
# warfarin", "off warfarin"); elsewhere they are too common ("pain on and off ... angina").
_ADJACENT_PRE_NEGATION = re.compile(
    r"\b(?:stopped|discontinued|off)(?:\s+taking)?\s*$", re.IGNORECASE
)
_CLAUSE_END = re.compile(
    r"[.;:,!?\n]|\b(?:but|except|although|however|and|then|started|onto)\b", re.IGNORECASE
)
_PRE_WORDS = 4


def _words(text: str) -> list[str]:
    return [part for part in re.split(r"[_\-\s()]+", text.casefold()) if len(part) >= 4]


def _code_terms(kind: FindingKind, code: str) -> tuple[str, ...]:
    if kind is FindingKind.CONDITION:
        return CONDITION_TERMS[code]
    drug = rule_table.DRUGS_BY_ID.get(code)
    if drug is None:  # an allergy coded as a class ID or an active ingredient
        return tuple(_words(code)) or (code.casefold(),)
    # The drug ID and active ingredient only: display names add generic words ("acid").
    return tuple({*_words(drug.drug_id), *_words(drug.active_ingredient)})


def _term_in(span: re.Match[str], terms: Sequence[str]) -> re.Match[str] | None:
    """First code term inside the matched quote, at a word start ("sacs" is not ACS)."""
    pattern = "|".join(rf"(?<![a-z]){re.escape(term)}" for term in terms)
    return re.compile(pattern, re.IGNORECASE).search(span.string, span.start(), span.end())


def _negated(text: str, term: re.Match[str]) -> bool:
    before = text[: term.start()]
    ends = list(_CLAUSE_END.finditer(before))
    clause_before = before[ends[-1].end() :] if ends else before
    window = " ".join(clause_before.split()[-_PRE_WORDS:])
    after = text[term.end() :]
    stop = _CLAUSE_END.search(after)
    clause_after = after[: stop.start()] if stop else after
    return bool(
        _PRE_NEGATION.search(window)
        or _ADJACENT_PRE_NEGATION.search(clause_before)
        or _POST_NEGATION.search(clause_after)
    )


def _find(quote: str, text: str) -> re.Match[str] | None:
    """The quote in ``text``, ignoring case and spacing (NFKC on both)."""
    words = unicodedata.normalize("NFKC", quote).split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(word) for word in words)
    return re.search(pattern, unicodedata.normalize("NFKC", text), re.IGNORECASE)


def _verified(finding: NoteFinding, context: PatientContext) -> NoteFinding | None:
    if finding.code not in CODES_BY_KIND[finding.kind]:
        return None
    for text in (context.ed_note, context.reason_for_consult):
        match = _find(finding.quote, text)
        if match is None:
            continue
        span = match.group()
        if not MIN_QUOTE_CHARS <= len(span) <= MAX_QUOTE_CHARS:
            return None
        term = _term_in(match, _code_terms(finding.kind, finding.code))
        if term is None or _negated(match.string, term):
            return None
        # Show the note's own words, not the model's copy of them.
        return finding.model_copy(update={"quote": span})
    return None


def verify(findings: Iterable[NoteFinding], context: PatientContext) -> tuple[NoteFinding, ...]:
    """Keep findings whose code fits the kind and whose quote is verbatim note text that names
    the code and is not negated; drop the rest (AC-003.6)."""
    kept: dict[tuple[FindingKind, str], NoteFinding] = {}
    for finding in findings:
        checked = _verified(finding, context)
        if checked is None:
            continue
        kept.setdefault((checked.kind, checked.code), checked)
        if len(kept) == MAX_FINDINGS:
            break
    return tuple(kept.values())


def _union(existing: Sequence[str], added: Iterable[str]) -> list[str]:
    return list(dict.fromkeys([*existing, *added]))


def augment(context: PatientContext, findings: Sequence[NoteFinding]) -> PatientContext:
    """The coded context plus the kept findings; nothing is ever removed."""

    def codes(kind: FindingKind) -> list[str]:
        return [finding.code for finding in findings if finding.kind is kind]

    return context.model_copy(
        update={
            "diagnoses": _union(context.diagnoses, codes(FindingKind.CONDITION)),
            "chronic_medications": _union(
                context.chronic_medications, codes(FindingKind.MEDICATION)
            ),
            "allergies": _union(context.allergies, codes(FindingKind.ALLERGY)),
        }
    )


def _allergy_quotes(findings: Sequence[NoteFinding], order: Order) -> list[str]:
    drug = rule_table.DRUGS_BY_ID[order.drug_id]
    names = {drug.drug_id.casefold(), drug.active_ingredient.casefold(), drug.drug_class.casefold()}
    return [
        finding.quote
        for finding in findings
        if finding.kind is FindingKind.ALLERGY and finding.code.casefold() in names
    ]


def _context_quotes(rule: ContextRule, findings: Sequence[NoteFinding]) -> list[str]:
    quotes = [
        finding.quote
        for finding in findings
        if rule.diagnosis is not None
        and finding.kind is FindingKind.CONDITION
        and finding.code == rule.diagnosis
    ]
    if rule.chronic_class is not None:
        quotes += [
            finding.quote
            for finding in findings
            if finding.kind is FindingKind.MEDICATION
            and rule_table.DRUGS_BY_ID[finding.code].drug_class == rule.chronic_class
        ]
    return quotes


def _evidence(rule: FiredRule, findings: Sequence[NoteFinding], order: Order) -> list[str]:
    entry = rule_table.RULES_BY_ID[rule.rule_id]
    if entry is rule_table.ALLERGY_RULE:
        return _allergy_quotes(findings, order)
    if isinstance(entry, ContextRule):
        return _context_quotes(entry, findings)
    return []


def evaluate(
    context: PatientContext,
    order: Order,
    findings: Sequence[NoteFinding],
    coded: RulesVerdict | None = None,
) -> RulesVerdict:
    """Layer 1 on the coded context plus the kept findings, with quotes on new rules.

    ``coded`` is the verdict on the coded context, if the caller already has it. Rules that
    also fire on the coded context carry no evidence: the record already supports them.
    """
    if coded is None:
        coded = rules_engine.evaluate(context, order)
    if not findings:
        return coded
    augmented = rules_engine.evaluate(augment(context, findings), order)
    coded_ids = {rule.rule_id for rule in coded.fired_rules}
    fired = [
        rule
        if rule.rule_id in coded_ids
        else rule.model_copy(update={"evidence": _evidence(rule, findings, order)})
        for rule in augmented.fired_rules
    ]
    return augmented.model_copy(update={"fired_rules": fired})
