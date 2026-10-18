# Run locally with Docker (one command)

Runs the app and Ollama in containers. Synthetic patients only; not a medical device. This is
the on-premises shape of the product: nothing leaves your machine except the one-time image and
model downloads.

## Requirements
- Docker with the Compose plugin (`docker compose version`).
- About 10 GB of free disk (images plus the 6.6 GB `gemma4:e4b` model).
- Optional: an NVIDIA GPU with at least 8 GB of VRAM and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/).
  Without a GPU the model runs on the CPU and is much slower than the 10 s model deadline, so
  cards fall back to rules only.

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
prescription. Stop with `Ctrl+C`; `docker compose down` removes the containers, and
`docker compose down -v` also deletes the downloaded model.

Alternative to step 1 once the stack is running:
`docker compose exec ollama ollama pull gemma4:e4b`.

## What stays local
- The app is published only as `127.0.0.1:8000`; Ollama has no published port.
- The container binds `0.0.0.0` internally (`OPENMEDCHECK_ALLOW_NONLOCAL=1`) and accepts only the
  Host headers `localhost` and `127.0.0.1` (`OPENMEDCHECK_PUBLIC_HOSTS`). The hosted-demo notice
  is shown only when a non-loopback public host is configured.
- Do not change the port mapping to `8000:8000` or `0.0.0.0:8000:8000`: that exposes the app to
  your network.

## Troubleshooting
- Model status stays "unavailable": run `docker compose logs ollama` and check the pull finished
  (`docker compose exec ollama ollama list`).
- First check after start is rules only: the model was still loading; wait for "ready".
- Health: `docker compose ps` shows the health state of each service (`/healthz` for the app).
