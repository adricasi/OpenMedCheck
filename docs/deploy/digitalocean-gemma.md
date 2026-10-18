# Gemma on a DigitalOcean GPU droplet behind Caddy (bearer token)

Ollama listens on the droplet's loopback only. Caddy terminates HTTPS and forwards a request to
Ollama only when it carries `Authorization: Bearer <key>`; everything else gets 401. You do
every step by hand; nothing here is automated or deployed by the repository.

Data: synthetic patients only. The model host receives the prompt (clinical note and order) for
each check, which is why this is a demo profile and not the product story.

## 0. Choose the droplet (human, in the console)
- Create a GPU droplet in the DigitalOcean control panel. Pick an image with the NVIDIA driver
  preinstalled if one is offered, and a GPU with at least 8 GB of VRAM (`gemma4:e4b` is about
  6.6 GB). GPU sizes, regions and hourly prices change: check in the console before creating it.
- Add your SSH key (no password login). Note the droplet IP.
- Use a DNS name you control (`gemma.example.org` with an A record to the droplet IP). Caddy's
  automatic HTTPS needs a name; Let's Encrypt does not issue certificates for bare IP addresses
  in the default setup. If you have no domain, check in the console whether the droplet gets a
  usable public host name.

## 1. Firewall
Networking -> Firewalls (check in the console): attach to the droplet inbound rules for only
TCP 22 (restrict the source to your IP if you can), TCP 443, and TCP 80 (the ACME HTTP challenge
and the redirect to HTTPS). Do not open 11434.

## 2. Install Ollama and keep it on loopback
```bash
ssh root@<droplet-ip>
nvidia-smi                               # the GPU must be listed
curl -fsSL https://ollama.com/install.sh -o install-ollama.sh
less install-ollama.sh                   # read it before running
sh install-ollama.sh
systemctl status ollama --no-pager
ss -ltnp | grep 11434                    # must show 127.0.0.1:11434, not 0.0.0.0
ollama pull gemma4:e4b
ollama run gemma4:e4b "Say OK"           # quick GPU check, then /bye
```
Ollama binds `127.0.0.1:11434` by default. Do not set `OLLAMA_HOST`. If `ss` shows `0.0.0.0`,
remove any `OLLAMA_HOST` override (`systemctl edit ollama`).

## 3. Generate the API key
```bash
openssl rand -hex 32
```
Copy the output into your password manager. It is the bearer token: the same value goes into
Caddy (below) and into Render as `OPENMEDCHECK_OLLAMA_API_KEY`. Never commit it.

## 4. Install Caddy and configure it
Install Caddy from its official package repository (current instructions:
<https://caddyserver.com/docs/install>, Debian/Ubuntu). Then store the key in a root-only
environment file for the service:
```bash
install -m 600 /dev/null /etc/caddy/caddy.env
nano /etc/caddy/caddy.env                # one line: OLLAMA_API_KEY=<the key from step 3>
systemctl edit caddy                     # add the two lines below, save
```
```ini
[Service]
EnvironmentFile=/etc/caddy/caddy.env
```
`/etc/caddy/Caddyfile` (replace the host name):
```caddyfile
gemma.example.org {
	@authorized header Authorization "Bearer {$OLLAMA_API_KEY}"

	handle @authorized {
		reverse_proxy 127.0.0.1:11434 {
			transport http {
				response_header_timeout 60s
			}
		}
	}

	handle {
		respond "Unauthorized" 401
	}
}
```
`{$OLLAMA_API_KEY}` is replaced from the environment when Caddy reads the Caddyfile, so the
variable must be set wherever the Caddyfile is parsed: the service gets it from the
`EnvironmentFile` above; for `caddy validate` load it into your shell first.
```bash
set -a; . /etc/caddy/caddy.env; set +a     # only for the validate step
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl daemon-reload && systemctl restart caddy
systemctl status caddy --no-pager        # Caddy obtains the certificate automatically
```
Keep the key hex-only (as `openssl rand -hex 32` produces) so no character needs escaping.

## 5. Verify from your own machine
```bash
curl -i https://gemma.example.org/api/tags                                    # expect 401
curl -i -H "Authorization: Bearer wrong" https://gemma.example.org/api/tags   # expect 401
curl -s -H "Authorization: Bearer $OLLAMA_API_KEY" https://gemma.example.org/api/tags
                                                      # expect JSON listing gemma4:e4b
nc -vz <droplet-ip> 11434                             # expect refused or timeout
```
Set `OLLAMA_API_KEY` in your shell from the password manager (do not paste it into shared logs
or screenshots). Then set `OPENMEDCHECK_OLLAMA_URL=https://gemma.example.org` and
`OPENMEDCHECK_OLLAMA_API_KEY` in Render ([render.md](render.md)).

## 6. Cost and power-off
A GPU droplet bills by the hour while it exists. Check in the console whether a powered-off GPU
droplet still bills (it usually does until destroyed). Plan: create it shortly before judging;
when judging ends, power it off and, if you do not need it again, destroy it, remove the DNS
record and suspend the Render service. Set a billing alert on the DigitalOcean account first.

## 7. Rotate the key
1. `openssl rand -hex 32` for a new key.
2. On the droplet: edit `/etc/caddy/caddy.env`, then `systemctl restart caddy`.
3. In Render: update `OPENMEDCHECK_OLLAMA_API_KEY` and redeploy.
4. Re-run the verification curls; the old key must now return 401.
Rotate immediately if the key was ever pasted somewhere it should not be.

## Risks
- A public GPU endpoint can be probed and, if the key leaks, used for free inference. The bearer
  token, the narrow firewall and the power-off plan are the mitigations (ADR 0007).
- Prompts contain only synthetic data, but the host still sees them; never use real patients.
- Caddy's request logs go to the journal; request bodies are not logged by default.
