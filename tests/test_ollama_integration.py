"""Real-model integration tests (T-009; AC-003.4, AC-009.2). Local only: ``pytest -m ollama``.

These call a local Ollama with the configured Gemma tag and are excluded by default
(``addopts = -m 'not ollama'``) and in CI. They skip cleanly when Ollama or the model is absent.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from openmedcheck.check_service import final_card, rules_card
from openmedcheck.config import Config
from openmedcheck.contracts import CheckRequest, Order, Source, Status
from openmedcheck.model_client import ModelHealth, OllamaClient
from openmedcheck.presets import PRESETS

pytestmark = pytest.mark.ollama

RUNS = 10
MIN_PASSES = 9  # AC-003.4 / AC-009.2: at least 9 of 10 runs


@pytest.fixture(scope="module")
def ollama_client() -> Iterator[OllamaClient]:
    config = Config()
    client = OllamaClient(config.ollama_url, config.model, deadline_s=config.model_timeout_s)
    try:
        if client.health() is ModelHealth.UNAVAILABLE:
            pytest.skip(f"Ollama or model {config.model} is not available locally")
        if not client.warm_up():
            pytest.skip(f"model {config.model} could not be loaded")
        yield client
    finally:
        client.close()


def paracetamol_variant(request: CheckRequest) -> CheckRequest:
    order = Order(drug_id="paracetamol", dose_text="1 g", route="PO", frequency="every 8 hours")
    return request.model_copy(update={"order": order})


def test_ac_003_4_preset_a_rules_no_issue_final_blocked_with_paracetamol(
    ollama_client: OllamaClient,
) -> None:
    request = PRESETS["A"].request
    assert rules_card(request).status is Status.NO_ISSUE
    passes = 0
    for _ in range(RUNS):
        card = final_card(request, ollama_client)
        if (
            card.status is Status.BLOCKED
            and card.source is Source.RULES_MODEL
            and card.alternative is not None
            and card.alternative.drug_id == "paracetamol"
        ):
            passes += 1
    assert passes >= MIN_PASSES, f"BLOCKED with paracetamol in {passes}/{RUNS} runs"


def test_ac_009_2_preset_a_with_paracetamol_is_no_issue(ollama_client: OllamaClient) -> None:
    request = paracetamol_variant(PRESETS["A"].request)
    assert rules_card(request).status is Status.NO_ISSUE
    passes = sum(
        1 for _ in range(RUNS) if final_card(request, ollama_client).status is Status.NO_ISSUE
    )
    assert passes >= MIN_PASSES, f"NO_ISSUE in {passes}/{RUNS} runs"
