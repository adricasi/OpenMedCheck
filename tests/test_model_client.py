"""Model client: validation (AC-001.2, AC-003.2, AC-003.5), retry/deadline (AC-003.3, NFR-004),
fail-safe outcomes (REQ-005, NFR-003) and the Ollama request (T-001 spike)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from openmedcheck.contracts import ModelVerdict
from openmedcheck.model_client import (
    FakeDelay,
    FakeModelClient,
    InvalidModelOutput,
    ManualClock,
    ModelOutcome,
    ModelTimeout,
    ModelUnavailable,
    OllamaClient,
    content_violation,
    parse_model_output,
)
from tests.model_helpers import make_request, verdict_json


def _verdict_fields() -> dict[str, Any]:
    """The fake model output without the note answers, which ``ModelVerdict`` does not have."""
    return {key: value for key, value in verdict_json().items() if not key.startswith("note_")}


REQUEST = make_request()


# --- schema validation -------------------------------------------------------------------


def test_ac_003_2_valid_output_parses() -> None:
    verdict = parse_model_output(json.dumps(verdict_json()), REQUEST)
    assert verdict.status.value == "BLOCKED"
    assert verdict.alternative_drug_id == "paracetamol"


@pytest.mark.parametrize(
    ("raw", "reason_prefix"),
    [
        ("not json", "schema:root:json_invalid"),
        ("[]", "schema:root:model_type"),
        (json.dumps({"status": "BLOCKED"}), "schema:risk_level:missing"),
        (json.dumps(verdict_json(extra="x")), "schema:extra:extra_forbidden"),
        (json.dumps(verdict_json(status="APPROVED")), "schema:status:enum"),
        (json.dumps(verdict_json(renal_adjustment_required="yes")), "schema:renal"),
        (json.dumps(verdict_json(conflict_type="MADE_UP")), "schema:conflict_type"),
        (json.dumps(verdict_json(conflict_type=None)), "schema:root:value_error"),
        (json.dumps(verdict_json(alternative_drug_id="morphine")), "bad_alternative"),
        ("x" * 4_001, "too_long"),
    ],
)
def test_ac_003_2_invalid_output_is_rejected_with_code(raw: str, reason_prefix: str) -> None:
    with pytest.raises(InvalidModelOutput) as caught:
        parse_model_output(raw, REQUEST)
    assert caught.value.reason.startswith(reason_prefix)


def test_ac_003_2_alternative_must_be_in_this_requests_allowed_list() -> None:
    request = make_request(allowed=())
    with pytest.raises(InvalidModelOutput, match="bad_alternative"):
        parse_model_output(json.dumps(verdict_json()), request)
    parse_model_output(json.dumps(verdict_json(alternative_drug_id=None)), request)


def test_no_issue_does_not_need_a_conflict_type() -> None:
    raw = json.dumps(
        verdict_json(
            status="NO_ISSUE", risk_level="LOW", conflict_type=None, alternative_drug_id=None
        )
    )
    assert parse_model_output(raw, REQUEST).conflict_type is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"headline": "one two three four five six seven eight nine"},
        {"headline": "x" * 61},
        {"headline": "   "},
        {"rationale": "x" * 301},
        {"rationale": "   "},
        {"rationale": "First sentence. Second sentence. Third sentence."},
    ],
)
def test_ac_001_2_text_limits_are_enforced(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvalidModelOutput, match="schema:"):
        parse_model_output(json.dumps(verdict_json(**overrides)), REQUEST)


def test_ac_001_2_limits_accept_the_boundary() -> None:
    headline = "one two three four five six seven eight"
    rationale = "Short one. Short two."
    parse_model_output(json.dumps(verdict_json(headline=headline, rationale=rationale)), REQUEST)


def test_model_verdict_is_immutable() -> None:
    verdict = ModelVerdict.model_validate_json(json.dumps(_verdict_fields()))
    with pytest.raises(ValueError, match="frozen"):
        verdict.headline = "changed"  # type: ignore[misc]


# --- content check (AC-003.5) -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Give 400 mg now",
        "Use 5 ml",
        "Take 2 tablets",
        "1,5 g daily",
        "every 8 hours",
        "Cada 8 horas",
        "q6h",
        "3 times a day",
        "5 mg/kg",
        "500 milligrams",
        "IV400mg",
        "_400 mg",
        "1 mg/min",
        "5 mcg/min",
        "two micrograms",
        "five hundred milligrams",
        "1 gram",
        "10 millilitres",
        "2 liters",
        "10 international units",
        "5 units",
        "5 mgs",
        "5-10 ml",
        "50 mg/min",
        "one tablet",
        "10 U",
        "twice daily",
        "three times daily",
        "every 6-8 hours",
        "q6-8h",
        "BID",
        "tid",
        "qid",
        "qds",
        "tds",
        "od",
        "prn",
    ],
)
def test_ac_003_5_dose_patterns_are_rejected(text: str) -> None:
    assert (
        content_violation(text, allowed_drug_ids=["ibuprofen"], drug_list=("ibuprofen",))
        == "content:dose_pattern"
    )


@pytest.mark.parametrize(
    "text",
    ["eGFR 22 mL/min is low", "Creatinine 2.6 mg/dL", "Potassium 5.1 mmol/L", "67 y, 82 kg"],
)
def test_ac_003_5_lab_values_are_not_dose_patterns(text: str) -> None:
    assert content_violation(text, allowed_drug_ids=["ibuprofen"], drug_list=("ibuprofen",)) is None


def test_ac_003_5_other_drug_names_are_rejected_but_ordered_and_alternative_are_allowed() -> None:
    drugs = ("ibuprofen", "paracetamol", "aspirin", "amoxicillin_clavulanate")
    allowed = ["ibuprofen", "paracetamol"]
    assert (
        content_violation("Ibuprofen is risky", allowed_drug_ids=allowed, drug_list=drugs) is None
    )
    assert content_violation("Try paracetamol", allowed_drug_ids=allowed, drug_list=drugs) is None
    for text in ("Patient takes ASPIRIN", "Avoid amoxicillin-clavulanate", "Has clavulanate"):
        assert (
            content_violation(text, allowed_drug_ids=allowed, drug_list=drugs)
            == "content:other_drug"
        )
    # whole words only: "aspirins" and "unaspirinated" style substrings do not mask a hit
    assert content_violation("Nonaspirinic care", allowed_drug_ids=allowed, drug_list=drugs) is None


def test_ac_003_5_shared_name_part_of_an_allowed_drug_is_not_flagged() -> None:
    drugs = ("amoxicillin_clavulanate", "amoxicillin")
    assert (
        content_violation(
            "amoxicillin is fine", allowed_drug_ids=["amoxicillin_clavulanate"], drug_list=drugs
        )
        is None
    )


@pytest.mark.parametrize(
    "text",
    [
        "This order is approved",
        "Safe to prescribe",
        "It is safe",
        "Suggests a diagnosis of ACS",
        "We diagnose ACS",
        "Orden aprobada",
        "Diagnóstico probable",
        "Highly effective choice",
        "Proven benefit",
        "s​afe",
    ],
)
def test_ac_003_5_banned_words_are_rejected(text: str) -> None:
    assert (
        content_violation(text, allowed_drug_ids=["ibuprofen"], drug_list=("ibuprofen",))
        == "content:banned_word"
    )


@pytest.mark.parametrize(
    "text",
    ["\u0455\u0430f\u0435", "500 m\u0433", "ibupr\u043ffen", "\u03bfk", "caf\u00e9 \u4e2d"],
)
def test_ac_003_5_confusable_non_ascii_letters_are_rejected(text: str) -> None:
    assert (
        content_violation(text, allowed_drug_ids=["ibuprofen"], drug_list=("ibuprofen",))
        == "content:non_ascii"
    )


def test_ac_003_5_accented_latin_passes_after_stripping_marks() -> None:
    text = "Dolor tor\u00e1cico, revisi\u00f3n \u00fatil"
    assert content_violation(text, allowed_drug_ids=["ibuprofen"], drug_list=("ibuprofen",)) is None


@pytest.mark.parametrize("key", ["<img src=x>", "John Doe has HIV", "SECRET-KEY-9917", "headline "])
def test_nfr_002_hostile_extra_key_is_not_echoed(
    key: str, caplog: pytest.LogCaptureFixture
) -> None:
    raw = json.dumps({**verdict_json(), key: 1})
    with caplog.at_level(logging.DEBUG), pytest.raises(InvalidModelOutput) as caught:
        parse_model_output(raw, REQUEST)
    assert caught.value.reason == "schema:extra:extra_forbidden"
    assert key.strip() not in caught.value.reason
    assert key not in caplog.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"headline": "Give 400 mg instead"},
        {"rationale": "Aspirin plus NSAID raises risk."},
        {"rationale": "Looks safe to continue."},
    ],
)
def test_ac_003_5_content_violations_make_the_output_invalid(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvalidModelOutput, match="content:"):
        parse_model_output(json.dumps(verdict_json(**overrides)), REQUEST)


def test_ac_003_5_selected_alternative_may_be_named() -> None:
    raw = json.dumps(verdict_json(rationale="Paracetamol avoids the conflict."))
    parse_model_output(raw, REQUEST)


# --- retry and deadline with the fake (AC-003.3, AC-005.1, NFR-003, NFR-004) --------------


def test_valid_first_attempt() -> None:
    fake = FakeModelClient([verdict_json()])
    result = fake.assess(REQUEST)
    assert result.outcome is ModelOutcome.OK
    assert result.attempts == 1
    assert result.verdict is not None


def test_ac_003_3_invalid_then_valid_retries_once() -> None:
    fake = FakeModelClient(["garbage", verdict_json()])
    result = fake.assess(REQUEST)
    assert result.outcome is ModelOutcome.OK
    assert result.attempts == 2


def test_ac_003_3_invalid_twice_is_invalid_outcome_with_reason_code() -> None:
    fake = FakeModelClient(["garbage", verdict_json(headline="Give 5 mg")])
    result = fake.assess(REQUEST)
    assert result.outcome is ModelOutcome.INVALID
    assert result.verdict is None
    assert result.attempts == 2
    assert result.invalid_reason == "content:dose_pattern"


def test_nfr_004_slow_first_attempt_leaves_no_time_for_retry() -> None:
    fake = FakeModelClient([FakeDelay(10.0, "garbage"), verdict_json()])
    result = fake.assess(REQUEST)
    assert result.outcome is ModelOutcome.TIMEOUT
    assert result.attempts == 1
    assert fake.script == [verdict_json()]  # retry never started


def test_nfr_004_deadline_is_shared_across_attempt_and_retry() -> None:
    fake = FakeModelClient([FakeDelay(4.0, "garbage"), FakeDelay(7.0, verdict_json())])
    result = fake.assess(REQUEST)
    assert result.outcome is ModelOutcome.TIMEOUT
    assert result.attempts == 2
    assert result.latency_ms == 10_000
    assert result.invalid_reason == "schema:root:json_invalid"


def test_nfr_004_fast_attempts_within_deadline_succeed() -> None:
    fake = FakeModelClient([FakeDelay(4.0, "garbage"), FakeDelay(5.0, verdict_json())])
    result = fake.assess(REQUEST)
    assert result.outcome is ModelOutcome.OK
    assert result.latency_ms == 9_000


def test_nfr_004_answer_arriving_after_the_deadline_is_a_timeout() -> None:
    clock = ManualClock()

    def late(_: Any, __: float) -> str:
        clock.advance(11.0)
        return json.dumps(verdict_json())

    from openmedcheck.model_client import run_assessment

    result = run_assessment(late, REQUEST, deadline_s=10.0, clock=clock)
    assert result.outcome is ModelOutcome.TIMEOUT


def test_nfr_004_deadline_is_configurable() -> None:
    fake = FakeModelClient([FakeDelay(2.0, verdict_json())], deadline_s=1.0)
    assert fake.assess(REQUEST).outcome is ModelOutcome.TIMEOUT


def test_nfr_003_unreachable_is_unavailable() -> None:
    fake = FakeModelClient([ModelUnavailable()])
    result = fake.assess(REQUEST)
    assert result.outcome is ModelOutcome.UNAVAILABLE
    assert result.verdict is None


def test_timeout_exception_is_timeout_outcome() -> None:
    assert FakeModelClient([ModelTimeout()]).assess(REQUEST).outcome is ModelOutcome.TIMEOUT


def test_fake_accepts_model_verdict_and_records_requests() -> None:
    fake = FakeModelClient([ModelVerdict.model_validate_json(json.dumps(_verdict_fields()))])
    assert fake.assess(REQUEST).outcome is ModelOutcome.OK
    assert fake.requests == [REQUEST]


def test_fake_script_exhausted_is_a_loud_test_error() -> None:
    with pytest.raises(AssertionError, match="exhausted"):
        FakeModelClient([]).assess(REQUEST)


# --- OllamaClient over httpx.MockTransport ------------------------------------------------


def _chat_body(content: object) -> dict[str, Any]:
    return {"model": "gemma4:e4b", "message": {"role": "assistant", "content": content}}


def _client(
    handler: Any, *, clock: ManualClock | None = None, deadline_s: float = 10.0
) -> OllamaClient:
    return OllamaClient(
        "http://127.0.0.1:11434",
        "gemma4:e4b",
        deadline_s=deadline_s,
        transport=httpx.MockTransport(handler),
        clock=clock or ManualClock(),
    )


def test_ac_003_1_request_matches_the_spike_contract() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_chat_body(json.dumps(verdict_json())))

    result = _client(handler).assess(REQUEST)

    assert result.outcome is ModelOutcome.OK
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/chat"
    body = json.loads(request.content)
    assert body["model"] == "gemma4:e4b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["keep_alive"] == "10m"
    assert body["options"] == {"temperature": 0, "num_predict": 800}
    assert body["format"]["properties"]["alternative_drug_id"]["enum"] == [
        "paracetamol",
        "metamizole",
        None,
    ]
    assert [message["role"] for message in body["messages"]] == ["system", "user"]


def test_per_attempt_timeout_is_the_time_left_in_the_deadline() -> None:
    clock = ManualClock()
    timeouts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        clock.advance(3.0)
        content = "garbage" if len(timeouts) == 1 else json.dumps(verdict_json())
        return httpx.Response(200, json=_chat_body(content))

    result = _client(handler, clock=clock).assess(REQUEST)

    assert result.outcome is ModelOutcome.OK
    assert timeouts == [10.0, 7.0]


def test_ac_003_3_ollama_invalid_then_valid() -> None:
    contents = iter(["{}", json.dumps(verdict_json())])
    client = _client(lambda _: httpx.Response(200, json=_chat_body(next(contents))))
    result = client.assess(REQUEST)
    assert (result.outcome, result.attempts) == (ModelOutcome.OK, 2)


def test_ac_005_1_ollama_invalid_twice() -> None:
    client = _client(lambda _: httpx.Response(200, json=_chat_body("")))
    result = client.assess(REQUEST)
    assert (result.outcome, result.attempts) == (ModelOutcome.INVALID, 2)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, json=_chat_body(None)),
        httpx.Response(200, json=[1, 2]),
    ],
)
def test_malformed_ollama_bodies_count_as_invalid(response: httpx.Response) -> None:
    result = _client(lambda _: response).assess(REQUEST)
    assert result.outcome is ModelOutcome.INVALID


def test_nfr_003_connection_refused_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = _client(handler).assess(REQUEST)
    assert (result.outcome, result.attempts) == (ModelOutcome.UNAVAILABLE, 1)


def test_connect_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow connect", request=request)

    assert _client(handler).assess(REQUEST).outcome is ModelOutcome.UNAVAILABLE


@pytest.mark.parametrize("status", [404, 500, 503])
def test_error_status_is_unavailable(status: int) -> None:
    result = _client(lambda _: httpx.Response(status, json={"error": "model not found"})).assess(
        REQUEST
    )
    assert result.outcome is ModelOutcome.UNAVAILABLE


def test_nfr_004_read_timeout_is_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    result = _client(handler).assess(REQUEST)
    assert (result.outcome, result.attempts) == (ModelOutcome.TIMEOUT, 1)


def test_other_transport_errors_are_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("bad", request=request)

    assert _client(handler).assess(REQUEST).outcome is ModelOutcome.UNAVAILABLE


def test_close_closes_the_http_client() -> None:
    client = _client(lambda _: httpx.Response(200))
    client.close()
    with pytest.raises(RuntimeError):
        client._http.get("/")


# --- privacy (NFR-002): the model layer logs nothing --------------------------------------


def test_nfr_002_model_client_emits_no_logs(caplog: pytest.LogCaptureFixture) -> None:
    private_note = "SECRET-NOTE-TEXT-9917"
    request = make_request(ed_note=private_note)
    contents = iter(["garbage " + private_note, json.dumps(verdict_json(headline="Give 5 mg"))])
    client = _client(lambda _: httpx.Response(200, json=_chat_body(next(contents))))
    with caplog.at_level(logging.DEBUG):
        result = client.assess(request)
    assert result.outcome is ModelOutcome.INVALID
    assert private_note not in repr(result)
    assert not [r for r in caplog.records if r.name.startswith("openmedcheck")]


def test_req_005_unexpected_errors_become_unavailable_without_message() -> None:
    result = FakeModelClient([RuntimeError("SECRET-NOTE-TEXT")]).assess(REQUEST)
    assert result.outcome is ModelOutcome.UNAVAILABLE
    assert result.invalid_reason == "exception"
    assert "SECRET" not in repr(result)


def test_nfr_002_repr_of_request_and_result_hides_context_and_verdict() -> None:
    request = make_request(ed_note="SECRET-NOTE-TEXT-9917")
    result = FakeModelClient([verdict_json()]).assess(request)
    assert "SECRET-NOTE-TEXT-9917" not in repr(request)
    assert "NSAID conflicts" not in repr(result)


def test_closed_client_does_not_raise() -> None:
    client = _client(lambda _: httpx.Response(200))
    client.close()
    assert client.assess(REQUEST).outcome is ModelOutcome.UNAVAILABLE


@pytest.mark.parametrize(
    "text",
    [
        "safer option",
        "the safest choice",
        "safely given",
        "es seguro",
        "seguridad total",
        "was diagnosed",
        "diagnosing ACS",
        "a diagnosis",
        "approving",
        "aprobado",
        "efficacy shown",
        "effectively",
        "guaranteed",
    ],
)
def test_ac_010_2_banned_word_prefixes_are_rejected(text: str) -> None:
    assert (
        content_violation(text, allowed_drug_ids=["ibuprofen"], drug_list=("ibuprofen",))
        == "content:banned_word"
    )


@pytest.mark.parametrize("text", ["Drug safety review needed", "Checks orders against diagnoses"])
def test_ac_010_2_exact_exception_words_are_accepted(text: str) -> None:
    assert content_violation(text, allowed_drug_ids=["ibuprofen"], drug_list=("ibuprofen",)) is None


def test_ac_003_6_question_style_note_answers_become_findings() -> None:
    from openmedcheck.contracts import FindingKind

    raw = verdict_json(status="NO_ISSUE", risk_level="LOW", conflict_type=None)
    raw.update(
        note_acs_quote="Suspected ACS",
        note_gi_bleed_quote=None,
        note_medications=[{"drug_id": "aspirin", "quote": "On daily aspirin"}],
        note_allergies=[{"code": "PENICILLIN", "quote": "Penicillin allergy"}],
    )

    verdict = parse_model_output(json.dumps(raw), make_request())

    assert type(verdict) is ModelVerdict
    assert [(f.kind, f.code, f.quote) for f in verdict.note_findings] == [
        (FindingKind.CONDITION, "ACS", "Suspected ACS"),
        (FindingKind.MEDICATION, "aspirin", "On daily aspirin"),
        (FindingKind.ALLERGY, "PENICILLIN", "Penicillin allergy"),
    ]


def test_ac_003_5_quotes_are_not_content_checked_but_the_text_still_is() -> None:
    # A quote may repeat the doctor's own words, including a drug name; verify() later keeps it
    # only if it is verbatim in the note. Headline and rationale are still checked (AC-003.5).
    raw = verdict_json(status="NO_ISSUE", risk_level="LOW", conflict_type=None)
    raw["note_medications"] = [{"drug_id": "aspirin", "quote": "aspirin 100 mg daily"}]

    assert parse_model_output(json.dumps(raw), make_request()).note_findings

    raw["rationale"] = "Give aspirin 100 mg."
    with pytest.raises(InvalidModelOutput):
        parse_model_output(json.dumps(raw), make_request())
