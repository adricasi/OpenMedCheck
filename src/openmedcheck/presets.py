"""Synthetic template patients A-F (REQ-006). All data is invented; no real patient (AC-006.4).

A, B and C are the predefined rooms (``bed`` set); D, E and F are only offered as templates
when a room is added (AC-006.6, AC-006.7).
"""

from __future__ import annotations

from dataclasses import dataclass

from openmedcheck.contracts import CheckRequest, Labs, Order, PatientContext, Status

SYNTHETIC_LABEL = "Synthetic patient — invented data, not a real person"


@dataclass(frozen=True)
class Preset:
    preset_id: str
    title: str
    bed: str | None
    expected_rules_status: Status
    request: CheckRequest
    synthetic_label: str = SYNTHETIC_LABEL


PRESET_A = Preset(
    preset_id="A",
    title="Suspected ACS in the note only; aspirin at home; dexketoprofen proposed",
    bed="Bed 3",
    expected_rules_status=Status.NO_ISSUE,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-A",
            age=64,
            sex="M",
            weight_kg=82,
            reason_for_consult="Chest pain",
            ed_note=(
                "64-year-old man with a 2-hour history of crushing central chest pain "
                "radiating to the left arm, with diaphoresis. Suspected ACS; ECG and troponin "
                "pending. On daily aspirin."
            ),
            diagnoses=[],
            chronic_medications=["aspirin"],
            allergies=[],
            labs=Labs(creatinine_mg_dl=0.9, egfr_ml_min_1_73m2=92),
        ),
        order=Order(
            drug_id="dexketoprofen", dose_text="25 mg", route="PO", frequency="every 8 hours"
        ),
    ),
)

PRESET_B = Preset(
    preset_id="B",
    title="Reduced renal function; ciprofloxacin proposed",
    bed="Bed 7",
    expected_rules_status=Status.WARNING,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-B",
            age=78,
            sex="F",
            weight_kg=62,
            reason_for_consult="Fever and dysuria",
            ed_note=(
                "78-year-old woman with 2 days of fever and dysuria. Suspected urinary tract "
                "infection. No known allergies."
            ),
            diagnoses=[],
            chronic_medications=[],
            allergies=[],
            labs=Labs(creatinine_mg_dl=2.4, egfr_ml_min_1_73m2=21),
        ),
        order=Order(
            drug_id="ciprofloxacin", dose_text="500 mg", route="PO", frequency="every 12 hours"
        ),
    ),
)

PRESET_C = Preset(
    preset_id="C",
    title="Benign condition, normal renal function, standard analgesic",
    bed="Bed 12",
    expected_rules_status=Status.NO_ISSUE,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-C",
            age=34,
            sex="F",
            weight_kg=68,
            reason_for_consult="Ankle sprain",
            ed_note="34-year-old woman with an ankle sprain after a minor fall. Moderate pain.",
            diagnoses=[],
            chronic_medications=[],
            allergies=[],
            labs=Labs(creatinine_mg_dl=0.8, egfr_ml_min_1_73m2=105),
        ),
        order=Order(drug_id="paracetamol", dose_text="1 g", route="PO", frequency="every 8 hours"),
    ),
)

PRESET_D = Preset(
    preset_id="D",
    title="Coded active GI bleed; ibuprofen proposed",
    bed=None,
    expected_rules_status=Status.BLOCKED,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-D",
            age=58,
            sex="M",
            weight_kg=85,
            reason_for_consult="Melena",
            ed_note=(
                "58-year-old man with two episodes of melena since yesterday and epigastric "
                "pain. Upper GI bleed recorded today; haemoglobin pending. Asks for something "
                "for his back pain."
            ),
            diagnoses=["ACTIVE_GI_BLEED"],
            chronic_medications=[],
            allergies=[],
            labs=Labs(creatinine_mg_dl=1.0, egfr_ml_min_1_73m2=82),
        ),
        order=Order(drug_id="ibuprofen", dose_text="600 mg", route="PO", frequency="every 8 hours"),
    ),
)

PRESET_E = Preset(
    preset_id="E",
    title="Recorded penicillin allergy; amoxicillin-clavulanate proposed",
    bed=None,
    expected_rules_status=Status.BLOCKED,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-E",
            age=45,
            sex="F",
            weight_kg=64,
            reason_for_consult="Cough and fever",
            ed_note=(
                "45-year-old woman with 3 days of productive cough and fever. Suspected "
                "community-acquired pneumonia. Penicillin allergy (rash) in the record."
            ),
            diagnoses=[],
            chronic_medications=[],
            allergies=["penicillin"],
            labs=Labs(creatinine_mg_dl=0.8, egfr_ml_min_1_73m2=95),
        ),
        order=Order(
            drug_id="amoxicillin_clavulanate",
            dose_text="875/125 mg",
            route="PO",
            frequency="every 8 hours",
        ),
    ),
)

PRESET_F = Preset(
    preset_id="F",
    title="Renal colic with reduced kidney function; dexketoprofen proposed",
    bed=None,
    expected_rules_status=Status.BLOCKED,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-F",
            age=72,
            sex="M",
            weight_kg=70,
            reason_for_consult="Right flank pain",
            ed_note=(
                "72-year-old man with sudden right flank pain radiating to the groin, with "
                "nausea. Suspected renal colic."
            ),
            diagnoses=[],
            chronic_medications=[],
            allergies=[],
            labs=Labs(creatinine_mg_dl=1.6, egfr_ml_min_1_73m2=43),
        ),
        order=Order(
            drug_id="dexketoprofen", dose_text="50 mg", route="IV", frequency="every 12 hours"
        ),
    ),
)

PRESETS: dict[str, Preset] = {
    p.preset_id: p for p in (PRESET_A, PRESET_B, PRESET_C, PRESET_D, PRESET_E, PRESET_F)
}

# Illustrative only: the real final card for preset A is written by the model at run time
# (AC-003.4, AC-006.1). Shown to the specialist so the wording and the alternative can be checked.
PRESET_A_EXPECTED_FINAL_CARD: dict[str, str] = {
    "status": "BLOCKED",
    "headline": "NSAID with suspected acute coronary syndrome",
    "rationale": (
        "The note describes suspected ACS and the patient takes an antiplatelet agent; "
        "an NSAID raises bleeding and cardiovascular risk."
    ),
    "alternative": (
        "Paracetamol. Dose: consult SmPC (numeric dose shown only after specialist sign-off)"
    ),
}
