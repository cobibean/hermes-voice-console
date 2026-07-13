from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def console_scope_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_CONSOLE_SCOPE_SECRET", "test-scope-secret-000000000000")
