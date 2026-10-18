from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

PACKAGE = Path(__file__).parent.parent / "src" / "openmedcheck"
FORBIDDEN_JS = re.compile(
    r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function"
)
# "diagnoses" is the API field name for coded conditions, so only verb forms and the singular
# noun are banned here.
BANNED_WORDS = re.compile(
    r"\bapproved\b|\bsafe\b|\bdiagnose\b|\bdiagnosed\b|\bdiagnosing\b|\bdiagnosis\b",
    re.IGNORECASE,
)


def _ui_files() -> list[Path]:
    return [*PACKAGE.glob("static/*.js"), *PACKAGE.glob("templates/*.html")]


def test_nfr_001_static_js_never_inserts_markup() -> None:
    scripts = list(PACKAGE.glob("static/*.js"))
    assert scripts
    for script in scripts:
        assert not FORBIDDEN_JS.search(script.read_text()), script.name


def test_nfr_001_templates_have_no_inline_script_or_style() -> None:
    for template in PACKAGE.glob("templates/*.html"):
        text = template.read_text()
        for match in re.finditer(r"<script\b([^>]*)>(.*?)</script>", text, re.DOTALL):
            assert "src=" in match.group(1), template.name
            assert match.group(2).strip() == "", template.name
        assert "<style" not in text, template.name
        assert " style=" not in text, template.name
        assert not re.search(r"\son[a-z]+\s*=", text), template.name
        assert "http://" not in text, template.name
        assert "https://" not in text, template.name


def test_nfr_001_static_css_has_no_remote_urls() -> None:
    for sheet in PACKAGE.glob("static/*.css"):
        assert "http" not in sheet.read_text(), sheet.name


def test_ac_010_2_ui_strings_avoid_banned_wording() -> None:
    for path in _ui_files():
        assert not BANNED_WORDS.search(path.read_text()), path.name


def test_ac_010_1_page_has_banner_and_local_assets(client: TestClient) -> None:
    html = client.get("/").text

    assert "Not for clinical use — synthetic patients. Not a medical device." in html
    assert "/static/app.js" in html
    assert "Sign order" in html


def test_t_007_static_assets_are_served_locally(client: TestClient) -> None:
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_ac_008_8_ui_contains_required_fixed_texts() -> None:
    script = (PACKAGE / "static" / "app.js").read_text()

    assert "Order signed (demo — nothing stored)" in script
    assert "Verifying the prescription with Gemma…" in script
    assert "Acknowledge and keep order" in script
    assert "Use alternative" in script
    assert "No issue found by these checks" in script


def test_ac_010_2_server_sent_texts_avoid_banned_wording() -> None:
    from openmedcheck.presets import PRESETS
    from openmedcheck.rule_table import ALLERGY_RULE, CONTEXT_RULES, RENAL_RULES

    texts = [rule.reason for rule in (ALLERGY_RULE, *CONTEXT_RULES, *RENAL_RULES)]
    for preset in PRESETS.values():
        texts += [preset.title, preset.synthetic_label]
    # Rule reasons may say "a coded diagnosis" (a recorded input, not a system action), so the
    # noun is allowed here; the verbs and the absolute claims are not.
    banned = re.compile(r"\bapproved\b|\bsafe\b|\bdiagnose\b|\bdiagnosed\b|\bdiagnosing\b")
    for text in texts:
        assert not banned.search(text), text


def test_ac_007_1_record_fields_are_marked_and_order_fields_are_not() -> None:
    html = (PACKAGE / "templates" / "index.html").read_text()

    record_paths = re.findall(r'data-path="(context\.[^"]+)" data-record', html)
    assert set(record_paths) == {
        "context.age",
        "context.sex",
        "context.weight_kg",
        "context.reason_for_consult",
        "context.labs.creatinine_mg_dl",
        "context.labs.egfr_ml_min_1_73m2",
        "context.ed_note",
    }
    assert not re.search(r'data-path="order\.[^"]+" data-record', html)
    assert "From the patient record (simulated)" in html
    assert "Edit scenario (demo only)" in html


def test_ac_007_1_record_starts_read_only_and_the_toggle_unlocks_it() -> None:
    script = (PACKAGE / "static" / "app.js").read_text()

    assert "setRecordEditable(false)" in script
    assert "input.readOnly = !editable" in script
    # The sex select is swapped for a read-only text copy while the record is locked.
    assert 'if (input.tagName === "SELECT") input.hidden = !editable' in script
    assert '$("f-sex-text").hidden = editable' in script


def test_ac_007_4_request_panel_is_text_only_and_collapsed(client: TestClient) -> None:
    html = client.get("/").text
    script = (PACKAGE / "static" / "app.js").read_text()

    assert '<details id="payload" class="payload" hidden>' in html
    assert "<details open" not in html
    assert "What the record system would send" in html
    assert '$("payload-body").textContent = JSON.stringify(request, null, 2)' in script


