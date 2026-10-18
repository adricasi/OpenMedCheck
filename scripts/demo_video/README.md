# Demo video (T-012)

Builds the promotional demo video: designed slides, a screen recording of the app on preset A
(Bed 3), and a synthetic narration voice, with burned-in captions and a sidecar `.srt`. Synthetic
patients only; every slide and every app frame carries the "Not for clinical use — synthetic
patients. Not a medical device." banner.

| File | What it is |
|---|---|
| `scenes.json` | The scene list and the narration, spoken as written. Edit the text here. |
| `slides.html` | The slides, in the app's own fonts and colours; each `<section id>` is one 1920x1080 slide. |
| `record_app.py` | Drives the running app with Playwright (Bed 3 → auto-fill → verify → use alternative) and records `app.webm` plus the timestamps of each step in `app_marks.json`. |
| `build_video.py` | Renders the slides, speaks each scene with Kokoro-82M (Apache-2.0, local), cuts the recording to the narration, captions, joins and loudness-normalises. |

## Record the live app (needs the real model)

The recording must show the real Gemma 4 answer, so run it where the model runs, for example
the local Docker setup with a GPU ([docs/deploy/local-docker.md](../../docs/deploy/local-docker.md)):

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
uv run --with playwright==1.56.0 playwright install chromium     # once
uv run --with playwright==1.56.0 python scripts/demo_video/record_app.py --out build/demo
```

The script waits for the header to read "Model ready" before it starts, so the first check is
not a cold-start fallback. Check that `build/demo/app_marks.json` has every step and watch
`build/demo/app.webm` once: the card must be `BLOCKED` with the two quotes, then
"No issue found by these checks" after "Use alternative".

## Build the video

Download the Kokoro model and voices once (from the
[kokoro-onnx releases](https://github.com/thewh1teagle/kokoro-onnx/releases): `kokoro-v1.0.onnx`
and `voices-v1.0.bin`), then:

```bash
uv run --with playwright==1.56.0 --with kokoro-onnx --with soundfile \
  python scripts/demo_video/build_video.py --recording build/demo \
  --kokoro-model kokoro-v1.0.onnx --kokoro-voices voices-v1.0.bin
```

Output: `build/demo/openmedcheck-demo.mp4` (1920x1080, 30 fps, H.264/AAC, about 2 minutes) and
`build/demo/openmedcheck-demo.srt`. It needs `ffmpeg` with libass on `PATH`. The voice and speed
are set in `scenes.json` (`"voice"`, `"speed"`); other Kokoro voices include `am_michael` and
`bf_emma`.

`--draft-label "..."` burns a label into the app scenes. Use it for any cut whose model answer is
not the live model's, so a draft can never be mistaken for the real recording.

## Rules for the content

The narration follows the project's wording rules: never "approved" or "safe";
the system checks orders against diagnoses and never makes them; `NO_ISSUE` is "No issue found by
these checks"; the prescriber decides; the 97% is a development-set figure. Re-check the
wording after changing `scenes.json` or `slides.html`.
