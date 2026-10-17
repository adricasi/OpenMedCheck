"""The rule table: drug list, classes, rules and allowed alternatives (REQ-002, NFR-011).

Pure data, no I/O. Every entry carries a source citation, a conflict type and a
specialist-review mark (``reviewed_by`` / ``reviewed_on``). Nothing here has been reviewed by a
clinical specialist yet (T-006): numeric doses stay hidden until ``reviewed_on`` is set.

The citations name a product and section of the Spanish SmPC (AEMPS CIMA, https://cima.aemps.es)
or a published guideline. They were written without access to the live documents; the review
sheet (``docs/clinical-review.md``) asks the specialist to confirm each one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from openmedcheck.contracts import ConflictType, RiskLevel, Status

RENAL_FALLBACK_GUIDANCE = "Renal adjustment required — consult SmPC"
DOSE_FALLBACK_TEXT = "Dose: consult SmPC"

CIMA = "AEMPS CIMA (https://cima.aemps.es)"


class RenalBasis(StrEnum):
    """Which renal measure a rule uses (AC-002.2)."""

    EGFR = "EGFR"
    CRCL = "CRCL"


@dataclass(frozen=True)
class Drug:
    drug_id: str
    name: str
    active_ingredient: str
    drug_class: str


@dataclass(frozen=True)
class RuleEntry:
    """Fields shared by every rule-table entry."""

    rule_id: str
    status: Status
    risk_level: RiskLevel
    conflict_type: ConflictType
    reason: str
    source: str
    reviewed_by: str | None = None
    reviewed_on: date | None = None


@dataclass(frozen=True)
class AllergyRule(RuleEntry):
    """Fires when the drug's active ingredient or class equals a recorded allergy (AC-002.5)."""


@dataclass(frozen=True)
class ContextRule(RuleEntry):
    """Class contraindication given a coded diagnosis (AC-002.3, AC-002.4).

    ``chronic_class`` set: also requires a chronic medication of that class.
    """

    applies_to_class: str = ""
    diagnosis: str = ""
    chronic_class: str | None = None


@dataclass(frozen=True)
class RenalRule(RuleEntry):
    """Fires when the renal measure is strictly below ``threshold`` (AC-002.2)."""

    drug_id: str = ""
    basis: RenalBasis = RenalBasis.CRCL
    threshold: float = 0.0
    # Numeric adjustment taken from the SmPC; shown only once reviewed (NFR-011, Q-5).
    dose_guidance: str | None = None


@dataclass(frozen=True)
class RenalUnknownRule(RuleEntry):
    """Fires when the lab a drug's renal rule needs is missing (AC-001.5)."""

    basis: RenalBasis = RenalBasis.CRCL


@dataclass(frozen=True)
class AllowedAlternative:
    """A substitute offered for (proposed drug, conflict type); dose from the source only."""

    proposed_drug_id: str
    conflict_type: ConflictType
    drug_id: str
    dose_text: str
    route: str
    frequency: str
    reason: str
    source: str
    reviewed_by: str | None = None
    reviewed_on: date | None = None


def is_reviewed(entry: RuleEntry | AllowedAlternative) -> bool:
    """True once a specialist has signed the entry off (both mark fields set)."""
    return entry.reviewed_by is not None and entry.reviewed_on is not None


def shown_dose_guidance(rule: RenalRule) -> str:
    """Numeric renal guidance only when reviewed, otherwise the fallback (NFR-011)."""
    if rule.dose_guidance is not None and is_reviewed(rule):
        return rule.dose_guidance
    return RENAL_FALLBACK_GUIDANCE


def shown_alternative_dose(alternative: AllowedAlternative) -> str:
    """The alternative's dose text when reviewed, otherwise the fallback (NFR-011)."""
    if is_reviewed(alternative):
        return f"{alternative.dose_text}, {alternative.route}, {alternative.frequency}"
    return DOSE_FALLBACK_TEXT


# --- Drug list and classes ------------------------------------------------------------------

