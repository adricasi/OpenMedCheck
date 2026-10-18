"""End-to-end measurement of the running app over HTTP (T-009; REQ-012, NFR-004, NFR-012).

Starts ``openmedcheck`` as a subprocess on a free loopback port, confirms the warm-up endpoint
loads the model, then times ``POST /api/check/rules`` and ``POST /api/check`` as a client sees
them over presets A, B, C and A re-checked with paracetamol (A-alt). Prints aggregates only: no
patient context or model text. Needs a local Ollama with the model tag.

    uv run python scripts/measure.py --calls 40 --rules-calls 200

``--cold-start`` unloads the configured model only (``keep_alive: 0`` for that tag, other loaded
models are untouched) and times the first check afterwards. Valid-output rate here is "the card
came from rules+model", i.e. valid on the first try or after the retry; the first-try rate needs
the raw attempt text and is measured by ``scripts/eval_model.py``.
"""

from __future__ import annotations

import argparse
import math
import os
import socket
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from openmedcheck import prompt
from openmedcheck.config import Config
from openmedcheck.contracts import CheckRequest, Order
from openmedcheck.presets import PRESETS

CASE_ORDER = ("A", "A-alt", "B", "C")
REQUEST_TIMEOUT_S = 30.0


def build_payloads() -> dict[str, dict[str, Any]]:
    cases = {pid: preset.request for pid, preset in PRESETS.items()}
    alt = Order(drug_id="paracetamol", dose_text="1 g", route="PO", frequency="every 8 hours")
    cases["A-alt"] = cases["A"].model_copy(update={"order": alt})
    return {key: _payload(cases[key]) for key in CASE_ORDER}


