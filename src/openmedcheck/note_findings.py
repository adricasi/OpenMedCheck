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

# The prompt asks for at most 4 conditions, 3 medications, 3 allergies and 3 history items.
MAX_FINDINGS = 13
MIN_QUOTE_CHARS = 3
MAX_QUOTE_CHARS = 120

CONDITION_CODES: tuple[str, ...] = ("ACS", "ACTIVE_GI_BLEED", "HEART_FAILURE", "PREGNANCY")
# Past medical history (REQ-016): past events, kept apart from the current conditions.
HISTORY_CODES: tuple[str, ...] = ("PAST_GI_BLEED", "ISCHAEMIC_HEART_DISEASE")
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
    FindingKind.HISTORY: HISTORY_CODES,
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
    "PREGNANCY": ("pregnan", "gestation"),
}
# Specific phrases only (safety review): a bare "ulcer", "stent" or "infarct" also names a
# diabetic foot ulcer, a ureteric stent or a cerebral infarct.
HISTORY_TERMS: dict[str, tuple[str, ...]] = {
    "PAST_GI_BLEED": (
        "gi bleed",
        "gi haemorrhage",
        "gi hemorrhage",
        "gib",
        "ugib",
        "gastrointestinal bleed",
        "gastrointestinal haemorrhage",
        "gastrointestinal hemorrhage",
        "melena",
        "melaena",
        "haematemesis",
        "hematemesis",
        "coffee-ground",
        "coffee ground",
        "peptic ulcer",
        "gastric ulcer",
        "duodenal ulcer",
        "stomach ulcer",
        "bleeding ulcer",
        "perforated ulcer",
        "pud",
        "gi perforation",
        "gastrointestinal perforation",
        "bowel perforation",
    ),
    "ISCHAEMIC_HEART_DISEASE": (
        "acs",
        "stemi",
        "nstemi",
        "angina",
        "myocardial infarct",
        "mi",
        "heart attack",
        "coronary stent",
        "cardiac stent",
        "pci",
        "ptca",
        "cabg",
        "coronary artery bypass",
        "coronary bypass",
        "ihd",
        "cad",
        "chd",
        "ischaemic heart",
        "ischemic heart",
        "coronary artery disease",
        "coronary heart disease",
        "coronary disease",
    ),
}
# Short history terms ("mi", "cad") must be whole words, a plural "s" aside: "mild" is not an
# MI, "two previous MIs" is.
_SHORT_TERM = 3
# Past history is evidence, not negation (ADR 0009): for history findings only denials count,
# and "resolved" says the event happened. The denial looks a little further back ("no known
# history of peptic ulcer") but stops at "since" and its kin ("no chest pain since MI").
_PRE_NEGATION_HISTORY = re.compile(
    r"\b(?:no|not|never|nil|without|denies|denied|negative\s+for|free\s+of)\b", re.IGNORECASE
)
_HISTORY_DENIAL_WORDS = 6
_DENIAL_STOP = re.compile(r"\b(?:since|after|following|post|s/p)\b", re.IGNORECASE)
_POST_NEGATION_HISTORY = re.compile(
    r"^(?P<gap>\W*(?:[\w']+\W+){0,2}?)(?:ruled\s+out|rules\s+out|excluded|unlikely)\b",
    re.IGNORECASE,
)
# A relative's history is not the patient's (AC-016.4). A blood relative counts in the term's
# comma-delimited clause ("Mother: MI at 60", "father and uncle had MIs"); a family-history
# label counts anywhere earlier in the sentence ("Family history of diabetes and MI"). Spouses
# and children are left out: "brought in by daughter, previous MI" is the patient's history.
_RELATIVE = re.compile(
    r"\b(?:(?:father|mother|dad|mum|mom|brother|sister|sibling|parent|uncle|aunt|cousin)s?|"
    r"grand\w*)\b",
    re.IGNORECASE,
)
_FAMILY = re.compile(r"\b(?:family|fhx|fh|f/h)\b", re.IGNORECASE)
# An acute event in a past-history list ("PMH: hypertension, upper GI bleed in 2021") is not a
# current one (AC-016.7): the label counts anywhere earlier in the sentence. Only for events:
# a chronic condition or a pregnancy in such a list ("Background: COPD, heart failure") still
# holds today.
_PAST_LIST_EVENT_CODES = frozenset({"ACS", "ACTIVE_GI_BLEED"})
_PAST_HISTORY_LABEL = re.compile(
    r"\b(?:past\s+medical\s+history|past\s+history|medical\s+history|pmhx?|background)\s*:",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.;!?\n]")
