"""Synthetic template patients A-L (REQ-006). All data is invented; no real patient (AC-006.4).

A, B, C and L are the predefined rooms (``bed`` set); D to K are only offered as templates when
a room is added (AC-006.6, AC-006.7). G, H and I show the conflict breadth of T-014; in I the
pregnancy is only in the note, so the rules alone say NO_ISSUE and the model's quote decides. J
and K carry a coded past medical history; in L the past GI bleed is one item of a long history
in the note, so again only the model's quote reveals it (REQ-016, AC-016.6).
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

PRESET_G = Preset(
    preset_id="G",
    title="Atrial fibrillation on warfarin; ibuprofen proposed",
    bed=None,
    expected_rules_status=Status.BLOCKED,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-G",
            age=76,
            sex="M",
            weight_kg=79,
            reason_for_consult="Knee pain after a fall",
            ed_note=(
                "76-year-old man with left knee pain after a fall at home. Atrial fibrillation "
                "on long-term anticoagulation. No head injury."
            ),
            diagnoses=[],
            chronic_medications=["warfarin"],
            allergies=[],
            labs=Labs(creatinine_mg_dl=1.0, egfr_ml_min_1_73m2=72, platelets_per_ul=210_000),
        ),
        order=Order(drug_id="ibuprofen", dose_text="600 mg", route="PO", frequency="every 8 hours"),
    ),
)

PRESET_H = Preset(
    preset_id="H",
    title="Hypertension with high potassium; enalapril proposed",
    bed=None,
    expected_rules_status=Status.BLOCKED,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-H",
            age=68,
            sex="F",
            weight_kg=71,
            reason_for_consult="High blood pressure reading",
            ed_note=(
                "68-year-old woman referred for a blood pressure of 182/104 mmHg, no chest pain or "
                "neurological symptoms. Potassium 5.8 mmol/L on today's labs."
            ),
            diagnoses=[],
            chronic_medications=[],
            allergies=[],
            labs=Labs(creatinine_mg_dl=1.1, egfr_ml_min_1_73m2=55, potassium_mmol_l=5.8),
        ),
        order=Order(drug_id="enalapril", dose_text="5 mg", route="PO", frequency="once daily"),
    ),
)

PRESET_I = Preset(
    preset_id="I",
    title="Pregnancy stated only in the note; ibuprofen proposed",
    bed=None,
    expected_rules_status=Status.NO_ISSUE,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-I",
            age=31,
            sex="F",
            weight_kg=70,
            reason_for_consult="Low back pain",
            ed_note=(
                "31-year-old woman with low back pain since yesterday, no trauma, no red flags. "
                "She is 30 weeks pregnant."
            ),
            diagnoses=[],
            chronic_medications=[],
            allergies=[],
            labs=Labs(creatinine_mg_dl=0.6, egfr_ml_min_1_73m2=118),
        ),
        order=Order(drug_id="ibuprofen", dose_text="400 mg", route="PO", frequency="every 8 hours"),
    ),
)

PRESET_J = Preset(
    preset_id="J",
    title="Previous GI bleed in the past medical history; ibuprofen proposed",
    bed=None,
    expected_rules_status=Status.WARNING,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-J",
            age=61,
            sex="F",
            weight_kg=70,
            reason_for_consult="Low back pain",
            ed_note=(
                "61-year-old woman with low back pain after lifting a box yesterday. No "
                "neurological signs. Haemodynamically stable."
            ),
            diagnoses=[],
            history=["PAST_GI_BLEED"],
            chronic_medications=[],
            allergies=[],
            labs=Labs(creatinine_mg_dl=0.8, egfr_ml_min_1_73m2=79),
        ),
        order=Order(drug_id="ibuprofen", dose_text="600 mg", route="PO", frequency="every 8 hours"),
    ),
)

PRESET_K = Preset(
    preset_id="K",
    title="Ischaemic heart disease in the past medical history; ibuprofen proposed",
    bed=None,
    expected_rules_status=Status.WARNING,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-K",
            age=67,
            sex="M",
            weight_kg=84,
            reason_for_consult="Knee pain",
            ed_note=(
                "67-year-old man with right knee pain and swelling after a fall at home. No chest "
                "pain today. Walks with pain."
            ),
            diagnoses=[],
            history=["ISCHAEMIC_HEART_DISEASE"],
            chronic_medications=["aspirin"],
            allergies=[],
            labs=Labs(creatinine_mg_dl=1.0, egfr_ml_min_1_73m2=77),
        ),
        order=Order(drug_id="ibuprofen", dose_text="400 mg", route="PO", frequency="every 8 hours"),
    ),
)

PRESET_L = Preset(
    preset_id="L",
    title="Routine wrist sprain; a past GI bleed buried in a long history in the note; ibuprofen "
    "proposed",
    bed="Bed 15",
    expected_rules_status=Status.NO_ISSUE,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-L",
            age=66,
            sex="M",
            weight_kg=81,
            reason_for_consult="Wrist pain after a fall",
            ed_note=(
                "66-year-old man who fell off his bicycle this morning onto an outstretched right "
                "hand. Wrist swollen and tender over the radial side; X-ray shows no fracture. "
                "Alert, haemodynamically stable, pain 7/10, asking for something stronger than "
                "paracetamol. Past medical history: hypertension, type 2 diabetes, "
                "hypercholesterolaemia, gout, knee arthroscopy in 2015, appendicectomy as a child, "
                "upper GI bleed from a duodenal ulcer in 2021 treated endoscopically, cataract "
                "surgery in 2023. Ex-smoker, lives with his wife, retired bus driver."
            ),
            diagnoses=[],
            history=[],
            chronic_medications=["enalapril", "metformin"],
            allergies=[],
            labs=Labs(
                creatinine_mg_dl=0.9,
                egfr_ml_min_1_73m2=86,
                potassium_mmol_l=4.3,
                platelets_per_ul=245_000,
            ),
        ),
        order=Order(drug_id="ibuprofen", dose_text="600 mg", route="PO", frequency="every 8 hours"),
    ),
)

PRESETS: dict[str, Preset] = {
    p.preset_id: p
    for p in (
        PRESET_A,
        PRESET_B,
        PRESET_C,
        PRESET_D,
        PRESET_E,
        PRESET_F,
        PRESET_G,
        PRESET_H,
        PRESET_I,
        PRESET_J,
        PRESET_K,
        PRESET_L,
    )
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
    "alternative": "Paracetamol 1 g, PO, every 8 hours (dose specialist-reviewed, T-006)",
}