def test_ac_006_5_page_lists_patients_instead_of_preset_letters(client: TestClient) -> None:
    html = client.get("/").text

    assert "Rooms (synthetic patients)" in html
    assert 'id="patient-list"' in html
    assert "Preset A" not in html


def _function_body(script: str, name: str) -> str:
    start = script.index(f"function {name}(")
    end = script.index("\n}\n", start)
    return script[start:end]


def test_ac_008_7_leaving_edit_scenario_restores_record_and_drops_the_card() -> None:
    script = (PACKAGE / "static" / "app.js").read_text()

    body = _function_body(script, "toggleScenarioEditing")
    assert "fillContext(state.record.context);" in body
    assert "invalidate();" in body
    assert 'if (input.hasAttribute("data-record")) state.scenarioEdited = true;' in script


def test_ac_008_1_selecting_a_room_hides_results_and_does_not_verify() -> None:
    body = _function_body((PACKAGE / "static" / "app.js").read_text(), "selectRoom")

    assert "hideResults();" in body
    assert "fillOrder(EMPTY_ORDER);" in body
    assert "evaluate(" not in body


def test_ac_007_1_order_controls_outside_the_form_are_bound_to_it() -> None:
    html = (PACKAGE / "templates" / "index.html").read_text()

    order_controls = re.findall(r"<(?:input|select)\b[^>]*data-path=\"order\.[^\"]+\"[^>]*>", html)
    assert len(order_controls) == 4
    assert all('form="check-form"' in control for control in order_controls)
    assert 'type="submit" form="check-form" id="check-button"' in html


def test_ac_008_1_verify_calls_only_the_final_check_and_shows_a_loading_state(
    client: TestClient,
) -> None:
    html = client.get("/").text
    body = _function_body((PACKAGE / "static" / "app.js").read_text(), "evaluate")

    assert ">Verify prescription</button>" in html
    assert "Check order" not in html
    assert '<div id="result-panel" hidden>' in html
    assert 'renderMessage(VERIFYING_TEXT, "checking")' in body
    assert 'postJson("/api/check", request)' in body
    assert "/api/check/rules" not in body


def test_ac_006_7_and_ac_007_5_room_and_patient_actions_exist(client: TestClient) -> None:
    html = client.get("/").text
    script = (PACKAGE / "static" / "app.js").read_text()

    for text in ("Add room", "Add patient", "Template patient", "Save patient"):
        assert text in html
    assert "Auto-fill test prescription" in html
    # Rooms live in page memory only (NFR-002): no browser storage anywhere in the script.
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "indexedDB" not in script


def test_ac_008_7_every_await_in_verify_and_fallback_rechecks_the_sequence() -> None:
    script = (PACKAGE / "static" / "app.js").read_text()

    evaluate = _function_body(script, "evaluate")
    assert evaluate.count("if (mine !== state.seq) return;") >= 3
    fallback = _function_body(script, "settleWithRulesOnly")
    assert fallback.index("if (mine !== state.seq) return;") < fallback.index("setModelStatus(")
    invalidate = _function_body(script, "invalidate")
    assert "state.seq += 1;" in invalidate
    assert "state.checking = false;" in invalidate


def test_ac_008_2_sign_stays_disabled_on_an_unresolved_blocked_card() -> None:
    body = _function_body((PACKAGE / "static" / "app.js").read_text(), "updateSign")

    assert 'card.status === "BLOCKED" && !state.resolved' in body
    assert "!state.checking && !blockedUnresolved" in body


def test_req_005_client_fallback_note_matches_the_server_note() -> None:
    from openmedcheck.check_service import MODEL_UNAVAILABLE_NOTE

    script = (PACKAGE / "static" / "app.js").read_text()

    assert f'const NO_MODEL_NOTE = "{MODEL_UNAVAILABLE_NOTE}";' in script
    assert 'postJson("/api/check/rules", request)' in _function_body(script, "settleWithRulesOnly")


def test_ac_009_1_unreviewed_alternative_waits_for_the_dose_and_does_not_verify() -> None:
    body = _function_body((PACKAGE / "static" / "app.js").read_text(), "useAlternative")
    unreviewed = body[body.index("if (!alt.route || !alt.frequency)") : body.index("return;")]

    assert '$("f-dose").value = "";' in unreviewed
    assert "invalidate();" in unreviewed
    assert "evaluate(" not in unreviewed


def test_ac_007_6_autofill_says_doses_are_test_input() -> None:
    html = (PACKAGE / "templates" / "index.html").read_text()

    assert "the doses are test input, not recommendations" in html


def test_ac_003_7_card_shows_note_evidence_as_text() -> None:
    body = _function_body((PACKAGE / "static" / "app.js").read_text(), "renderWhy")

    assert "rule.evidence" in body
    assert "From the clinician's note: “${quote}”" in body
