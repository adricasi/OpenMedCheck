"""The rule table: drug list, classes, rules and allowed alternatives (REQ-002, NFR-011).

Pure data, no I/O. Every entry carries a source citation and a conflict type; a reviewed entry
also carries a specialist-review mark (``reviewed_by`` / ``reviewed_on``). The T-006 entries
were reviewed by a clinical specialist on 2026-10-18; an entry added later (the past-history
rules of REQ-016) stays unreviewed, and its numeric doses hidden, until the specialist signs it
off.

The citations name the active ingredient and section of the summary of product characteristics
(SmPC) as published by the Spanish Agency of Medicines and Medical Devices in its online drug
information centre (AEMPS CIMA, https://cima.aemps.es), or a published guideline. Rules marked as
project policy are design choices, not SmPC text. The review sheet (``docs/clinical-review.md``)
records the review outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from openmedcheck.contracts import ConflictType, RiskLevel, Status

RENAL_FALLBACK_GUIDANCE = "Renal adjustment required — consult SmPC"
DOSE_FALLBACK_TEXT = "Dose: consult SmPC"

# T-006: the specialist review of the whole table. The reviewer's name is not recorded.
SPECIALIST_REVIEWER = "Clinical specialist (name not recorded)"
SPECIALIST_REVIEW_DATE = date(2026, 10, 18)

CIMA = "AEMPS CIMA, Spanish Agency of Medicines drug information centre (https://cima.aemps.es)"
ESC_HF_2021 = (
    "McDonagh TA et al., 2021 ESC Guidelines for the diagnosis and treatment of acute and "
    "chronic heart failure, Eur Heart J 2021;42:3599-3726"
)
ISTH_PLATELETS = (
    "Samuelson Bannow BT et al., Management of anticoagulation for cancer-associated thrombosis "
    "in patients with thrombocytopenia: guidance from the ISTH SSC, J Thromb Haemost "
    "2018;16:1246-1249"
)


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
    """Class conflict given a coded diagnosis, past history and/or a home medication class.

    ``diagnosis`` set: requires that coded diagnosis (AC-002.3, AC-002.4, AC-002.11, AC-002.13).
    ``history`` set: requires that past-history code (AC-016.2).
    ``chronic_class`` set: also requires a chronic medication of that class (AC-002.9).
    """

    applies_to_class: str = ""
    diagnosis: str | None = None
    history: str | None = None
    chronic_class: str | None = None


@dataclass(frozen=True)
class RenalRule(RuleEntry):
    """Fires when the renal measure is strictly below ``threshold`` (AC-002.2)."""

    drug_id: str = ""
    basis: RenalBasis = RenalBasis.CRCL
    threshold: float = 0.0
    # Numeric adjustment taken from the SmPC; shown only once reviewed (NFR-011, Q-5).
    dose_guidance: str | None = None


class LabComparison(StrEnum):
    """Direction of a lab threshold: the rule fires strictly beyond it."""

    ABOVE = "ABOVE"
    BELOW = "BELOW"


@dataclass(frozen=True)
class LabRule(RuleEntry):
    """Fires when a lab is strictly beyond ``threshold`` for a drug class (AC-002.10, AC-002.12).

    Rules on the same lab and classes overlap (warning and block thresholds): only the strictest
    one that fires is shown.
    """

    applies_to_classes: tuple[str, ...] = ()
    lab: str = ""  # a field of contracts.Labs
    comparison: LabComparison = LabComparison.ABOVE
    threshold: float = 0.0


@dataclass(frozen=True)
class LabUnknownRule(RuleEntry):
    """Fires when the lab a drug class needs is missing (AC-002.10)."""

    applies_to_classes: tuple[str, ...] = ()
    lab: str = ""


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
    Drug("acenocoumarol", "Acenocoumarol", "acenocoumarol", "ANTICOAGULANT"),
    Drug("warfarin", "Warfarin", "warfarin", "ANTICOAGULANT"),
    Drug("enalapril", "Enalapril", "enalapril", "ACE_INHIBITOR"),
    Drug("ramipril", "Ramipril", "ramipril", "ACE_INHIBITOR"),
    Drug("spironolactone", "Spironolactone", "spironolactone", "POTASSIUM_SPARING"),
)

DRUG_IDS: tuple[str, ...] = tuple(drug.drug_id for drug in DRUGS)
DRUGS_BY_ID: dict[str, Drug] = {drug.drug_id: drug for drug in DRUGS}
CLASS_IDS: tuple[str, ...] = tuple(dict.fromkeys(drug.drug_class for drug in DRUGS))

# --- Rules ----------------------------------------------------------------------------------

_NSAID_SMPC = f"{CIMA}: dexketoprofen SmPC"

ALLERGY_RULE = AllergyRule(
    rule_id="ALLERGY_EXACT_MATCH",
    reviewed_by=SPECIALIST_REVIEWER,
    reviewed_on=SPECIALIST_REVIEW_DATE,
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
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.BLOCKED,
        risk_level=RiskLevel.CRITICAL,
        conflict_type=ConflictType.ANTIPLATELET_ACS,
        reason="NSAID with an antiplatelet agent and ACS recorded or suspected by the clinician.",
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
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.BLOCKED,
        risk_level=RiskLevel.CRITICAL,
        conflict_type=ConflictType.GI_BLEED,
        reason="NSAID with active gastrointestinal bleeding recorded by the clinician.",
        source=f"{_NSAID_SMPC}, section 4.3 (active gastrointestinal bleeding or ulceration is "
        "a contraindication); the same contraindication appears in the SmPCs of ibuprofen, "
        "naproxen and diclofenac",
        applies_to_class="NSAID",
        diagnosis="ACTIVE_GI_BLEED",
    ),
    ContextRule(
        rule_id="NSAID_ORAL_ANTICOAGULANT",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.BLOCKED,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.BLEEDING,
        reason="NSAID with an oral anticoagulant (acenocoumarol or warfarin): bleeding risk.",
        source=f"{CIMA}: acenocoumarol and warfarin SmPCs, section 4.5 (NSAIDs increase the "
        "anticoagulant effect and the bleeding risk), and the dexketoprofen SmPC, section 4.5",
        applies_to_class="NSAID",
        chronic_class="ANTICOAGULANT",
    ),
    ContextRule(
        rule_id="NSAID_HEART_FAILURE",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.HEART_FAILURE,
        reason="NSAID with heart failure recorded or suspected by the clinician.",
        source=f"{_NSAID_SMPC}, section 4.3 (contraindicated in severe heart failure) and "
        f"section 4.4; {ESC_HF_2021} (NSAIDs are not recommended in heart failure)",
        applies_to_class="NSAID",
        diagnosis="HEART_FAILURE",
    ),
    ContextRule(
        rule_id="PREGNANCY_ACE_INHIBITOR",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.BLOCKED,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.PREGNANCY,
        reason="ACE inhibitor in pregnancy recorded or stated by the clinician.",
        source=f"{CIMA}: enalapril and ramipril SmPCs, sections 4.3 and 4.6 (contraindicated in "
        "the second and third trimesters; not recommended in the first)",
        applies_to_class="ACE_INHIBITOR",
        diagnosis="PREGNANCY",
    ),
    ContextRule(
        rule_id="PREGNANCY_ORAL_ANTICOAGULANT",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.BLOCKED,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.PREGNANCY,
        reason="Oral anticoagulant in pregnancy recorded or stated by the clinician.",
        source=f"{CIMA}: acenocoumarol and warfarin SmPCs, sections 4.3 and 4.6 "
        "(contraindicated in pregnancy)",
        applies_to_class="ANTICOAGULANT",
        diagnosis="PREGNANCY",
    ),
    ContextRule(
        rule_id="PREGNANCY_NSAID",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.PREGNANCY,
        reason="NSAID in pregnancy recorded or stated by the clinician; this rule does not use "
        "gestational age.",
        source=f"{_NSAID_SMPC}, sections 4.3 and 4.6 (contraindicated in the third trimester; "
        "to be avoided in the first and second unless clearly necessary)",
        applies_to_class="NSAID",
        diagnosis="PREGNANCY",
    ),
    # Past medical history (REQ-016, ADR 0009). Not reviewed yet: no review mark until the
    # specialist confirms them (AC-016.3, NFR-011). WARNING because labels differ on how far the
    # contraindication goes; whether either should be BLOCKED is a specialist question.
    ContextRule(
        rule_id="NSAID_HISTORY_GI_BLEED",
        status=Status.WARNING,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.PAST_GI_BLEED,
        reason="NSAID with a recorded history of gastrointestinal bleeding, peptic ulcer or "
        "perforation.",
        source=f"{CIMA}: ibuprofen SmPC, section 4.3 (history of gastrointestinal bleeding or "
        "perforation related to previous NSAID therapy, and active or history of recurrent peptic "
        "ulcer or haemorrhage, are contraindications) and section 4.4 (higher risk with a history "
        f"of ulcer); {_NSAID_SMPC}, sections 4.3 and 4.4 (the wording on past bleeding, ulcer and "
        "perforation differs between labels; not yet checked against a live label)",
        applies_to_class="NSAID",
        history="PAST_GI_BLEED",
    ),
    ContextRule(
        rule_id="NSAID_HISTORY_ISCHAEMIC_HEART_DISEASE",
        status=Status.WARNING,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.ISCHAEMIC_HEART_DISEASE,
        reason="NSAID with a recorded history of ischaemic heart disease (previous ACS or "
        "infarction, coronary stent or angina).",
        source=f"{_NSAID_SMPC}, section 4.4 (cardiovascular thrombotic risk); European Medicines "
        "Agency, diclofenac-containing medicines referral, 2013 (diclofenac contraindicated in "
        "established ischaemic heart disease); Antman EM et al., Use of nonsteroidal "
        "antiinflammatory drugs: an update for clinicians, AHA scientific statement, Circulation "
        "2007;115:1634-1642",
        applies_to_class="NSAID",
        history="ISCHAEMIC_HEART_DISEASE",
    ),
)

_RAAS_CLASSES = ("ACE_INHIBITOR", "POTASSIUM_SPARING")
_PLATELET_POLICY = (
    "Project policy aligned with the anticoagulation threshold in "
    f"{ISTH_PLATELETS}; {_NSAID_SMPC}, section 4.4 (caution in bleeding disorders). The NSAID "
    "threshold is a design choice, not SmPC text"
)

LAB_RULES: tuple[LabRule, ...] = (
    LabRule(
        rule_id="POTASSIUM_RAAS_ABOVE_5_5",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.BLOCKED,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.HYPERKALAEMIA,
        reason="ACE inhibitor or potassium-sparing drug with potassium above 5.5 mmol/L.",
        source=f"{ESC_HF_2021} (potassium above 5.5 mmol/L: reduce or stop); {CIMA}: enalapril, "
        "ramipril and spironolactone SmPCs, sections 4.3 to 4.5 (hyperkalaemia). Applied "
        "outside heart failure by project policy",
        applies_to_classes=_RAAS_CLASSES,
        lab="potassium_mmol_l",
        comparison=LabComparison.ABOVE,
        threshold=5.5,
    ),
    LabRule(
        rule_id="POTASSIUM_RAAS_ABOVE_5_0",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.HYPERKALAEMIA,
        reason="ACE inhibitor or potassium-sparing drug with potassium above 5.0 mmol/L.",
        source=f"{ESC_HF_2021} (start only with potassium of 5.0 mmol/L or less); {CIMA}: "
        "enalapril, ramipril and spironolactone SmPCs, section 4.4 (monitor potassium). Applied "
        "outside heart failure by project policy",
        applies_to_classes=_RAAS_CLASSES,
        lab="potassium_mmol_l",
        comparison=LabComparison.ABOVE,
        threshold=5.0,
    ),
    LabRule(
        rule_id="PLATELETS_ANTICOAGULANT_BELOW_50000",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.BLOCKED,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.BLEEDING,
        reason="Anticoagulant with platelets below 50,000 per µL.",
        source=f"{ISTH_PLATELETS} (full-dose anticoagulation with platelets of 50,000 per µL "
        f"or more); {CIMA}: enoxaparin, acenocoumarol and warfarin SmPCs, section 4.4. Applied "
        "to every anticoagulant order regardless of dose or indication by project policy",
        applies_to_classes=("ANTICOAGULANT", "LMWH"),
        lab="platelets_per_ul",
        comparison=LabComparison.BELOW,
        threshold=50_000,
    ),
    LabRule(
        rule_id="PLATELETS_NSAID_BELOW_50000",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.HIGH,
        conflict_type=ConflictType.BLEEDING,
        reason="NSAID with platelets below 50,000 per µL.",
        source=_PLATELET_POLICY,
        applies_to_classes=("NSAID",),
        lab="platelets_per_ul",
        comparison=LabComparison.BELOW,
        threshold=50_000,
    ),
)

LAB_UNKNOWN_RULES: tuple[LabUnknownRule, ...] = (
    LabUnknownRule(
        rule_id="POTASSIUM_UNKNOWN_RAAS",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.HYPERKALAEMIA,
        reason="Potassium unknown: missing for an ACE inhibitor or potassium-sparing drug.",
        source="Project policy, like AC-001.5 for renal labs: a missing potassium for these "
        "drugs gives a warning. This is a design choice, not SmPC text",
        applies_to_classes=_RAAS_CLASSES,
        lab="potassium_mmol_l",
    ),
)

RENAL_RULES: tuple[RenalRule, ...] = (
    RenalRule(
        rule_id="RENAL_DEXKETOPROFEN_CRCL_60",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
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
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Ciprofloxacin and CrCl below 30 mL/min.",
        source=f"{CIMA}: ciprofloxacin SmPC, section 4.2 (dosage in renal "
        "impairment, table by creatinine clearance)",
        drug_id="ciprofloxacin",
        basis=RenalBasis.CRCL,
        threshold=30,
        # Q-5 (specialist review, 2026-10-18): the card keeps "consult SmPC", no numeric dose.
    ),
    RenalRule(
        rule_id="RENAL_LEVOFLOXACIN_CRCL_50",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Levofloxacin and CrCl below 50 mL/min.",
        source=f"{CIMA}: levofloxacin SmPC, section 4.2 (dosage in renal impairment; "
        "no adjustment at CrCl of 50 mL/min or more)",
        drug_id="levofloxacin",
        basis=RenalBasis.CRCL,
        threshold=50,
    ),
    RenalRule(
        rule_id="RENAL_METFORMIN_EGFR_30",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
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
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
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
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Enoxaparin and CrCl below 30 mL/min.",
        source=f"{CIMA}: enoxaparin SmPC, section 4.2 (severe renal impairment, "
        "CrCl 15-30 mL/min: dose adjustment)",
        drug_id="enoxaparin",
        basis=RenalBasis.CRCL,
        threshold=30,
    ),
    RenalRule(
        rule_id="RENAL_TRAMADOL_CRCL_30",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
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
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Amoxicillin-clavulanate and CrCl below 30 mL/min.",
        source=f"{CIMA}: amoxicillin-clavulanate SmPC, section 4.2 (renal "
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
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
        status=Status.WARNING,
        risk_level=RiskLevel.MODERATE,
        conflict_type=ConflictType.RENAL,
        reason="Renal function unknown: eGFR is missing for a drug with a renal rule.",
        source=_UNKNOWN_SOURCE,
        basis=RenalBasis.EGFR,
    ),
    RenalBasis.CRCL: RenalUnknownRule(
        rule_id="RENAL_UNKNOWN_CRCL",
        reviewed_by=SPECIALIST_REVIEWER,
        reviewed_on=SPECIALIST_REVIEW_DATE,
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
    f"{CIMA}: paracetamol 1 g SmPC, sections 4.1 and 4.2 (adult dose and maximum daily dose)"
)


def _paracetamol_for(
    proposed_drug_id: str, conflict_type: ConflictType, *, reviewed: bool = True
) -> AllowedAlternative:
    """Paracetamol 1 g every 8 hours; ``reviewed`` only where the specialist confirmed it."""
    return AllowedAlternative(
        proposed_drug_id=proposed_drug_id,
        conflict_type=conflict_type,
        drug_id="paracetamol",
        dose_text="1 g",
        route="PO",
        frequency="every 8 hours",
        reason="Analgesic outside the NSAID class.",
        source=_PARACETAMOL_SOURCE,
        reviewed_by=SPECIALIST_REVIEWER if reviewed else None,
        reviewed_on=SPECIALIST_REVIEW_DATE if reviewed else None,
    )


_NSAID_IDS = tuple(drug.drug_id for drug in DRUGS if drug.drug_class == "NSAID")

ALLOWED_ALTERNATIVES: dict[tuple[str, ConflictType], tuple[AllowedAlternative, ...]] = {
    **{
        (drug_id, conflict_type): (_paracetamol_for(drug_id, conflict_type),)
        for drug_id in _NSAID_IDS
        for conflict_type in (
            ConflictType.ANTIPLATELET_ACS,
            ConflictType.GI_BLEED,
            ConflictType.BLEEDING,
            ConflictType.HEART_FAILURE,
            ConflictType.PREGNANCY,
        )
    },
    ("dexketoprofen", ConflictType.RENAL): (_paracetamol_for("dexketoprofen", ConflictType.RENAL),),
    # Past medical history (REQ-016): not reviewed for these rules, so the card shows the drug
    # with "Dose: consult SmPC" until the specialist confirms the dose (NFR-011).
    **{
        (drug_id, conflict_type): (_paracetamol_for(drug_id, conflict_type, reviewed=False),)
        for drug_id in _NSAID_IDS
        for conflict_type in (ConflictType.PAST_GI_BLEED, ConflictType.ISCHAEMIC_HEART_DISEASE)
    },
}

# --- Questions for the clinical specialist (rendered into docs/clinical-review.md) -----------

SPECIALIST_QUESTIONS: tuple[str, ...] = (
    "Raised by the source check after your review (not applied; the reviewed text stands until "
    "you confirm): (a) RENAL_METFORMIN_EGFR_45: the EMA 2016 text sets a maximum of 1000 mg a "
    "day at GFR 30-44 rather than 'not to be started'; change the source text? (b) "
    "PREGNANCY_NSAID: add the MHRA 2023 / FDA 2020 advice to avoid NSAIDs from week 20 as a "
    "separate source? (c) RENAL_CIPROFLOXACIN_CRCL_30 fires below 30 while the SmPC band is "
    "30 or lower: keep, or flag at 30 too?",
    "Citations: confirm each SmPC section and product named in the table. They were written "
    "without access to the live CIMA documents and none links to a specific document.",
    "Drug list: is this the right set of 20 drugs for the demo? Anything to add "
    "or remove, e.g. a second alternative analgesic?",
    "Renal thresholds: confirm each threshold, its basis (CrCl by Cockcroft-Gault or eGFR) and "
    "its status. In particular dexketoprofen BLOCKED below CrCl 60 (the SmPC says 59 or lower) "
    "and metformin BLOCKED below eGFR 30.",
    "Renal gaps: no renal rule exists for ibuprofen, naproxen, diclofenac, morphine, "
    "metamizole, aspirin, clopidogrel, paracetamol, enalapril, ramipril, spironolactone, "
    "warfarin or acenocoumarol because no threshold was available to "
    "cite. Which of these need one, and at what value?",
    "Cockcroft-Gault uses actual body weight, creatinine in mg/dL, a 0.85 factor for women, "
    "and compares the unrounded value with the threshold (the card shows one decimal). Is "
    "that acceptable, or should obese or "
    "low-weight patients use another weight?",
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
    "another P2Y12 inhibitor also count as an antiplatelet agent (only aspirin and clopidogrel "
    "do now; oral anticoagulants are covered by NSAID_ORAL_ANTICOAGULANT)?",
    "NSAID with active GI bleed: is BLOCKED / CRITICAL right? Should aspirin and clopidogrel "
    "(class ANTIPLATELET, not NSAID here) also be flagged with an active GI bleed?",
    "Risk tiers (CRITICAL, HIGH, MODERATE) are the authors' judgment, not from a source. Please "
    "confirm or change them.",
    "Allergy matching is exact (ignoring upper or lower case) on the drug ID, the active "
    "ingredient or the class ID (NSAID, PENICILLIN, FLUOROQUINOLONE, "
    "OPIOID, PYRAZOLONE, ANTIPLATELET, LMWH, BIGUANIDE, ANALGESIC_ANTIPYRETIC, ANTICOAGULANT, "
    "ACE_INHIBITOR, POTASSIUM_SPARING). Brand names "
    "or ingredient names in another language do not match (the drug list uses English generic "
    "names only). Is that acceptable for a demo?",
    "Allergy cross-reactivity is not modelled: an aspirin allergy does not flag NSAIDs, and "
    "'amoxicillin' alone does not match (only the drug ID, the active ingredient or the class "
    "PENICILLIN does). Which cross-reactions, if any, should the rules cover?",
    "Template D (coded active GI bleed, ibuprofen): the record has a coded active GI bleed and "
    "the note says it was recorded today. Is that a realistic case, and is paracetamol the right "
    "alternative?",
    "Template E (penicillin allergy, amoxicillin-clavulanate for suspected pneumonia): should a "
    "recorded penicillin allergy offer an alternative (for example levofloxacin, on the drug "
    "list)? At the moment there is none.",
    "Template F (72 M, 70 kg, creatinine 1.6 mg/dL, Cockcroft-Gault CrCl 41 mL/min, eGFR 43; "
    "renal colic, dexketoprofen): is BLOCKED right, and is paracetamol the right alternative, "
    "or should another analgesic on the list (for example metamizole) be offered? Should age "
    "65 or over add its own dexketoprofen warning?",
    "Demo order text (test input, not recommendations): ibuprofen 600 mg PO every 8 hours (D), "
    "amoxicillin-clavulanate 875/125 mg PO every 8 hours (E), dexketoprofen 50 mg IV every 12 "
    "hours (F), ibuprofen 600 mg PO every 8 hours (G), enalapril 5 mg PO once daily (H), "
    "ibuprofen 400 mg PO every 8 hours (I and the custom-patient sample). Do any read as "
    "implausible for an ED order?",
    "Note findings (ADR 0006): should a suspected ACS taken from the clinician's note give the "
    "same BLOCKED / CRITICAL as a coded ACS, or WARNING?",
    "Note findings: should 'suspected' or 'recent' GI bleeding written in the note count as "
    "active bleeding for NSAID_ACTIVE_GI_BLEED?",
    "Note findings: is a note saying the patient takes a drug (for example 'On daily aspirin') "
    "enough to treat it as a home medicine for the rules?",
    "Note findings: should an allergy written only in the note (template E without the coded "
    "allergy) block the order the same way as a recorded allergy?",
    "Card display: a verbatim note quote (which may contain dose text or other drug names) is "
    "shown under a fired rule, labelled as the clinician's words. Is that acceptable?",
    "Preset A card: does 'From the clinician's note: “Suspected ACS”' read as the clinician's "
    "statement and not as a system diagnosis?",
    "T-014 NSAID_ORAL_ANTICOAGULANT: is BLOCKED / HIGH right for any NSAID with acenocoumarol or "
    "warfarin, or should a short course be WARNING? Should DOACs be added to the list?",
    "T-014 potassium: are 5.0 mmol/L (WARNING) and 5.5 mmol/L (BLOCKED) the right thresholds for "
    "starting an ACE inhibitor or spironolactone in the ED, and is a WARNING right when potassium "
    "is missing?",
    "T-014 NSAID_HEART_FAILURE: WARNING / HIGH because severity is unknown; should it be BLOCKED "
    "when heart failure is coded?",
    "T-014 platelets: the anticoagulant threshold of 50,000 per µL follows the ISTH guidance for "
    "cancer-associated thrombosis; the NSAID threshold is project policy. Please confirm or "
    "change both.",
    "T-014 pregnancy: ACE inhibitors and oral anticoagulants BLOCKED, NSAIDs WARNING / HIGH "
    "because the trimester is not recorded. Should the record carry gestational age so the "
    "NSAID rule can block from 20 weeks?",
    "T-014 alternatives: paracetamol is offered for NSAIDs under BLEEDING, HEART_FAILURE and "
    "PREGNANCY. With acenocoumarol or warfarin, regular paracetamol can raise the INR (SmPC "
    "4.5). Should the card add a monitoring note, or should no alternative be offered there?",
    "Missing renal lab gives WARNING 'renal function unknown' (design choice A-5, not SmPC). "
    "Is a warning right, or should some drugs (e.g. metformin) be stricter?",
    "Past medical history (REQ-016, added after your review, not reviewed yet): (a) "
    "NSAID_HISTORY_GI_BLEED is a WARNING for any recorded history of GI bleeding, ulcer or "
    "perforation. Ibuprofen labels contraindicate a history related to previous NSAID therapy "
    "or recurrent ulcer/haemorrhage; dexketoprofen label wording differs and was not checked. "
    "Should it be BLOCKED, and should the record distinguish NSAID-related or recurrent events? "
    "(b) NSAID_HISTORY_ISCHAEMIC_HEART_DISEASE is a WARNING for every NSAID; EMA contraindicates "
    "diclofenac in established ischaemic heart disease. Should diclofenac be BLOCKED? (c) Past "
    "history read from the note counts only when the model quotes it word for word and the "
    "quote names the event (for example 'GI bleed', 'peptic ulcer', 'MI', 'stent', 'angina'); "
    "it is dropped when the sentence denies it ('no', 'never', 'denies') or names a relative "
    "('father', 'mother', 'family history'). Acceptable, and which cues are missing?",
    "Preset L (Bed 5, added after your review): (a) is a WARNING right for one endoscopically "
    "treated duodenal-ulcer bleed in 2021 (the ibuprofen SmPC names recurrent ulcer or "
    "haemorrhage), and should the card mention gastroprotection? (b) ibuprofen 600 mg every 8 "
    "hours with enalapril in a 66-year-old with diabetes: does NSAID with an ACE inhibitor need "
    "its own rule? (c) the patient found paracetamol not enough; is paracetamol still the right "
    "alternative to offer? (d) acute events (ACS, active GI bleed) in a 'PMH:' or 'Background:' "
    "list are not read as current; chronic conditions and pregnancy are. Agree?",
)

RULES_BY_ID: dict[str, RuleEntry] = {
    rule.rule_id: rule
    for rule in (
        ALLERGY_RULE,
        *CONTEXT_RULES,
        *RENAL_RULES,
        *RENAL_UNKNOWN_RULES.values(),
        *LAB_RULES,
        *LAB_UNKNOWN_RULES,
    )
}
