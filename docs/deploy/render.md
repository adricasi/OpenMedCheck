# Deploy the hosted demo app on Render (opt-in, synthetic data only)

The product is meant to run on-premises inside the hospital. This hosted copy exists only so
judges can try the demo. It shows a notice on every page saying so. Never enter real patient
data. You do these steps by hand; nothing in the repository deploys anything.

Order: set up the model host first ([digitalocean-gemma.md](digitalocean-gemma.md)), then the
app. You need from that guide: the HTTPS URL of the model proxy and the bearer API key.

## 1. Create the service from the Blueprint
1. Push the branch you want to deploy to GitHub (the Blueprint reads `render.yaml` from the
   repository root).
2. Render dashboard -> New -> Blueprint -> connect the `OpenMedCheck` repository and pick the
   branch (check in the console: menu names may differ).
3. Render reads `render.yaml`: one Docker web service `openmedcheck-demo`, health check
   `/healthz`, auto-deploy off. Render prompts for the variables marked `sync: false`.

## 2. Environment variables
| Variable | Value | Secret |
|---|---|---|
| `OPENMEDCHECK_ALLOW_NONLOCAL` | `1` (set by the Blueprint) | no |
| `OPENMEDCHECK_HOST` | `0.0.0.0` (set by the Blueprint) | no |
| `OPENMEDCHECK_PUBLIC_HOSTS` | the service host name, e.g. `openmedcheck-demo.onrender.com`, plus your custom domain if any (comma-separated, no scheme, no port) | no |
| `OPENMEDCHECK_OLLAMA_URL` | `https://<your model host>` (must be https when a key is set) | no |
| `OPENMEDCHECK_OLLAMA_API_KEY` | the bearer token from the model-host guide | **yes** |

Render injects `PORT` itself; the app uses it when `OPENMEDCHECK_PORT` is unset. Do not set
`OPENMEDCHECK_PORT`. The exact `*.onrender.com` name is shown on the service page after
creation (check in the console). If it differs from the name you entered, update
`OPENMEDCHECK_PUBLIC_HOSTS` and redeploy; otherwise every request returns 400 "Invalid host
header". `/healthz` is exempt from the host check, so Render's health probe works whatever Host
header it sends.

Paste the API key only into the Render dashboard field. Never put it in the repository, a
commit message or an issue.

## 3. Verify
```bash
curl -s https://<app host>/healthz                 # {"status":"ok"}
curl -s https://<app host>/api/model/health        # "ready" once the model host answers
```
Open the URL: the page must show the hosted-demo notice. Run preset A (Bed 3, "Auto-fill test
prescription", "Verify prescription"). If the model host is off or unreachable you get the
rules-only card with "Model check unavailable".

## 4. Cost, idle behaviour and shutdown
- Check current plans and prices in the Render dashboard; the Blueprint requests the `starter`
  plan. A free instance, if you choose it, spins down when idle, so the first request after a
  pause is slow (check in the console).
- When judging ends: suspend or delete the service (service page -> Settings), and power off or
  destroy the GPU droplet (the larger cost).

## 5. Rotate the API key
Follow the rotation steps in [digitalocean-gemma.md](digitalocean-gemma.md), then update
`OPENMEDCHECK_OLLAMA_API_KEY` in Render (Environment tab) and let it redeploy.

## Rollback
Render dashboard -> the service -> Deploys -> redeploy a previous deploy (check in the
console). Auto-deploy is off, so nothing changes until you trigger it.
