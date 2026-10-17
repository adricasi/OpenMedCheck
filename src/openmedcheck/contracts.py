"""Pydantic contracts: request/response shapes and range validation (AC-001.1, AC-001.4)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

MAX_BODY_BYTES = 16 * 1024

IdText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class Status(StrEnum):
    """Verdict status. Strictness order: NO_ISSUE < WARNING < BLOCKED."""

    NO_ISSUE = "NO_ISSUE"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"

    @property
    def rank(self) -> int:
        return _STATUS_ORDER.index(self)


class RiskLevel(StrEnum):
    """Risk tier. Order: LOW < MODERATE < HIGH < CRITICAL."""

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return _RISK_ORDER.index(self)


_STATUS_ORDER = (Status.NO_ISSUE, Status.WARNING, Status.BLOCKED)
_RISK_ORDER = (RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL)


class ConflictType(StrEnum):
    ALLERGY = "ALLERGY"
    RENAL = "RENAL"
    ANTIPLATELET_ACS = "ANTIPLATELET_ACS"
    GI_BLEED = "GI_BLEED"
    OTHER = "OTHER"


class Source(StrEnum):
    RULES = "rules"
    RULES_MODEL = "rules+model"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Labs(_Strict):
    creatinine_mg_dl: float | None = Field(default=None, ge=0.1, le=20)
    egfr_ml_min_1_73m2: float | None = Field(default=None, ge=0, le=200)
    potassium_mmol_l: float | None = Field(default=None, ge=1.5, le=9)
    platelets_per_ul: float | None = Field(default=None, ge=1_000, le=2_000_000)


class PatientContext(_Strict):
    patient_id: IdText
    age: int = Field(ge=18, le=110)
    sex: Literal["M", "F"]
    weight_kg: float = Field(ge=30, le=250)
    reason_for_consult: str = Field(default="", max_length=200)
    ed_note: str = Field(default="", max_length=2_000)
    diagnoses: list[Literal["ACS", "ACTIVE_GI_BLEED"]] = Field(default_factory=list, max_length=10)
    chronic_medications: list[IdText] = Field(default_factory=list, max_length=50)
    allergies: list[IdText] = Field(default_factory=list, max_length=50)
    labs: Labs = Field(default_factory=Labs)

    @field_validator("chronic_medications")
    @classmethod
    def _known_medications(cls, value: list[str]) -> list[str]:
        # Imported here: rule_table imports this module, so a top-level import would cycle.
        from openmedcheck.rule_table import DRUG_IDS

        if any(drug not in DRUG_IDS for drug in value):
            raise ValueError("medication is not in the drug list")
        return value


class Order(_Strict):
    drug_id: str
    dose_text: str = Field(min_length=1, max_length=100)
    route: Literal["PO", "IV", "IM", "SC"]
    frequency: str = Field(min_length=1, max_length=100)

    @field_validator("drug_id")
    @classmethod
    def _known_drug(cls, value: str) -> str:
        # Imported here: rule_table imports this module, so a top-level import would cycle.
        from openmedcheck.rule_table import DRUG_IDS

        if value not in DRUG_IDS:
            raise ValueError("drug is not in the drug list")
        return value


class CheckRequest(_Strict):
    context: PatientContext
    order: Order


class FiredRule(_Strict):
    rule_id: str
    reason: str
    conflict_type: ConflictType


class RulesVerdict(_Strict):
    status: Status
    risk_level: RiskLevel
    fired_rules: list[FiredRule]
    renal_adjustment_required: bool = False
    crcl_ml_min: float | None = None


class ModelVerdict(BaseModel):
    """The model's validated verdict (design § Data model).

    Text limits and content checks (AC-001.2, AC-003.5) are enforced by the model layer
    (``model_client.ModelOutput``), not here: the combiner must hold for any value.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    status: Status
    risk_level: RiskLevel
    headline: str
    rationale: str
    renal_adjustment_required: bool
    conflict_type: ConflictType | None
    alternative_drug_id: str | None


class Alternative(_Strict):
    drug_id: str
    name: str
    dose_text: str
    route: str
    frequency: str
    reason: str


class DecisionCard(_Strict):
    status: Status
    risk_level: RiskLevel
    headline: str
    rationale: str
    fired_rules: list[FiredRule]
    renal_adjustment_required: bool
    crcl_ml_min: float | None
    alternative: Alternative | None
    source: Source
    model_note: str | None
    request_id: str


class FieldError(_Strict):
    field: str
    message: str


class ProblemDetails(_Strict):
    """RFC 9457 problem details; ``errors`` lists field-level validation failures."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    errors: list[FieldError] | None = None