DRUGS: tuple[Drug, ...] = (
    Drug("dexketoprofen", "Dexketoprofen", "dexketoprofen", "NSAID"),
    Drug("ibuprofen", "Ibuprofen", "ibuprofen", "NSAID"),
    Drug("naproxen", "Naproxen", "naproxen", "NSAID"),
    Drug("diclofenac", "Diclofenac", "diclofenac", "NSAID"),
    Drug("paracetamol", "Paracetamol", "paracetamol", "ANALGESIC_ANTIPYRETIC"),
    Drug("metamizole", "Metamizole", "metamizole", "PYRAZOLONE"),
    Drug("tramadol", "Tramadol", "tramadol", "OPIOID"),
    Drug("morphine", "Morphine", "morphine", "OPIOID"),
    Drug("ciprofloxacin", "Ciprofloxacin", "ciprofloxacin", "FLUOROQUINOLONE"),
    Drug("levofloxacin", "Levofloxacin", "levofloxacin", "FLUOROQUINOLONE"),
    Drug(
        "amoxicillin_clavulanate",
        "Amoxicillin-clavulanate",
        "amoxicillin_clavulanate",
        "PENICILLIN",
    ),
    Drug("aspirin", "Aspirin (acetylsalicylic acid)", "aspirin", "ANTIPLATELET"),
    Drug("clopidogrel", "Clopidogrel", "clopidogrel", "ANTIPLATELET"),
    Drug("enoxaparin", "Enoxaparin", "enoxaparin", "LMWH"),
    Drug("metformin", "Metformin", "metformin", "BIGUANIDE"),
)

DRUG_IDS: tuple[str, ...] = tuple(drug.drug_id for drug in DRUGS)
DRUGS_BY_ID: dict[str, Drug] = {drug.drug_id: drug for drug in DRUGS}
CLASS_IDS: tuple[str, ...] = tuple(dict.fromkeys(drug.drug_class for drug in DRUGS))

# --- Rules ----------------------------------------------------------------------------------

_NSAID_SMPC = f"{CIMA}: Enantyum (dexketoprofen) summary of product characteristics"

ALLERGY_RULE = AllergyRule(
    rule_id="ALLERGY_EXACT_MATCH",
    status=Status.BLOCKED,
    risk_level=RiskLevel.CRITICAL,
    conflict_type=ConflictType.ALLERGY,
    reason="The proposed drug matches a recorded allergy.",
    source=f"{CIMA}: section 4.3 (hypersensitivity to the active substance is a contraindication) "
    "of the SmPC of every drug on the list",
)

CONTEXT_RULES: tuple[ContextRule, ...] = (
    ContextRule(
        rule_id="NSAID_ANTIPLATELET_ACS",
        status=Status.BLOCKED,
        risk_level=RiskLevel.CRITICAL,
        conflict_type=ConflictType.ANTIPLATELET_ACS,
        reason="NSAID with an antiplatelet agent and a coded diagnosis of ACS.",
        source=f"{_NSAID_SMPC}, section 4.5 (NSAIDs with antiplatelet agents: higher bleeding "
        "risk) and section 4.4 (cardiovascular risk); Antman EM et al., Use of nonsteroidal "
        "antiinflammatory drugs: an update for clinicians, AHA scientific statement, "
        "Circulation 2007;115:1634-1642",
        applies_to_class="NSAID",
        diagnosis="ACS",
        chronic_class="ANTIPLATELET",
    ),
    ContextRule(
        rule_id="NSAID_ACTIVE_GI_BLEED",
        status=Status.BLOCKED,
        risk_level=RiskLevel.CRITICAL,
        conflict_type=ConflictType.GI_BLEED,
        reason="NSAID with a coded diagnosis of active gastrointestinal bleeding.",
        source=f"{_NSAID_SMPC}, section 4.3 (active gastrointestinal bleeding or ulceration is "
        "a contraindication); the same contraindication appears in the SmPCs of ibuprofen, "
        "naproxen and diclofenac",
        applies_to_class="NSAID",
        diagnosis="ACTIVE_GI_BLEED",
    ),
)

