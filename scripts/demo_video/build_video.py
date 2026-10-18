"""Build the demo video (T-012): slides + the app recording + a synthetic narration voice.

Inputs: scenes.json (narration per scene), slides.html (rendered with Playwright) and the
output of record_app.py (app.webm + app_marks.json). The voice is Kokoro-82M (Apache-2.0) run
locally through kokoro-onnx; ffmpeg cuts, captions and joins the scenes. Synthetic patients only.

    uv run --with playwright==1.56.0 --with kokoro-onnx --with soundfile \
        python scripts/demo_video/build_video.py --recording build/demo \
        --kokoro-model kokoro-v1.0.onnx --kokoro-voices voices-v1.0.bin
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import soundfile
from kokoro_onnx import Kokoro
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SIZE = (1920, 1080)
FPS = 30
LEAD_S = 0.35  # silence before the narration of each scene
TAIL_S = 0.6  # hold after it
FADE_S = 0.25
CAPTION_STYLE = (
    "FontName=DejaVu Sans,FontSize=13,PrimaryColour=&H00FFFFFF,BackColour=&H1A16232F,"
    "BorderStyle=4,Outline=0,Shadow=0,MarginV=34,Alignment=2"
)


@dataclass(frozen=True)
class Scene:
    scene_id: str
    narration: str
    slide: str | None
    clip: tuple[str, str] | None


def ffmpeg(*args: str) -> None:
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise SystemExit("ffmpeg is required on PATH")
    subprocess.run([binary, "-v", "error", "-y", *args], check=True)  # noqa: S603


def load_scenes(path: Path) -> tuple[str, float, list[Scene]]:
    data = json.loads(path.read_text())
    scenes = [
        Scene(
            scene_id=item["id"],
            narration=item["narration"],
            slide=item.get("slide"),
            clip=tuple(item["clip"]) if "clip" in item else None,  # type: ignore[arg-type]
        )
        for item in data["scenes"]
    ]
    return data.get("voice", "af_heart"), float(data.get("speed", 1.0)), scenes


def render_slides(slide_ids: set[str], out_dir: Path) -> dict[str, Path]:
    page_url = (HERE / "slides.html").as_uri()
    paths: dict[str, Path] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": SIZE[0], "height": SIZE[1]})
        for slide_id in sorted(slide_ids):
            page.goto(f"{page_url}#{slide_id}")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(200)
            paths[slide_id] = out_dir / f"slide-{slide_id}.png"
            page.screenshot(path=str(paths[slide_id]))
        browser.close()
    return paths


def speak(tts: Kokoro, voice: str, speed: float, text: str, out: Path) -> float:
    samples, rate = tts.create(text, voice=voice, speed=speed, lang="en-us")
    soundfile.write(out, samples, rate)
    return len(samples) / rate


def write_captions(text: str, start_s: float, duration_s: float, out: Path) -> None:
    """One caption per sentence, timed in proportion to its length within the narration."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?:;])\s+", text) if s.strip()]
    total = sum(len(s) for s in sentences)
    clock = start_s
    lines = []
    for index, sentence in enumerate(sentences, start=1):
        length = duration_s * len(sentence) / total
        lines += [str(index), f"{_srt_time(clock)} --> {_srt_time(clock + length)}", sentence, ""]
        clock += length
    out.write_text("\n".join(lines))


