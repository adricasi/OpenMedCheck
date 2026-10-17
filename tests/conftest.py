from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openmedcheck.config import Config
from openmedcheck.model_client import FakeModelClient
from openmedcheck.web import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Config(), FakeModelClient([])), base_url="http://127.0.0.1:8000")


@pytest.fixture
def make_payload() -> Callable[..., dict[str, Any]]:
    def build(**context_overrides: Any) -> dict[str, Any]:
        context: dict[str, Any] = {
            "patient_id": "SYN-001",
            "age": 64,
            "sex": "M",
            "weight_kg": 80,
            "reason_for_consult": "Chest discomfort",
            "ed_note": "Synthetic note.",
            "diagnoses": [],
            "chronic_medications": [],
            "allergies": [],
            "labs": {"creatinine_mg_dl": 1.0},
        }
        context.update(context_overrides)
        return {
            "context": context,
            "order": {
                "drug_id": "ibuprofen",
                "dose_text": "400 mg",
                "route": "PO",
                "frequency": "every 8 hours",
            },
        }

    return build