RENAL_RULES: tuple[RenalRule, ...] = (
    RenalRule(
        rule_id="RENAL_DEXKETOPROFEN_CRCL_60",
        status=Status.BLOCKED,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.RENAL,
        reason="Dexketoprofen and CrCl below 60 mL/min (moderate to severe renal impairment).",
        source=f"{_NSAID_SMPC}, sections 4.2 and 4.3 (contraindicated when creatinine "
        "clearance is 59 mL/min or lower)",
        drug_id="dexketoprofen",
        basis=RenalBasis.CRCL,
        threshold=60,
    ),
    RenalRule(
        rule_id="RENAL_CIPROFLOXACIN_CRCL_30",
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Ciprofloxacin and CrCl below 30 mL/min.",
        source=f"{CIMA}: Ciproxin (ciprofloxacin) SmPC, section 4.2 (dosage in renal "
        "impairment, table by creatinine clearance)",
        drug_id="ciprofloxacin",
        basis=RenalBasis.CRCL,
        threshold=30,
        dose_guidance="CrCl below 30 mL/min: maximum 500 mg a day by mouth, per SmPC 4.2",
    ),
    RenalRule(
        rule_id="RENAL_LEVOFLOXACIN_CRCL_50",
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Levofloxacin and CrCl below 50 mL/min.",
        source=f"{CIMA}: Tavanic (levofloxacin) SmPC, section 4.2 (dosage in renal impairment; "
        "no adjustment at CrCl of 50 mL/min or more)",
        drug_id="levofloxacin",
        basis=RenalBasis.CRCL,
        threshold=50,
    ),
    RenalRule(
        rule_id="RENAL_METFORMIN_EGFR_30",
        status=Status.BLOCKED,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.RENAL,
        reason="Metformin and eGFR below 30 mL/min/1.73 m² (contraindicated).",
        source=f"{CIMA}: metformin SmPC, sections 4.2 and 4.3 (contraindicated when GFR is "
        "below 30 mL/min)",
        drug_id="metformin",
        basis=RenalBasis.EGFR,
        threshold=30,
    ),
    RenalRule(
        rule_id="RENAL_METFORMIN_EGFR_45",
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Metformin and eGFR below 45 mL/min/1.73 m².",
        source=f"{CIMA}: metformin SmPC, section 4.2 (not to be started when GFR is "
        "30-44 mL/min; dose reduction if already taking it)",
        drug_id="metformin",
        basis=RenalBasis.EGFR,
        threshold=45,
    ),
    RenalRule(
        rule_id="RENAL_ENOXAPARIN_CRCL_30",
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Enoxaparin and CrCl below 30 mL/min.",
        source=f"{CIMA}: Clexane (enoxaparin) SmPC, section 4.2 (severe renal impairment, "
        "CrCl 15-30 mL/min: dose adjustment)",
        drug_id="enoxaparin",
        basis=RenalBasis.CRCL,
        threshold=30,
    ),
    RenalRule(
        rule_id="RENAL_TRAMADOL_CRCL_30",
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Tramadol and CrCl below 30 mL/min.",
        source=f"{CIMA}: tramadol SmPC, section 4.2 (renal impairment: longer dosing interval "
        "when CrCl is below 30 mL/min)",
        drug_id="tramadol",
        basis=RenalBasis.CRCL,
        threshold=30,
    ),
    RenalRule(
        rule_id="RENAL_AMOXICILLIN_CLAVULANATE_CRCL_30",
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Amoxicillin-clavulanate and CrCl below 30 mL/min.",
        source=f"{CIMA}: Augmentine (amoxicillin-clavulanate) SmPC, section 4.2 (renal "
        "impairment: adjust dose when CrCl is below 30 mL/min)",
        drug_id="amoxicillin_clavulanate",
        basis=RenalBasis.CRCL,
        threshold=30,
    ),
)

_UNKNOWN_SOURCE = (
    "Project policy, docs/spec/requirements.md AC-001.5 / assumption A-5: a missing lab "
    "for a drug with a renal rule gives at least a warning. This is a design choice, not SmPC "
    "text"
)

RENAL_UNKNOWN_RULES: dict[RenalBasis, RenalUnknownRule] = {
    RenalBasis.EGFR: RenalUnknownRule(
        rule_id="RENAL_UNKNOWN_EGFR",
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Renal function unknown: eGFR is missing for a drug with a renal rule.",
        source=_UNKNOWN_SOURCE,
        basis=RenalBasis.EGFR,
    ),
    RenalBasis.CRCL: RenalUnknownRule(
        rule_id="RENAL_UNKNOWN_CRCL",
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Renal function unknown: creatinine is missing for a drug with a renal rule.",
        source=_UNKNOWN_SOURCE,
        basis=RenalBasis.CRCL,
    ),
}

# --- Allowed alternatives, keyed by (proposed drug, conflict type) ---------------------------

_PARACETAMOL_SOURCE = (
    f"{CIMA}: paracetamol 1 g SmPC, sections 4.1 and 4.2 (adult dose and maximum daily dose); "
    "dose to be confirmed by the specialist"
)


def _paracetamol_for(proposed_drug_id: str, conflict_type: ConflictType) -> AllowedAlternative:
    return AllowedAlternative(
        proposed_drug_id=proposed_drug_id,
        conflict_type=conflict_type,
        drug_id="paracetamol",
        dose_text="1 g",
        route="PO",
        frequency="every 8 hours",
        reason="Analgesic outside the NSAID class.",
        source=_PARACETAMOL_SOURCE,
    )


_NSAID_IDS = tuple(drug.drug_id for drug in DRUGS if drug.drug_class == "NSAID")

ALLOWED_ALTERNATIVES: dict[tuple[str, ConflictType], tuple[AllowedAlternative, ...]] = {
    **{
        (drug_id, conflict_type): (_paracetamol_for(drug_id, conflict_type),)
        for drug_id in _NSAID_IDS
        for conflict_type in (ConflictType.ANTIPLATELET_ACS, ConflictType.GI_BLEED)
    },
    ("dexketoprofen", ConflictType.RENAL): (_paracetamol_for("dexketoprofen", ConflictType.RENAL),),
}

