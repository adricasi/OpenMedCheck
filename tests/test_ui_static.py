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