_RELATIVE_CLAUSE_END = re.compile(r"[,.;!?\n]")
# Negation is local (safety review): a cue counts only inside the clause of the matched term,
# a few words before it ("no GI bleeding", "history of ACS", "not on aspirin") or right after it
# ("ACS ruled out"). Clauses end at punctuation, "but", "except", "although" and "however", so
# "Suspected ACS, no ST elevation" and "No known allergies except ... ibuprofen" keep the finding.
_PRE_NEGATION = re.compile(
    r"\b(?:no|not|denies|denied|negative\s+for|free\s+of|history\s+of|h/o|previous|prior)\b",
    re.IGNORECASE,
)
# "ACS ruled out", "bleeding resolved": up to two words between, but never a negator ("ACS not
# ruled out" keeps the finding).
_POST_NEGATION = re.compile(
    r"^(?P<gap>\W*(?:[\w']+\W+){0,2}?)"
    r"(?:ruled\s+out|rules\s+out|excluded|resolved|unlikely)\b",
    re.IGNORECASE,
)
# Only for pregnancy and only straight after the term ("pregnancy test negative"); a negative
# troponin or stress test says nothing about an ACS.
_POST_PREGNANCY_TEST_NEGATIVE = re.compile(
    r"^[ \t]*test[ \t]+(?:was[ \t]+|is[ \t]+)?negative\b", re.IGNORECASE
)
# "non-pregnant" only: a generic "non" would negate "non-ST elevation ACS".
_NON_PREFIX = re.compile(r"\bnon-?\Z", re.IGNORECASE)
_NEGATOR = re.compile(r"\b(?:not|never|no|cannot|\w+n't)\b", re.IGNORECASE)
# "Warfarin stopped", "warfarin was discontinued": right after the drug, so "warfarin not
# stopped" and "aspirin to be stopped" keep the finding.
_POST_STOPPED = re.compile(
    r"^[ \t]*(?:was[ \t]+|is[ \t]+|has[ \t]+been[ \t]+|been[ \t]+)?(?:stopped|discontinued)\b",
    re.IGNORECASE,
)
# "Stopped", "discontinued" and "off" negate only when right before the term ("stopped taking
# warfarin", "off warfarin"); elsewhere they are too common ("pain on and off ... angina").
_ADJACENT_PRE_NEGATION = re.compile(
    # Spaces and tabs only: a cue on the previous line never reaches the term.
    r"(?<!\band[ \t])(?<!\bon[ \t])\b(?:stopped|discontinued|off)(?:[ \t]+taking)?[ \t]*\Z",
    re.IGNORECASE,
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
    if kind is FindingKind.HISTORY:
        return HISTORY_TERMS[code]
    drug = rule_table.DRUGS_BY_ID.get(code)
    if drug is None:  # an allergy coded as a class ID or an active ingredient
        return tuple(_words(code)) or (code.casefold(),)
    # The drug ID and active ingredient only: display names add generic words ("acid").
    return tuple({*_words(drug.drug_id), *_words(drug.active_ingredient)})


def _phrase(term: str) -> str:
    return r"\s+".join(re.escape(word) for word in term.split())


def _term_in(
    span: re.Match[str], terms: Sequence[str], *, whole_short: bool = False
) -> re.Match[str] | None:
    """First code term inside the matched quote, at a word start ("sacs" is not ACS).

    Words of a term match across any spacing. ``whole_short``: terms of up to three letters
    must also end a word, a plural "s" aside ("mild" is not MI).
    """
    pattern = "|".join(
        rf"(?<![a-z]){_phrase(term)}"
        + (r"s?(?![a-z])" if whole_short and len(term) <= _SHORT_TERM else "")
        for term in terms
    )
    return re.compile(pattern, re.IGNORECASE).search(span.string, span.start(), span.end())


def _post_negated(clause_after: str, pattern: re.Pattern[str] = _POST_NEGATION) -> bool:
    """A post-term cue ("ruled out") with no negator between it and the term."""
    match = pattern.search(clause_after)
    return match is not None and not _NEGATOR.search(match.group("gap"))


def _negated(text: str, term: re.Match[str], kind: FindingKind, code: str) -> bool:
    text = text.replace("\u2019", "'").replace("\u02bc", "'")  # typographic apostrophes
    before = text[: term.start()]
    ends = list(_CLAUSE_END.finditer(before))
    clause_before = before[ends[-1].end() :] if ends else before
    window = " ".join(clause_before.split()[-_PRE_WORDS:])
    # Terms can be word prefixes ("pregnan", "bleed"): look after the whole word.
    word_end = term.end()
    while word_end < len(text) and (text[word_end].isalnum() or text[word_end] == "'"):
        word_end += 1
    after = text[word_end:]
    stop = _CLAUSE_END.search(after)
    clause_after = after[: stop.start()] if stop else after
    if kind is FindingKind.HISTORY:
        return _history_negated(before, after, clause_before, clause_after)
    return bool(
        _PRE_NEGATION.search(window)
        or _post_negated(clause_after)
        or (
            code == "PREGNANCY"
            and bool(_POST_PREGNANCY_TEST_NEGATIVE.search(after) or _NON_PREFIX.search(before))
        )
        or (
            code in _PAST_LIST_EVENT_CODES
            and kind is FindingKind.CONDITION
            and bool(_PAST_HISTORY_LABEL.search(_SENTENCE_END.split(before)[-1]))
        )
        # Stopping a drug only negates a medication finding, checked on the raw text before it.
        or (
            kind is FindingKind.MEDICATION
            and (_ADJACENT_PRE_NEGATION.search(before) or _POST_STOPPED.search(after))
        )
    )


def _history_negated(before: str, after: str, clause_before: str, clause_after: str) -> bool:
    """A denial near the term, or the history of a relative (ADR 0009, AC-016.4)."""
    stops = list(_DENIAL_STOP.finditer(clause_before))
    denial_span = clause_before[stops[-1].end() :] if stops else clause_before
    denial_window = " ".join(denial_span.split()[-_HISTORY_DENIAL_WORDS:])
    relative_before = _RELATIVE_CLAUSE_END.split(before)[-1]
    relative_after = _RELATIVE_CLAUSE_END.split(after, maxsplit=1)[0]
    return bool(
        _PRE_NEGATION_HISTORY.search(denial_window)
        or _post_negated(clause_after, _POST_NEGATION_HISTORY)
        or _RELATIVE.search(relative_before)
        or _RELATIVE.search(relative_after)
        or _FAMILY.search(_SENTENCE_END.split(before)[-1])
        or _FAMILY.search(relative_after)
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
        term = _term_in(
            match,
            _code_terms(finding.kind, finding.code),
            whole_short=finding.kind is FindingKind.HISTORY,
        )
        if term is None or _negated(match.string, term, finding.kind, finding.code):
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
            "history": _union(context.history, codes(FindingKind.HISTORY)),
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
    quotes += [
        finding.quote
        for finding in findings
        if rule.history is not None
        and finding.kind is FindingKind.HISTORY
        and finding.code == rule.history
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
