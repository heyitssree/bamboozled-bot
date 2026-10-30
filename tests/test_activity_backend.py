"""Smoke tests for the legacy Activity backend (replaced in Phase 3): hygiene items from Phase 1 only."""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = str(Path(__file__).resolve().parents[1] / "activity" / "backend")


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "activity.db"))
    monkeypatch.delenv("BAMBOOZLED_DEBUG", raising=False)
    monkeypatch.syspath_prepend(BACKEND)
    for name in ("config", "db", "main", "game_engine", "models", "question_service", "session_manager"):
        sys.modules.pop(name, None)
    return importlib.import_module("main")


def test_docs_are_off_by_default_and_startup_runs_via_lifespan(backend):
    with TestClient(backend.app) as client:           # entering the context runs the lifespan startup
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/health").status_code == 200
    assert Path(backend.settings.DB_PATH).exists()


def test_docs_are_on_with_debug(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("BAMBOOZLED_DEBUG", "1")
    monkeypatch.syspath_prepend(BACKEND)
    for name in ("config", "db", "main", "game_engine", "models", "question_service", "session_manager"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    with TestClient(main.app) as client:
        assert client.get("/docs").status_code == 200


def test_cors_is_not_a_wildcard(backend):
    assert "*" not in backend._cors_origins()


def test_no_on_event_handlers_left(backend):
    assert not backend.app.router.on_startup and not backend.app.router.on_shutdown


def test_game_over_payload_has_no_award_fields(backend):
    import inspect
    src = inspect.getsource(backend._handle_game_over)
    assert "award" not in src.lower()