# --- Questions for the clinical specialist (rendered into docs/clinical-review.md) -----------

SPECIALIST_QUESTIONS: tuple[str, ...] = (
    "Citations: confirm each SmPC section and product named in the table. They were written "
    "without access to the live CIMA documents and none links to a specific document.",
    "Drug list: is this the right set of about 15 drugs for the demo (Q-5)? Anything to add "
    "or remove, e.g. a second alternative analgesic?",
    "Renal thresholds: confirm each threshold, its basis (CrCl by Cockcroft-Gault or eGFR) and "
    "its status. In particular dexketoprofen BLOCKED below CrCl 60 (the SmPC says 59 or lower) "
    "and metformin BLOCKED below eGFR 30.",
    "Renal gaps: no renal rule exists for ibuprofen, naproxen, diclofenac, morphine, "
    "metamizole, aspirin, clopidogrel or paracetamol because no threshold was available to "
    "cite. Which of these need one, and at what value?",
    "Cockcroft-Gault uses actual body weight, creatinine in mg/dL, a 0.85 factor for women, "
    "and compares the unrounded value with the threshold (the card shows one decimal). Is "
    "that acceptable, or should obese or "
    "low-weight patients use another weight?",
    "Preset B dose guidance: the ciprofloxacin text 'maximum 500 mg a day by mouth' is hidden "
    "until you sign it off (Q-5). Confirm or correct it, or keep the fallback 'consult SmPC'.",
    "Alternative paracetamol 1 g by mouth every 8 hours (preset A): confirm dose, route and "
    "frequency, or provide the dose to use. Until you sign the dose off, the card offers "
    "paracetamol by name only, with the text 'Dose: consult SmPC' and no number; after your "
    "sign-off it shows the signed-off dose.",
    "Basis and bands: metformin rules use eGFR in mL/min/1.73 m2 where the SmPC says GFR in "
    "mL/min (acceptable?). Should enoxaparin CrCl below 15 be a stricter rule? Should "
    "dexketoprofen CrCl 60-89 (mild impairment, reduced maximum dose) warn? Does the "
    "ciprofloxacin renal table have a further CrCl band (30-60) needing its own rule?",
    "Alternatives: is paracetamol right for every NSAID with ACS or GI bleed and for "
    "dexketoprofen with renal impairment? Should ciprofloxacin with low CrCl (preset B) offer "
    "an alternative? Does the illustrative preset A text read correctly and avoid suggesting "
    "that the tool made the ACS diagnosis?",
    "Where two renal rules on one lab both apply (metformin below 30 and below 45), only the "
    "stricter one is shown. Acceptable?",
    "NSAID with antiplatelet and coded ACS: is BLOCKED / CRITICAL the right verdict, and is "
    "the AHA 2007 statement plus SmPC 4.5 an adequate source? Should a P2Y12 inhibitor or "
    "an anticoagulant also count as an antiplatelet agent (only aspirin and clopidogrel do now)?",
    "NSAID with active GI bleed: is BLOCKED / CRITICAL right? Should aspirin and clopidogrel "
    "(class ANTIPLATELET, not NSAID here) also be flagged with an active GI bleed?",
    "Risk tiers (CRITICAL, HIGH, MODERATE) are the authors' judgment, not from a source. Please "
    "confirm or change them.",
    "Allergy matching is exact (ignoring upper or lower case) on the drug ID or "
    "class ID (NSAID, PENICILLIN, FLUOROQUINOLONE, "
    "OPIOID, PYRAZOLONE, ANTIPLATELET, LMWH, BIGUANIDE, ANALGESIC_ANTIPYRETIC). Spanish brand "
    "or ingredient names ('ibuprofeno', 'Adiro') do not match. Is that acceptable for a demo?",
    "Allergy cross-reactivity is not modelled (an aspirin or penicillin allergy does not flag "
    "NSAIDs or amoxicillin-clavulanate, and 'amoxicillin' does not match the class "
    "PENICILLIN). Which cross-reactions, if any, should the rules cover?",
    "Missing renal lab gives WARNING 'renal function unknown' (design choice A-5, not SmPC). "
    "Is a warning right, or should some drugs (e.g. metformin) be stricter?",
)

RULES_BY_ID: dict[str, RuleEntry] = {
    rule.rule_id: rule
    for rule in (ALLERGY_RULE, *CONTEXT_RULES, *RENAL_RULES, *RENAL_UNKNOWN_RULES.values())
}
