from __future__ import annotations

from typing import Any

import pytest

from openmedcheck import __main__ as entry


def test_ac_011_4_main_refuses_to_start_on_non_loopback_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENMEDCHECK_HOST", "0.0.0.0")  # noqa: S104

    with pytest.raises(SystemExit, match="refusing to start"):
        entry.main()


def test_main_serves_on_loopback_with_access_log_off(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(entry.uvicorn, "run", lambda _app, **kwargs: calls.update(kwargs))
    monkeypatch.delenv("OPENMEDCHECK_HOST", raising=False)
    monkeypatch.delenv("OPENMEDCHECK_PORT", raising=False)

    entry.main()

    assert calls == {"host": "127.0.0.1", "port": 8000, "access_log": False}
