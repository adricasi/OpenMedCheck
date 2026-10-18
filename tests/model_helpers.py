"""Shared builders for model-layer tests (synthetic data only)."""

from __future__ import annotations

from typing import Any

from openmedcheck.contracts import (
    Labs,
    Order,
    PatientContext,
    RiskLevel,
    RulesVerdict,
    Status,
)
from openmedcheck.model_client import ModelRequest

DRUG_LIST = ("ibuprofen", "paracetamol", "metamizole", "aspirin", "ciprofloxacin")
ALTERNATIVES = ("paracetamol", "metamizole")


def make_request(
    *,
    ed_note: str = "Synthetic note.",
    allowed: tuple[str, ...] = ALTERNATIVES,
    drug_id: str = "ibuprofen",
    **context_overrides: Any,
) -> ModelRequest:
    fields: dict[str, Any] = {"diagnoses": [], "allergies": []}
    fields.update(context_overrides)
    context = PatientContext(
        patient_id="SYN-SECRET-ID",
        age=67,
        sex="M",
        weight_kg=82,
        reason_for_consult="Chest discomfort",
        ed_note=ed_note,
        chronic_medications=["aspirin"],
        labs=Labs(creatinine_mg_dl=1.0, egfr_ml_min_1_73m2=78),
        **fields,
    )
    order = Order(drug_id=drug_id, dose_text="400 mg", route="PO", frequency="every 8 hours")
    verdict = RulesVerdict(status=Status.NO_ISSUE, risk_level=RiskLevel.LOW, fired_rules=[])
    return ModelRequest(
        context=context,
        order=order,
        rules_verdict=verdict,
        allowed_alternatives=allowed,
        drug_list=DRUG_LIST,
    )


def verdict_json(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status": "BLOCKED",
        "risk_level": "HIGH",
        "headline": "NSAID conflicts with suspected ACS",
        "rationale": "The note suggests an acute coronary syndrome. Review before ordering.",
        "renal_adjustment_required": False,
        "conflict_type": "ANTIPLATELET_ACS",
        "alternative_drug_id": "paracetamol",
        # Like the real model (prompt v5): the escalation comes with the note's own words. The
        # rules decide ANTIPLATELET_ACS from this quote (AC-003.7, AC-003.8).
        "note_acs_quote": "Suspected ACS",
    }
    data.update(overrides)
    return data
