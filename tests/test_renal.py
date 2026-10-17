from __future__ import annotations

import pytest

from openmedcheck.renal import cockcroft_gault


def test_ac_002_7_male_formula() -> None:
    # (140 - 60) * 80 / (72 * 1.0) = 88.888...
    assert round(cockcroft_gault(60, 80, "M", 1.0), 1) == 88.9


def test_ac_002_7_female_factor() -> None:
    # (140 - 78) * 62 / (72 * 2.4) * 0.85 = 18.9
    assert round(cockcroft_gault(78, 62, "F", 2.4), 1) == 18.9


def test_ac_002_7_rejects_non_positive_creatinine() -> None:
    with pytest.raises(ValueError, match="creatinine"):
        cockcroft_gault(60, 80, "M", 0)
