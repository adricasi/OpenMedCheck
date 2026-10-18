"""Record the running app for the demo video (T-012): Bed 3, then Bed 5.

Bed 3: scroll the whole record (note and history) -> back to the top -> verify -> BLOCKED ->
accept the alternative -> the prescription changes and is re-checked.
Bed 5: scroll the whole record (the long past medical history) -> back to the top -> verify ->
WARNING with the quote.

Drives the real UI with Playwright against a running instance (default http://127.0.0.1:8000,
e.g. `docker compose up` with the GPU override) and writes a video plus the timestamps of each
step, which build_video.py uses to cut the recording to the narration. Synthetic patients only.

    uv run --with playwright==1.56.0 python scripts/demo_video/record_app.py --out build/demo
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
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


def open_room(page: Page, bed: str, mark: Callable[[str], None], name: str) -> None:
    page.evaluate("window.scrollTo(0, 0)")
    page.locator("button.patient-button", has_text=bed).click()
    mark(name)


# Smooth scroll in page JavaScript, so the recording shows a steady, readable movement.
_SCROLL_JS = """([target, ms]) => new Promise((done) => {
  const start = window.scrollY, distance = target - start, t0 = performance.now();
  function step(now) {
    const k = Math.min((now - t0) / ms, 1);
    const eased = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    window.scrollTo(0, start + distance * eased);
    if (k < 1) requestAnimationFrame(step); else done();
  }
  requestAnimationFrame(step);
})"""


def scroll_to(page: Page, target: float | str, ms: int) -> None:
    """Scroll to a y position, or to "bottom", over ``ms`` milliseconds."""
    if target == "bottom":
        target = page.evaluate("document.documentElement.scrollHeight - window.innerHeight")
    page.evaluate(_SCROLL_JS, [target, ms])


def read_record(page: Page) -> None:
    """Top to bottom through the whole record, a pause on the free text, then back to the top."""
    page.wait_for_timeout(1200)
    scroll_to(page, "bottom", 7000)
    page.wait_for_timeout(1800)
    scroll_to(page, 0, 1500)
    page.wait_for_timeout(600)


def verify(page: Page, mark: Callable[[str], None], suffix: str, card_timeout_s: float) -> None:
    page.locator("#autofill-button").click()
    mark(f"autofill{suffix}")
    page.wait_for_timeout(2000)
    page.locator("#check-button").click()
    mark(f"verify{suffix}")
    card = page.locator("#card-area article.card")
    card.wait_for(timeout=card_timeout_s * 1000)
    mark(f"card{suffix}")
    card.scroll_into_view_if_needed()


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

        open_room(page, "Bed 3", mark, "room3")
        read_record(page)

        verify(page, mark, "3", card_timeout_s)
        page.wait_for_timeout(7000)  # the verdict, the quoted evidence and the alternative

        page.locator("#use-alternative").click()
        mark("alternative")
        page.locator("#card-area article.card.card-compact").wait_for(timeout=card_timeout_s * 1000)
        mark("recheck")
        # Show the changed prescription (now paracetamol) and its re-check together.
        page.locator("#order-fields").scroll_into_view_if_needed()
        scroll_to(page, 0, 800)
        page.wait_for_timeout(5500)

        open_room(page, "Bed 5", mark, "room5")
        read_record(page)

        verify(page, mark, "5", card_timeout_s)
        page.wait_for_timeout(8000)  # the warning and the quoted line of the history
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
