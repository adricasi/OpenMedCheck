"""FastAPI app: page, rules-only check API and RFC 9457 problem+json errors."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from openmedcheck.catalog_api import router as catalog_router
from openmedcheck.check_service import final_card, rules_card
from openmedcheck.config import Config, is_loopback_host
from openmedcheck.contracts import (
    MAX_BODY_BYTES,
    CheckRequest,
    DecisionCard,
    FieldError,
    ProblemDetails,
)
from openmedcheck.logging_setup import LOGGER_NAME, log_event
from openmedcheck.model_client import ModelClient, ModelHealth, OllamaClient

LOGGER = logging.getLogger(f"{LOGGER_NAME}.web")
PROBLEM_JSON = "application/problem+json"
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_PACKAGE_DIR = Path(__file__).parent


def problem_response(problem: ProblemDetails) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(mode="json", exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_JSON,
    )


def _field_errors(error: ValidationError) -> list[FieldError]:
    # Omits the offending input value (patient data, NFR-002) and never echoes
    # client-chosen keys: unknown fields are reported as "<parent>.<unknown field>".
    errors = []
    for item in error.errors():
        loc = item["loc"][:-1] if item["type"] == "extra_forbidden" else item["loc"]
        parts = [str(part) for part in loc]
        if item["type"] == "extra_forbidden":
            parts.append("<unknown field>")
        errors.append(FieldError(field=".".join(parts), message=item["msg"]))
    return errors


def _content_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";")[0].strip().lower()


def _unsupported_media_type() -> JSONResponse:
    return problem_response(
        ProblemDetails(
            title="Unsupported media type",
            status=415,
            detail="Content-Type must be application/json.",
        )
    )


async def _read_limited_body(request: Request) -> bytes | None:
    """Body bytes, or None once it exceeds the limit; stops reading at the limit (NFR-001).

    Counts streamed chunks so a chunked or Content-Length-less body is never buffered whole.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


_HOST_HEADER = re.compile(r"(?P<host>\[[0-9a-f:.]+\]|[a-z0-9.-]+)(?::\d{1,5})?")


def _request_hostname(host_header: str) -> str:
    """Host header without its port, lower-cased; keeps the brackets of an IPv6 literal."""
    match = _HOST_HEADER.fullmatch(host_header.strip().lower())
    return match.group("host") if match else ""


async def _read_check_request(request: Request) -> CheckRequest | JSONResponse:
    """Parse the body once, at the edge: 415, 413, then 422 with field errors."""
    if _content_type(request) != "application/json":
        return _unsupported_media_type()
    body = await _read_limited_body(request)
    if body is None:
        return problem_response(
            ProblemDetails(
                title="Request body too large",
                status=413,
                detail=f"The request body must not exceed {MAX_BODY_BYTES} bytes.",
            )
        )
    try:
        return CheckRequest.model_validate_json(body)
    except ValidationError as error:
        return problem_response(
            ProblemDetails(
                title="Invalid request",
                status=422,
                detail="The request failed validation and was not evaluated.",
                errors=_field_errors(error),
            )
        )


def create_app(config: Config | None = None, model_client: ModelClient | None = None) -> FastAPI:
    """Build the app; ``model_client`` is injected in tests, else Ollama from ``config``."""
    config = config or Config()
    injected = model_client
    if model_client is None:
        model_client = OllamaClient(
            config.ollama_url, config.model, deadline_s=config.model_timeout_s
        )
    owns_client = injected is None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owns_client and isinstance(model_client, OllamaClient):
                model_client.close()

    app = FastAPI(
        title="OpenMedCheck",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    allowed_hosts = {"127.0.0.1", "localhost", "[::1]"}
    if config.allow_nonlocal and not is_loopback_host(config.host):
        host = config.host.lower().strip("[]")
        allowed_hosts.add(f"[{host}]" if ":" in host else host)

    @app.middleware("http")
    async def _trusted_host(request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Registered first, so it runs inside the header and error middlewares below and its
        # rejection is a problem+json response that still carries the security headers.
        if _request_hostname(request.headers.get("host", "")) not in allowed_hosts:
            return problem_response(
                ProblemDetails(
                    title="Invalid host header",
                    status=400,
                    detail="The Host header is not an allowed host.",
                )
            )
        return await call_next(request)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    templates = Jinja2Templates(directory=_PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=_PACKAGE_DIR / "static"), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> Response:
        return problem_response(ProblemDetails(title=str(exc.detail), status=exc.status_code))

    @app.middleware("http")
    async def _unexpected_error(request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Caught here, not by an Exception handler: Starlette re-raises those and uvicorn
        # would then log the traceback, which can carry patient data (NFR-002).
        try:
            return await call_next(request)
        except Exception:
            return problem_response(ProblemDetails(title="Internal server error", status=500))

    app.include_router(catalog_router)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html")

    @app.post("/api/check/rules", response_model=DecisionCard)
    async def check_rules(request: Request) -> Any:
        parsed = await _read_check_request(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        return rules_card(parsed)

    @app.post("/api/check", response_model=DecisionCard)
    async def check(request: Request) -> Any:
        parsed = await _read_check_request(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        # The model client blocks (httpx): keep it off the event loop.
        return await run_in_threadpool(final_card, parsed, model_client)

    @app.get("/api/model/health")
    async def model_health() -> dict[str, str]:
        try:
            state = await run_in_threadpool(model_client.health)
        except Exception:
            state = ModelHealth.UNAVAILABLE  # a failing probe means unavailable, not a 500
        return {"status": state.value, "model": config.model}

    warmup = _WarmUp()

    @app.post("/api/model/warmup", status_code=202)
    async def model_warmup(request: Request, background: BackgroundTasks) -> Any:
        """Start loading the model without blocking (REQ-014); idempotent, never raises."""
        # JSON-only: a cross-origin page can't send this without a CORS preflight we never answer.
        if _content_type(request) != "application/json":
            return _unsupported_media_type()
        try:
            state = await run_in_threadpool(model_client.health)
        except Exception:
            state = ModelHealth.UNAVAILABLE
        if state is ModelHealth.UNAVAILABLE:
            return {"status": ModelHealth.UNAVAILABLE.value}
        if state is ModelHealth.READY:
            return {"status": ModelHealth.READY.value}
        if warmup.try_start():
            background.add_task(warmup.run, model_client)
        return {"status": ModelHealth.WARMING.value}

    return app


class _WarmUp:
    """Single-flight guard so repeated warm-up requests start at most one model load."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False

    def try_start(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            return True

    def run(self, client: ModelClient) -> None:
        try:
            client.warm_up()
        except Exception:  # best effort: a failed warm-up only means the first check is slower
            log_event(LOGGER, "model_warmup_failed", level=logging.WARNING)
        finally:
            with self._lock:
                self._running = False
