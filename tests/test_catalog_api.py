from __future__ import annotations

from fastapi.testclient import TestClient

from openmedcheck.rule_table import DRUG_IDS


def test_t_007_drugs_endpoint_lists_the_drug_list(client: TestClient) -> None:
    response = client.get("/api/drugs")

    assert response.status_code == 200
    drugs = response.json()
    assert [drug["drug_id"] for drug in drugs] == list(DRUG_IDS)
    assert set(drugs[0]) == {"drug_id", "name", "active_ingredient", "class"}


def test_ac_006_4_presets_endpoint_lists_a_b_c_labelled_synthetic(client: TestClient) -> None:
    response = client.get("/api/presets")

    assert response.status_code == 200
    presets = response.json()
    assert [preset["preset_id"] for preset in presets] == list("ABCDEFGHIJK")
    assert all("Synthetic" in preset["synthetic_label"] for preset in presets)


def test_t_007_preset_detail_is_a_valid_check_request(client: TestClient) -> None:
    response = client.get("/api/presets/A")

    assert response.status_code == 200
    body = response.json()
    assert body["request"]["order"]["drug_id"] == "dexketoprofen"
    check = client.post("/api/check/rules", json=body["request"])
    assert check.status_code == 200


def test_t_007_unknown_preset_is_404_problem_json(client: TestClient) -> None:
    response = client.get("/api/presets/Z")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_ac_007_2_edited_context_is_evaluated_not_the_preset(client: TestClient) -> None:
    request = client.get("/api/presets/C").json()["request"]
    assert client.post("/api/check/rules", json=request).json()["status"] == "NO_ISSUE"

    request["order"]["drug_id"] = "ibuprofen"
    request["context"]["allergies"] = ["ibuprofen"]
    edited = client.post("/api/check/rules", json=request).json()

    assert edited["status"] == "BLOCKED"


def test_ac_007_2_edited_renal_value_changes_the_verdict(client: TestClient) -> None:
    request = client.get("/api/presets/B").json()["request"]
    assert client.post("/api/check/rules", json=request).json()["status"] == "WARNING"

    request["context"]["labs"] = {"creatinine_mg_dl": 0.8, "egfr_ml_min_1_73m2": 105}
    assert client.post("/api/check/rules", json=request).json()["status"] == "NO_ISSUE"


def test_ac_007_3_out_of_range_value_is_rejected_with_field_error(client: TestClient) -> None:
    request = client.get("/api/presets/A").json()["request"]
    request["context"]["age"] = 12

    response = client.post("/api/check/rules", json=request)

    assert response.status_code == 422
    assert "context.age" in [error["field"] for error in response.json()["errors"]]


def test_ac_009_1_alternative_order_is_rechecked_preset_a_paracetamol(client: TestClient) -> None:
    request = client.get("/api/presets/A").json()["request"]
    request["order"] = {
        "drug_id": "paracetamol",
        "dose_text": "Dose: consult SmPC",
        "route": "PO",
        "frequency": "as per SmPC",
    }

    card = client.post("/api/check/rules", json=request).json()

    assert card["status"] == "NO_ISSUE"
    assert card["headline"] == "No issue found by these checks"


def test_ac_006_5_presets_carry_distinct_bed_labels(client: TestClient) -> None:
    presets = client.get("/api/presets").json()

    beds = [preset["bed"] for preset in presets if preset["bed"] is not None]
    assert len(beds) == 3
    assert all(bed.startswith("Bed ") for bed in beds)
    assert len(set(beds)) == len(beds)