def _srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def build_segment(
    scene: Scene,
    voice_wav: Path,
    voice_s: float,
    slides: dict[str, Path],
    recording: Path,
    marks: dict[str, float],
    draft_label: str | None,
    work: Path,
) -> Path:
    captions = work / f"{scene.scene_id}.srt"
    write_captions(scene.narration, LEAD_S, voice_s, captions)
    out = work / f"{scene.scene_id}.mp4"
    needed_s = LEAD_S + voice_s + TAIL_S
    if scene.slide is not None:
        duration = needed_s
        video_in = [
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-t",
            f"{duration:.3f}",
            "-i",
            str(slides[scene.slide]),
        ]
        video_filter = "format=yuv420p"
    else:
        if scene.clip is None:
            raise ValueError(f"scene {scene.scene_id} needs a slide or a clip")
        start, end = (0.0 if m == "start" else marks[m] for m in scene.clip)
        clip_s = end - start
        duration = max(clip_s, needed_s)
        video_in = ["-ss", f"{start:.3f}", "-t", f"{clip_s:.3f}", "-i", str(recording)]
        hold = duration - clip_s
        video_filter = (
            f"fps={FPS},scale={SIZE[0]}:{SIZE[1]},"
            f"tpad=stop_mode=clone:stop_duration={hold:.3f},format=yuv420p"
        )
        if draft_label:
            label = draft_label.replace(":", r"\:").replace("'", r"\'")
            video_filter += (
                f",drawtext=text='{label}':font='DejaVu Sans':fontsize=30:fontcolor=0x16232f:"
                "box=1:boxcolor=0xf2b134:boxborderw=14:x=w-tw-36:y=70"
            )
    fade_out = max(duration - FADE_S, 0)
    style = CAPTION_STYLE
    video_filter += (
        f",fade=t=in:st=0:d={FADE_S},fade=t=out:st={fade_out:.3f}:d={FADE_S},"
        f"subtitles={captions}:force_style='{style}'"
    )
    ffmpeg(
        *video_in,
        "-i", str(voice_wav),
        "-filter_complex",
        f"[0:v]{video_filter}[v];[1:a]adelay={int(LEAD_S * 1000)}:all=1,apad,"
        f"atrim=0:{duration:.3f},aresample=48000[a]",
        "-map", "[v]", "-map", "[a]",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "160k", "-ac", "2",
        str(out),
    )  # fmt: skip
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recording", type=Path, required=True, help="record_app.py output dir")
    parser.add_argument("--kokoro-model", type=Path, required=True)
    parser.add_argument("--kokoro-voices", type=Path, required=True)
    parser.add_argument("--scenes", type=Path, default=HERE / "scenes.json")
    parser.add_argument(
        "--out", type=Path, default=None, help="default: <recording>/openmedcheck-demo.mp4"
    )
    parser.add_argument("--draft-label", default=None, help="text burned into the app scenes")
    args = parser.parse_args()

    voice, speed, scenes = load_scenes(args.scenes)
    recording = args.recording / "app.webm"
    marks = json.loads((args.recording / "app_marks.json").read_text())
    work = args.recording / "work"
    work.mkdir(parents=True, exist_ok=True)
    out = args.out or args.recording / "openmedcheck-demo.mp4"

    slides = render_slides({s.slide for s in scenes if s.slide}, work)
    tts = Kokoro(str(args.kokoro_model), str(args.kokoro_voices))
    segments = []
    captions_all = []
    clock = 0.0
    for scene in scenes:
        wav = work / f"{scene.scene_id}.wav"
        voice_s = speak(tts, voice, speed, scene.narration, wav)
        segment = build_segment(
            scene, wav, voice_s, slides, recording, marks, args.draft_label, work
        )
        segments.append(segment)
        captions_all.append((clock + LEAD_S, voice_s, scene.narration))
        clock += float(_probe_duration(segment))
        print(f"{scene.scene_id}: narration {voice_s:.1f} s")

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{s.resolve()}'\n" for s in segments))
    ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart", str(out),
    )  # fmt: skip
    _write_full_captions(captions_all, out.with_suffix(".srt"))
    print(f"wrote {out} ({clock:.1f} s) and {out.with_suffix('.srt')}")


def _probe_duration(path: Path) -> str:
    binary = shutil.which("ffprobe")
    if binary is None:
        raise SystemExit("ffprobe is required on PATH")
    result = subprocess.run(  # noqa: S603
        [binary, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_full_captions(parts: list[tuple[float, float, str]], out: Path) -> None:
    """A sidecar .srt for the whole video, for platforms that take captions separately."""
    blocks = []
    index = 1
    for start, duration, text in parts:
        piece = out.with_name(f".tmp-{index}.srt")
        write_captions(text, start, duration, piece)
        for block in piece.read_text().strip().split("\n\n"):
            _, timing, *body = block.split("\n")
            blocks.append("\n".join([str(index), timing, *body]))
            index += 1
        piece.unlink()
    out.write_text("\n\n".join(blocks) + "\n")


if __name__ == "__main__":
    main()
