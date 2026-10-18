"""Entry point: ``uv run openmedcheck`` serves the app on the configured loopback address."""

from __future__ import annotations

import os

import uvicorn

from openmedcheck.config import Config, ConfigError
from openmedcheck.logging_setup import configure_logging
from openmedcheck.web import create_app


def main() -> None:
    try:
        config = Config.from_env(os.environ)
    except ConfigError as error:
        raise SystemExit(f"openmedcheck: refusing to start: {error}") from error
    configure_logging()
    # Access log off: request lines must never reach logs with patient data (NFR-002).
    uvicorn.run(create_app(config), host=config.host, port=config.port, access_log=False)


if __name__ == "__main__":
    main()
