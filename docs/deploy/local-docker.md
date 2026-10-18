# Run locally with Docker (one command)

Runs the app and Ollama in containers. Synthetic patients only; not a medical device. This is
the on-premises shape of the product: nothing leaves your machine except the one-time image and
model downloads, and it is the **only** way OpenMedCheck v0.1 is deployed — there is no hosted
demo ([ADR 0008](../adr/0008-drop-opt-in-hosted-demo.md)). For how this would run in a
hospital's own cloud instead, see
[`gcp-reference-architecture.md`](gcp-reference-architecture.md) (documented, not implemented).

## Requirements
- Docker with the Compose plugin (`docker compose version`).
- About 10 GB of free disk (images plus the 6.6 GB `gemma4:e4b` model).
- Optional: an NVIDIA GPU with at least 8 GB of VRAM and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/).
  Without a GPU the model runs on the CPU and is much slower than the 10 s model deadline, so
  cards fall back to rules only (see "Symptom: Bed 3 says No issue" below).

## Steps
```bash
git clone https://github.com/adricasi/OpenMedCheck.git && cd OpenMedCheck

# 1. Pull the model once (stored in the `ollama-models` volume).
docker compose --profile setup run --rm model-pull

# 2. Start the app and Ollama.
docker compose up --build                       # CPU
# docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build   # NVIDIA GPU
```
Open <http://127.0.0.1:8000>. Wait for the model status to read ready, then verify a
prescription.

### Symptom: Bed 3 says "No issue found by these checks" with "Model check unavailable"
Bed 3's suspected ACS is only in the note, so only the model can catch it. If the card shows
"Model check unavailable — rules only", the model did not answer within the deadline (the
fail-safe, REQ-005). Check where the model runs:
```bash
docker compose exec ollama ollama ps        # PROCESSOR "100% CPU" = no GPU in the container
```
- **Best: give the container the GPU.** Install the NVIDIA Container Toolkit (on WSL2 inside the
  Linux distribution, following NVIDIA's guide), run `sudo nvidia-ctk runtime configure
  --runtime=docker` and restart Docker, stop any native Ollama that holds the VRAM, then start
  with the GPU override above. `ollama ps` must then show `100% GPU`.
- **CPU only: raise the deadline.** `OPENMEDCHECK_MODEL_TIMEOUT_S=120 docker compose up` makes
  each check slow (tens of seconds) but lets the model finish, so Bed 3 is blocked. Stop with `Ctrl+C`; `docker compose down` removes the containers, and
`docker compose down -v` also deletes the downloaded model.

Alternative to step 1 once the stack is running:
`docker compose exec ollama ollama pull gemma4:e4b`.

## What gets created
| Container | Image | Published port | Purpose |
|---|---|---|---|
| `app` | built from this repo's `Dockerfile` | `127.0.0.1:8000` only | FastAPI app, rules engine, UI |
| `ollama` | `ollama/ollama:0.35.1` | none | Serves `gemma4:e4b`; reachable only from `app`, over the Compose network |
| `model-pull` | `ollama/ollama:0.35.1` | none | One-shot: pulls the model into the `ollama-models` volume, then exits (`--profile setup`) |

One named volume, `ollama-models`, holds the downloaded weights so they survive
`docker compose down` (but not `docker compose down -v`).

## Verify it is working
```bash
docker compose ps                                  # both services "running"/"healthy"
curl -s http://127.0.0.1:8000/healthz               # {"status":"ok"}
curl -s http://127.0.0.1:8000/api/model/health      # "ready" once the model has loaded
```
In the browser at <http://127.0.0.1:8000>: load preset A ("Bed 3"), click "Auto-fill test
prescription" then "Verify prescription". The rules card should appear almost instantly,
followed by the final card. If the final card says "Model check unavailable — rules only",
see "Symptom: Bed 3 says No issue" below.

## Configuration
Every setting is an environment variable read by `config.py`; set it before `app:` in
`docker-compose.yml`, or on the command line (`OPENMEDCHECK_MODEL_TIMEOUT_S=30 docker compose up`).

| Variable | Default | Change it when |
|---|---|---|
| `OPENMEDCHECK_MODEL_TIMEOUT_S` | `10` | The model runs on CPU and keeps timing out (see below) |
| `OPENMEDCHECK_MAX_MODEL_CALLS` | `4` | You want more or fewer concurrent model calls before extra checks get an instant rules-only card |
| `OPENMEDCHECK_MODEL` | `gemma4:e4b` | You pulled a different Ollama tag (re-run the model evaluation first: the prompt and schema are tuned for `gemma4:e4b`) |

Do **not** set `OPENMEDCHECK_ALLOW_NONLOCAL`, `OPENMEDCHECK_PUBLIC_HOSTS`,
`OPENMEDCHECK_HOST` or `OPENMEDCHECK_PORT` for a local run: the image already sets the first two
for the container's own interface, and changing the others, or the port mapping below, is how
you would accidentally expose the app to your network.

## What stays local
- The app is published only as `127.0.0.1:8000`; Ollama has no published port.
- The container binds `0.0.0.0` internally (`OPENMEDCHECK_ALLOW_NONLOCAL=1`) and accepts only the
  Host headers `localhost` and `127.0.0.1` (`OPENMEDCHECK_PUBLIC_HOSTS`) — this is the generic
  non-local opt-in described in REQ-015, used here only to let the container's own loopback-style
  binding work; it is not a hosted deployment. The "hosted for trying it" notice only appears
  when a non-loopback public host is configured, which this setup never does.
- Do not change the port mapping to `8000:8000` or `0.0.0.0:8000:8000`: that exposes the app to
  your network.

## Troubleshooting
- Model status stays "unavailable": run `docker compose logs ollama` and check the pull finished
  (`docker compose exec ollama ollama list`).
- First check after start is rules only: the model was still loading; wait for "ready".
- Health: `docker compose ps` shows the health state of each service (`/healthz` for the app).

## Stopping and cleaning up
```bash
docker compose down        # stops and removes the containers; keeps the downloaded model
docker compose down -v     # also deletes the ollama-models volume (re-pull next time)
docker system df           # check how much disk the images/volumes are using, if reclaiming space
```
