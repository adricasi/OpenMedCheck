"""Smoke test of scripts/eval_set.py without a model (AC-012.4, T-015)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).parent.parent / "scripts" / "eval_set.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_set", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def test_ac_012_4_rules_only_report_is_written(tmp_path: Path) -> None:
    script = load_script()
    cases = script.load_cases(script.CASES_PATH)

    baseline = script.run_rules_only(cases)
    out = tmp_path / "report.md"
    script.write_report(out, "rules only", cases, baseline, None)

    text = out.read_text(encoding="utf-8")
    assert baseline.total == len(cases)
    assert baseline.false_alarms == 0
    assert "| Final status correct |" in text
    assert "Rules + Gemma" in text
