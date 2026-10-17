"""Read-only catalog routes for the UI: drug list and synthetic presets (REQ-006, REQ-007)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from openmedcheck.contracts import CheckRequest
from openmedcheck.presets import PRESETS, Preset
from openmedcheck.rule_table import DRUGS

router = APIRouter(prefix="/api")


class DrugItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    drug_id: str
    name: str
    active_ingredient: str
    drug_class: str = Field(serialization_alias="class")


class PresetItem(BaseModel):
    preset_id: str
    title: str
    synthetic_label: str
    request: CheckRequest


def _preset_item(preset: Preset) -> PresetItem:
    return PresetItem(
        preset_id=preset.preset_id,
        title=preset.title,
        synthetic_label=preset.synthetic_label,
        request=preset.request,
    )


@router.get("/drugs")
async def list_drugs() -> list[dict[str, str]]:
    return [
        DrugItem(
            drug_id=drug.drug_id,
            name=drug.name,
            active_ingredient=drug.active_ingredient,
            drug_class=drug.drug_class,
        ).model_dump(by_alias=True)
        for drug in DRUGS
    ]


@router.get("/presets", response_model=list[PresetItem])
async def list_presets() -> list[PresetItem]:
    return [_preset_item(preset) for preset in PRESETS.values()]


@router.get("/presets/{preset_id}", response_model=PresetItem)
async def get_preset(preset_id: str) -> PresetItem:
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    return _preset_item(preset)
