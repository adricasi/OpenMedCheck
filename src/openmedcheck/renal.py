"""Cockcroft-Gault creatinine clearance (AC-002.7). Pure: no I/O, no logging."""

from __future__ import annotations

from typing import Literal

FEMALE_FACTOR = 0.85


def cockcroft_gault(
    age: int, weight_kg: float, sex: Literal["M", "F"], creatinine_mg_dl: float
) -> float:
    """Return CrCl in mL/min using actual body weight, unrounded; callers round for display.

    CrCl = (140 - age) x weight / (72 x creatinine), multiplied by 0.85 for women.
    """
    if creatinine_mg_dl <= 0:
        raise ValueError("creatinine must be greater than zero")
    crcl = (140 - age) * weight_kg / (72 * creatinine_mg_dl)
    if sex == "F":
        crcl *= FEMALE_FACTOR
    return crcl
