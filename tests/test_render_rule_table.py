from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from openmedcheck import rule_table

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
    # T-006 signed off the 2026-10-18 table; the history rules (AC-016.3) came later.
    assert (
        "**Status: NOT FULLY REVIEWED.** Clinical specialist (name not recorded) confirmed 44 of "
        "54 rules and alternatives on 2026-10-18" in text
    )
    assert (
        "Awaiting sign-off: NSAID_HISTORY_GI_BLEED, NSAID_HISTORY_ISCHAEMIC_HEART_DISEASE, "
        "dexketoprofen / PAST_GI_BLEED → paracetamol" in text
    )
    # The specialist sees what triggers a history rule and which presets carry history.
    assert "Past medical history PAST_GI_BLEED (recorded or a quoted note finding)" in text
    assert "Past medical history (free text): Hypertension. Hypercholesterolaemia." in text
    assert "## Source check (2026-10-18)" in text
    assert "Questions for the specialist" in text


def test_nfr_011_review_sheet_flags_an_unreviewed_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script()
    rule_id = "NSAID_HEART_FAILURE"
    unsigned = replace(rule_table.RULES_BY_ID[rule_id], reviewed_by=None, reviewed_on=None)
    monkeypatch.setitem(rule_table.RULES_BY_ID, rule_id, unsigned)

    text = module.render()

    assert "**Status: NOT FULLY REVIEWED.**" in text
    assert "Reviewer name and role: ____" in text


def test_nfr_011_review_sheet_hides_unreviewed_doses_on_cards() -> None:
    text = _load_script().render()

    assert "Renal adjustment required — consult SmPC" in text
    assert "Dose: consult SmPC" in text


def test_nfr_011_committed_review_sheet_is_up_to_date() -> None:
    committed = (ROOT / "docs" / "clinical-review.md").read_text(encoding="utf-8")

    assert committed == _load_script().render(), "run: uv run python scripts/render_rule_table.py"
