"""Synthetic presets A, B and C (REQ-006). All data is invented; no real patient (AC-006.4)."""

from __future__ import annotations

from dataclasses import dataclass

from openmedcheck.contracts import CheckRequest, Labs, Order, PatientContext, Status

SYNTHETIC_LABEL = "Synthetic patient — invented data, not a real person"


@dataclass(frozen=True)
class Preset:
    preset_id: str
    title: str
    expected_rules_status: Status
    request: CheckRequest
    synthetic_label: str = SYNTHETIC_LABEL


PRESET_A = Preset(
    preset_id="A",
    title="Suspected ACS in the note only; aspirin at home; dexketoprofen proposed",
    expected_rules_status=Status.NO_ISSUE,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-A",
            age=64,
            sex="M",
            weight_kg=82,
            reason_for_consult="Dolor torácico",
            ed_note=(
                "Varón de 64 años con dolor torácico opresivo de 2 horas, irradiado al brazo "
                "izquierdo, con sudoración. Sospecha de SCA; ECG y troponina pendientes. "
                "Toma Adiro a diario."
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
    expected_rules_status=Status.WARNING,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-B",
            age=78,
            sex="F",
            weight_kg=62,
            reason_for_consult="Fiebre y disuria",
            ed_note=(
                "Mujer de 78 años con fiebre y disuria de 2 días. Sospecha de infección "
                "urinaria. Sin alergias conocidas."
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
    expected_rules_status=Status.NO_ISSUE,
    request=CheckRequest(
        context=PatientContext(
            patient_id="SYN-C",
            age=34,
            sex="F",
            weight_kg=68,
            reason_for_consult="Esguince de tobillo",
            ed_note="Mujer de 34 años con esguince de tobillo tras caída leve. Dolor moderado.",
            diagnoses=[],
            chronic_medications=[],
            allergies=[],
            labs=Labs(creatinine_mg_dl=0.8, egfr_ml_min_1_73m2=105),
        ),
        order=Order(drug_id="paracetamol", dose_text="1 g", route="PO", frequency="every 8 hours"),
    ),
)

PRESETS: dict[str, Preset] = {p.preset_id: p for p in (PRESET_A, PRESET_B, PRESET_C)}

# Illustrative only: the real final card for preset A is written by the model at run time
# (AC-003.4, AC-006.1). Shown to the specialist so the wording and the alternative can be checked.
PRESET_A_EXPECTED_FINAL_CARD: dict[str, str] = {
    "status": "BLOCKED",
    "headline": "NSAID with suspected acute coronary syndrome",
    "rationale": (
        "The note describes suspected ACS and the patient takes an antiplatelet agent; "
        "an NSAID raises bleeding and cardiovascular risk."
    ),
    "alternative": "Paracetamol, offered once its dose is signed off by the specialist",
}
