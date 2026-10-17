from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "render_rule_table", ROOT / "scripts" / "render_rule_table.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nfr_011_review_sheet_lists_every_rule_and_preset() -> None:
    text = _load_script().render()

    for rule_id in (
        "ALLERGY_EXACT_MATCH",
        "NSAID_ANTIPLATELET_ACS",
        "NSAID_ACTIVE_GI_BLEED",
        "RENAL_CIPROFLOXACIN_CRCL_30",
        "RENAL_UNKNOWN_CRCL",
    ):
        assert rule_id in text
    for preset in ("Preset A", "Preset B", "Preset C"):
        assert preset in text
    assert "NOT REVIEWED" in text
    assert "Questions for the specialist" in text


def test_nfr_011_review_sheet_hides_unreviewed_doses_on_cards() -> None:
    text = _load_script().render()

    assert "Renal adjustment required — consult SmPC" in text
    assert "Dose: consult SmPC" in text


def test_nfr_011_committed_review_sheet_is_up_to_date() -> None:
    committed = (ROOT / "docs" / "clinical-review.md").read_text(encoding="utf-8")

    assert committed == _load_script().render(), "run: uv run python scripts/render_rule_table.py"
