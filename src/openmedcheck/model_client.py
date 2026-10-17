"""Layer 2 model client: Ollama over httpx, strict output validation, retry and deadline.

REQ-003 (AC-003.1 to AC-003.3, AC-003.5), REQ-005, NFR-003, NFR-004. This module never
logs patient context or model text; callers get an outcome code and a short reason code.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import ValidationError, field_validator, model_validator

from openmedcheck import prompt
from openmedcheck.contracts import (
    ModelVerdict,
    Order,
    PatientContext,
    RulesVerdict,
    Status,
)

DEFAULT_DEADLINE_S = 10.0
MAX_ATTEMPTS = 2
MAX_RAW_CHARS = 4_000
MAX_HEADLINE_WORDS = 8
MAX_HEADLINE_CHARS = 60
MAX_RATIONALE_CHARS = 300
MAX_RATIONALE_SENTENCES = 2
OLLAMA_OPTIONS: dict[str, Any] = {"temperature": 0, "num_predict": 400}
OLLAMA_KEEP_ALIVE = "10m"
CONNECT_TIMEOUT_S = 2.0

Clock = Callable[[], float]


class ModelOutcome(StrEnum):
    """NFR-007 ``model_outcome`` values."""

    OK = "ok"
    INVALID = "invalid"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class ModelTimeout(Exception):  # noqa: N818 - domain name, not an error suffix
    """The model did not answer within the time left in the deadline."""


class ModelUnavailable(Exception):  # noqa: N818 - domain name, not an error suffix
    """The model server is unreachable or answered with an error status."""


class InvalidModelOutput(ValueError):  # noqa: N818 - domain name, not an error suffix
    """Model output failed validation; ``reason`` is a short code, never model text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ModelOutput(ModelVerdict):
    """``ModelVerdict`` plus the model-output limits of AC-001.2 (parsed from the model only)."""

    @field_validator("headline")
    @classmethod
    def _headline_limits(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("headline is blank")
        if len(value.split()) > MAX_HEADLINE_WORDS or len(value) > MAX_HEADLINE_CHARS:
            raise ValueError("headline too long")
        return value

    @field_validator("rationale")
    @classmethod
    def _rationale_limits(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale is blank")
        if len(value) > MAX_RATIONALE_CHARS:
            raise ValueError("rationale too long")
        if len(_SENTENCE_END.findall(value.strip())) > MAX_RATIONALE_SENTENCES:
            raise ValueError("rationale has too many sentences")
        return value

    @model_validator(mode="after")
    def _conflict_type_when_escalating(self) -> ModelOutput:
        if self.status is not Status.NO_ISSUE and self.conflict_type is None:
            raise ValueError("conflict_type required unless NO_ISSUE")
        return self


@dataclass(frozen=True)
class ModelRequest:
    """Everything the model step needs (AC-003.1)."""

    context: PatientContext = field(repr=False)
    order: Order
    rules_verdict: RulesVerdict
    allowed_alternatives: tuple[str, ...]
    drug_list: tuple[str, ...]


@dataclass(frozen=True)
class ModelResult:
    """Outcome of the model step; ``verdict`` is set only when ``outcome`` is ``OK``."""

    outcome: ModelOutcome
    verdict: ModelVerdict | None = field(repr=False)
    attempts: int
    latency_ms: int
    invalid_reason: str | None = None


class ModelClient(Protocol):
    """Port used by the check service; never raises for model failures."""

    def assess(self, request: ModelRequest) -> ModelResult: ...


# --- content validation (AC-003.5) -------------------------------------------------------

_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
_DOSE_UNITS = (
    r"milligrams?|micrograms?|millilit(?:er|re)s?|lit(?:er|re)s?|international\s+units?"
    r"|mgs?|mcgs?|µgs?|μgs?|ugs?|gr?|grams?|cc|l|iu|ui|u|units?|meq|mmol|mol|%"
    r"|tablets?|tabs?|caps?|capsules?|capsulas?|sachets?|patch(?:es)?|parches?"
    r"|comprimidos?|gotas|drops?|puffs?|ampoules?|ampollas?|vials?"
)
_NUMBER_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty|fifty|hundred|thousand"
    r"|half|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|medio|media|cien|mil"
)
_RANGE = r"\d+(?:[.,]\d+)?(?:\s*[-\u2013/]\s*\d+(?:[.,]\d+)?)?"
_DOSE_PATTERNS = (
    # "400 mg", "5-10 ml", "2 tablets"; lab units (mg/dL, mL/min, mmol/L) are not doses.
    re.compile(
        rf"(?<![\d.,]){_RANGE}\s*(?:mls?(?![a-z])(?!\s*/\s*min\b)|(?:{_DOSE_UNITS})(?![a-z]))"
        r"(?!\s*/\s*(?:dl|l)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_NUMBER_WORDS})(?:[\s-]+(?:{_NUMBER_WORDS}))*\s*(?:{_DOSE_UNITS})(?![a-z])",
        re.IGNORECASE,
    ),
    re.compile(rf"\b(?:every|cada|q)\s*{_RANGE}\s*(?:h|hours?|hrs?|horas?)\b", re.IGNORECASE),
    re.compile(r"\bq\d+(?:\s*-\s*\d+)?h\b", re.IGNORECASE),
    re.compile(rf"\b{_RANGE}\s*(?:x|times)\s*(?:a|per|/)?\s*(?:day|daily|d[ií]a)\b", re.IGNORECASE),
    re.compile(
        rf"\b(?:once|twice|(?:{_NUMBER_WORDS})\s+times)\s*(?:a\s+|per\s+)?(?:day|daily|d[ií]a)\b"
        r"|\b(?:bid|tid|qid|qds|tds|qd|od|prn)\b",
        re.IGNORECASE,
    ),
)
_BANNED_WORDS = re.compile(
    r"\b(?:approv\w*|aprob\w*|safe\w*|segur\w*|diagnos\w*|diagnost\w*|effective\w*"
    r"|efficac\w*|guarantee\w*|proven|cures?|cured|ok\s+to\s+(?:give|prescribe|continue))\b",
    re.IGNORECASE,
)
# Exact words that share a banned prefix but are plain nouns the prompt itself uses.
_BANNED_WORD_EXCEPTIONS = frozenset({"safety", "diagnoses"})


def _normalize(text: str) -> str:
    """Casefold, drop accents and invisible format characters before matching."""
    decomposed = unicodedata.normalize("NFKD", text)
    kept = (ch for ch in decomposed if unicodedata.category(ch) not in {"Mn", "Cf"})
    return "".join(kept).casefold()


def _drug_name_patterns(drug_id: str) -> list[re.Pattern[str]]:
    parts = [part for part in re.split(r"[_\-\s]+", drug_id.casefold()) if part]
    full = r"[\s_\-]*".join(re.escape(part) for part in parts)
    variants = {full, *(re.escape(part) for part in parts if len(part) >= 5)}
    return [re.compile(rf"(?<![a-z]){variant}(?![a-z])") for variant in sorted(variants)]


def content_violation(
    text: str,
    *,
    allowed_drug_ids: Sequence[str],
    drug_list: Sequence[str],
) -> str | None:
    """Reason code if ``text`` has a dose pattern, another drug name or a banned word."""
    normalized = _normalize(text)
    if any(ord(ch) > 127 and ch.isalpha() for ch in normalized):
        return "content:non_ascii"  # confusables (Cyrillic/Greek look-alikes) could spell anything
    if any(pattern.search(normalized) for pattern in _DOSE_PATTERNS):
        return "content:dose_pattern"
    exempt = {part for drug in allowed_drug_ids for part in _drug_name_patterns_keys(drug)}
    for drug_id in drug_list:
        if drug_id in allowed_drug_ids:
            continue
        for pattern in _drug_name_patterns(drug_id):
            if pattern.pattern not in exempt and pattern.search(normalized):
                return "content:other_drug"
    if any(
        match.group().casefold() not in _BANNED_WORD_EXCEPTIONS
        for match in _BANNED_WORDS.finditer(normalized)
    ):
        return "content:banned_word"
    return None


def _drug_name_patterns_keys(drug_id: str) -> set[str]:
    return {pattern.pattern for pattern in _drug_name_patterns(drug_id)}


def _schema_reason(loc: tuple[int | str, ...], error_type: str) -> str:
    """Reason code from a pydantic error; model-chosen key names are never echoed."""
    if not loc:
        return f"schema:root:{error_type}"
    field_name = str(loc[0])
    if field_name in ModelOutput.model_fields:
        return f"schema:{field_name}:{error_type}"
    return f"schema:extra:{error_type}" if error_type == "extra_forbidden" else "schema:root"


def parse_model_output(raw: str, request: ModelRequest) -> ModelVerdict:
    """Strictly parse and validate raw model content, or raise ``InvalidModelOutput``.

    Order: size, JSON schema and limits, alternative in the allowed list, content check.
    """
    if len(raw) > MAX_RAW_CHARS:
        raise InvalidModelOutput("too_long")
    try:
        verdict = ModelOutput.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        first = exc.errors(include_input=False, include_url=False)[0]
        raise InvalidModelOutput(_schema_reason(first["loc"], first["type"])) from None
    if verdict.alternative_drug_id not in (*request.allowed_alternatives, None):
        raise InvalidModelOutput("bad_alternative")
    allowed_names = [request.order.drug_id]
    if verdict.alternative_drug_id is not None:
        allowed_names.append(verdict.alternative_drug_id)
    for text in (verdict.headline, verdict.rationale):
        reason = content_violation(
            text, allowed_drug_ids=allowed_names, drug_list=request.drug_list
        )
        if reason is not None:
            raise InvalidModelOutput(reason)
    return verdict


# --- attempt / retry / deadline ----------------------------------------------------------

Attempt = Callable[[ModelRequest, float], str]


def run_assessment(
    attempt: Attempt,
    request: ModelRequest,
    *,
    deadline_s: float,
    clock: Clock,
) -> ModelResult:
    """One attempt plus one retry on invalid output, inside one total deadline (AC-003.3).

    ``attempt(request, remaining_s)`` returns raw model content or raises ``ModelTimeout`` /
    ``ModelUnavailable``. A valid answer that arrives after the deadline counts as a timeout.
    """
    start = clock()

    def result(
        outcome: ModelOutcome,
        attempts: int,
        verdict: ModelVerdict | None = None,
        reason: str | None = None,
    ) -> ModelResult:
        return ModelResult(
            outcome=outcome,
            verdict=verdict,
            attempts=attempts,
            latency_ms=round((clock() - start) * 1000),
            invalid_reason=reason,
        )

    attempts = 0
    reason: str | None = None
    for _ in range(MAX_ATTEMPTS):
        remaining = deadline_s - (clock() - start)
        if remaining <= 0:
            return result(ModelOutcome.TIMEOUT, attempts, reason=reason)
        attempts += 1
        try:
            raw = attempt(request, remaining)
        except ModelTimeout:
            return result(ModelOutcome.TIMEOUT, attempts, reason=reason)
        except ModelUnavailable:
            return result(ModelOutcome.UNAVAILABLE, attempts, reason=reason)
        except AssertionError:
            raise  # a test double's own misuse must stay loud
        except Exception:
            # Fail-safe boundary (REQ-005): never keep the message, it may carry context.
            return result(ModelOutcome.UNAVAILABLE, attempts, reason="exception")
        if clock() - start > deadline_s:
            return result(ModelOutcome.TIMEOUT, attempts, reason=reason)
        try:
            verdict = parse_model_output(raw, request)
        except InvalidModelOutput as exc:
            reason = exc.reason
            continue
        return result(ModelOutcome.OK, attempts, verdict=verdict)
    return result(ModelOutcome.INVALID, attempts, reason=reason)


# --- Ollama ------------------------------------------------------------------------------


class OllamaClient:
    """``ModelClient`` backed by a local Ollama server (ADR 0004, T-001 spike request)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        deadline_s: float = DEFAULT_DEADLINE_S,
        transport: httpx.BaseTransport | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self._model = model
        self._deadline_s = deadline_s
        self._clock = clock
        # trust_env=False: never route the loopback call through a proxy from the environment.
        self._http = httpx.Client(base_url=base_url, transport=transport, trust_env=False)

    def close(self) -> None:
        self._http.close()

    def assess(self, request: ModelRequest) -> ModelResult:
        return run_assessment(self._chat, request, deadline_s=self._deadline_s, clock=self._clock)

    def _chat(self, request: ModelRequest, remaining_s: float) -> str:
        try:
            payload = self._payload(request)
            response = self._http.post(
                "/api/chat",
                json=payload,
                timeout=httpx.Timeout(
                    connect=min(remaining_s, CONNECT_TIMEOUT_S),
                    read=remaining_s,
                    write=remaining_s,
                    pool=CONNECT_TIMEOUT_S,
                ),
            )
        except httpx.ConnectTimeout:
            raise ModelUnavailable from None
        except httpx.TimeoutException:
            raise ModelTimeout from None
        except (httpx.HTTPError, UnicodeError, ValueError):
            raise ModelUnavailable from None
        if response.status_code != httpx.codes.OK:
            raise ModelUnavailable
        return _message_content(response)

    def _payload(self, request: ModelRequest) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": prompt.build_messages(
                request.context,
                request.order,
                request.rules_verdict,
                request.allowed_alternatives,
            ),
            "stream": False,
            "think": False,  # mandatory: thinking eats the token budget (T-001 spike)
            "format": prompt.build_schema(request.allowed_alternatives),
            "options": OLLAMA_OPTIONS,
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }


def _message_content(response: httpx.Response) -> str:
    """Model text from an Ollama chat response; anything malformed yields '' (invalid)."""
    try:
        body = response.json()
        content = body["message"]["content"]
    except (ValueError, KeyError, TypeError):
        return ""
    return content if isinstance(content, str) else ""


# --- fake for tests ----------------------------------------------------------------------


class ManualClock:
    """Deterministic clock for deadline tests; ``advance`` replaces real sleeping."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


_Immediate = str | dict[str, Any] | ModelVerdict | Exception


@dataclass(frozen=True)
class FakeDelay:
    """Scripted response that takes ``seconds`` of fake time before it is returned."""

    seconds: float
    response: _Immediate


FakeResponse = _Immediate | FakeDelay


@dataclass
class FakeModelClient:
    """Scripted ``ModelClient`` using the real retry, deadline and validation path.

    Each script item answers one attempt: raw text, a dict or ``ModelVerdict`` (serialised
    to JSON), ``ModelTimeout`` / ``ModelUnavailable`` to raise, or ``FakeDelay``.
    """

    script: list[FakeResponse]
    deadline_s: float = DEFAULT_DEADLINE_S
    clock: ManualClock = field(default_factory=ManualClock)
    requests: list[ModelRequest] = field(default_factory=list)

    def assess(self, request: ModelRequest) -> ModelResult:
        self.requests.append(request)
        return run_assessment(self._attempt, request, deadline_s=self.deadline_s, clock=self.clock)

    def _attempt(self, request: ModelRequest, remaining_s: float) -> str:  # noqa: ARG002
        if not self.script:
            raise AssertionError("FakeModelClient script exhausted")
        scripted = self.script.pop(0)
        item: _Immediate
        if isinstance(scripted, FakeDelay):
            if scripted.seconds > remaining_s:
                self.clock.advance(remaining_s)
                raise ModelTimeout
            self.clock.advance(scripted.seconds)
            item = scripted.response
        else:
            item = scripted
        if isinstance(item, Exception):
            raise item
        if isinstance(item, ModelVerdict):
            return item.model_dump_json()
        if isinstance(item, dict):
            return json.dumps(item)
        return item