def _payload(request: CheckRequest) -> dict[str, Any]:
    return request.model_dump(mode="json")


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def running_app(port: int, model: str, ollama_url: str) -> Iterator[None]:
    env = {
        **os.environ,
        "OPENMEDCHECK_HOST": "127.0.0.1",
        "OPENMEDCHECK_PORT": str(port),
        "OPENMEDCHECK_MODEL": model,
        "OPENMEDCHECK_OLLAMA_URL": ollama_url,
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "openmedcheck"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise SystemExit("measure: the app did not start within 20 s")
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def timed_post(client: httpx.Client, path: str, payload: dict[str, Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    response = client.post(path, json=payload)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.raise_for_status()
    return elapsed_ms, response.json()


def wait_until_ready(client: httpx.Client, limit_s: float = 60.0) -> tuple[bool, float]:
    start = time.perf_counter()
    while time.perf_counter() - start < limit_s:
        status = client.get("/api/model/health").json()["status"]
        if status == "ready":
            return True, time.perf_counter() - start
        time.sleep(0.25)
    return False, time.perf_counter() - start


def hardware() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],  # noqa: S607 - fixed tool name, no input
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "nvidia-smi unavailable"


def ollama_facts(ollama: httpx.Client, model: str) -> dict[str, str]:
    facts = {"version": str(ollama.get("/api/version").json().get("version"))}
    for entry in ollama.get("/api/tags").json().get("models", []):
        if entry.get("name") == model:
            facts["digest"] = str(entry.get("digest"))[:12]
            facts["size_gb"] = f"{entry.get('size', 0) / 1e9:.1f}"
    for entry in ollama.get("/api/ps").json().get("models", []):
        if entry.get("name") == model and entry.get("size"):
            facts["vram_share"] = f"{entry.get('size_vram', 0) / entry['size']:.0%}"
    return facts


def summarize(label: str, values: list[float], budget_ms: float) -> str:
    p50, p95 = percentile(values, 50), percentile(values, 95)
    verdict = "met" if p95 < budget_ms else "MISSED"
    return (
        f"{label}: n={len(values)} p50={p50:.1f} ms p95={p95:.1f} ms max={max(values):.1f} ms "
        f"(budget p95 < {budget_ms:.0f} ms: {verdict})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=40, help="timed final-card calls (>= 20)")
    parser.add_argument("--rules-calls", type=int, default=200)
    parser.add_argument("--cold-start", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    if args.calls < 20:
        raise SystemExit("measure: NFR-004 needs at least 20 timed calls")

    config = Config()
    payloads = build_payloads()
    port = free_port()
    ollama = httpx.Client(base_url=config.ollama_url, timeout=30)
    print(f"prompt_version={prompt.PROMPT_VERSION} model={config.model}")
    print(f"hardware={hardware()}")
    print(f"ollama={ollama_facts(ollama, config.model)}")

    with (
        running_app(port, config.model, config.ollama_url),
        httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=REQUEST_TIMEOUT_S) as client,
    ):
        loaded_at_start = ollama.get("/api/ps").json().get("models", [])
        was_loaded = any(m.get("name") == config.model for m in loaded_at_start)
        print(f"model_loaded_before_warmup={was_loaded}")
        health_before = client.get("/api/model/health").json()["status"]
        warm = client.post("/api/model/warmup", json={})
        print(f"health_before={health_before} warmup_http={warm.status_code} body={warm.json()}")
        ready, ready_s = wait_until_ready(client)
        print(f"warmup_ready={ready} after {ready_s:.2f} s")
        if not ready:
            raise SystemExit("measure: the model did not become ready after warm-up")
        print(f"ollama_after_warmup={ollama_facts(ollama, config.model)}")

        rules_ms: list[float] = []
        for index in range(args.rules_calls):
            elapsed, _ = timed_post(client, "/api/check/rules", payloads[CASE_ORDER[index % 4]])
            rules_ms.append(elapsed)

        final_ms: list[float] = []
        per_case: dict[str, list[float]] = {key: [] for key in CASE_ORDER}
        sources: Counter[str] = Counter()
        statuses: dict[str, Counter[str]] = {key: Counter() for key in CASE_ORDER}
        for index in range(args.calls):
            case = CASE_ORDER[index % 4]
            elapsed, card = timed_post(client, "/api/check", payloads[case])
            final_ms.append(elapsed)
            per_case[case].append(elapsed)
            sources[card["source"]] += 1
            statuses[case][card["status"]] += 1

        print(summarize("rules card", rules_ms, 200))
        print(summarize("final card", final_ms, 3000))
        for case in CASE_ORDER:
            values = per_case[case]
            print(
                f"  {case}: n={len(values)} p50={percentile(values, 50):.0f} ms "
                f"p95={percentile(values, 95):.0f} ms statuses={dict(statuses[case])}"
            )
        valid = sources["rules+model"]
        print(
            f"valid model output (rules+model cards): {valid}/{args.calls} "
            f"= {valid / args.calls:.1%} (NFR-012 >= 95%: "
            f"{'met' if valid / args.calls >= 0.95 else 'MISSED'}; any attempt, see docstring)"
        )
        print(f"sources={dict(sources)}")

        if args.cold_start:
            cold_start(client, ollama, config.model, payloads["A"])


def cold_start(
    client: httpx.Client, ollama: httpx.Client, model: str, payload: dict[str, Any]
) -> None:
    """Unload only ``model`` (keep_alive 0), then time the first check without warm-up."""
    unload = ollama.post("/api/generate", json={"model": model, "keep_alive": 0})
    if unload.status_code != 200:
        print(f"cold start skipped: unload returned HTTP {unload.status_code}")
        return
    for _ in range(40):
        loaded = ollama.get("/api/ps").json().get("models", [])
        if not any(m.get("name") == model for m in loaded):
            break
        time.sleep(0.25)
    else:
        print("cold start skipped: model still loaded after unload")
        return
    elapsed, card = timed_post(client, "/api/check", payload)
    print(f"cold start: first /api/check after unload = {elapsed:.0f} ms source={card['source']}")
    elapsed, card = timed_post(client, "/api/check", payload)
    print(f"  next call = {elapsed:.0f} ms source={card['source']}")


if __name__ == "__main__":
    main()
