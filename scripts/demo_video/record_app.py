"""Record the running app for the demo video (T-012): Bed 3 -> verify -> alternative -> re-check.

Drives the real UI with Playwright against a running instance (default http://127.0.0.1:8000,
e.g. `docker compose up` with the GPU override) and writes a video plus the timestamps of each
step, which build_video.py uses to cut the recording to the narration. Synthetic patients only.

    uv run --with playwright==1.56.0 python scripts/demo_video/record_app.py --out build/demo
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

VIDEO_SIZE = {"width": 1920, "height": 1080}
# Lay the page out as on a 1440 px wide screen, then paint it at 1920 px: crisp text that is
# large enough to read in a video (Playwright records CSS pixels, not device pixels).
ZOOM = 1920 / 1440


def wait_for_model_ready(page: Page, timeout_s: float) -> bool:
    """Wait until the header reads "ready", so the first check is not a cold-start fallback."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if "ready" in page.locator("#model-status").inner_text().lower():
            return True
        page.wait_for_timeout(500)
    return False


def record(url: str, out_dir: Path, ready_timeout_s: float, card_timeout_s: float) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    marks: dict[str, float] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport=VIDEO_SIZE, record_video_dir=str(out_dir), record_video_size=VIDEO_SIZE
        )
        context.add_init_script(
            f"document.addEventListener('DOMContentLoaded', () => "
            f"{{ document.documentElement.style.zoom = '{ZOOM}'; }});"
        )
        page = context.new_page()
        start = time.monotonic()

        def mark(name: str) -> None:
            marks[name] = round(time.monotonic() - start, 3)

        page.goto(url)
        if not wait_for_model_ready(page, ready_timeout_s):
            print("warning: model status never read 'ready'; the card may be rules-only")
        page.wait_for_timeout(1000)
        mark("open")

        page.locator("button.patient-button", has_text="Bed 3").click()
        mark("room")
        page.wait_for_timeout(3500)  # time to read the note

        page.locator("#autofill-button").click()
        mark("autofill")
        page.wait_for_timeout(2000)

        page.locator("#check-button").click()
        mark("verify")
        card = page.locator("#card-area article.card")
        card.wait_for(timeout=card_timeout_s * 1000)
        mark("card")
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(6000)  # the verdict, the quoted evidence and the alternative

        page.locator("#use-alternative").click()
        mark("alternative")
        page.locator("#card-area article.card.card-compact").wait_for(timeout=card_timeout_s * 1000)
        mark("recheck")
        page.locator("#card-area").scroll_into_view_if_needed()
        page.wait_for_timeout(4000)
        mark("end")

        video = page.video
        context.close()
        browser.close()
        if video is None:
            raise RuntimeError("Playwright did not record a video")
        video_path = Path(video.path())

    final = out_dir / "app.webm"
    video_path.replace(final)
    (out_dir / "app_marks.json").write_text(json.dumps(marks, indent=2))
    print(f"recorded {final} with marks {marks}")
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, default=Path("build/demo"))
    parser.add_argument("--ready-timeout", type=float, default=120.0)
    parser.add_argument("--card-timeout", type=float, default=60.0)
    args = parser.parse_args()
    record(args.url, args.out, args.ready_timeout, args.card_timeout)


if __name__ == "__main__":
    main()
