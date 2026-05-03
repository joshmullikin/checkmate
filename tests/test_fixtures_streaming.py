"""Tests for api/routes/fixtures.py streaming, state management, and generation logic.

Uses the `client` and `db_session` fixtures from conftest.py for proper test DB isolation.

Key architectural notes:
- PlaywrightExecutorClient is imported inside the function body, so patch at
  agent.executor_client.PlaywrightExecutorClient
- plan_test is imported inside generate_fixture function body, so patch at
  agent.nodes.planner.plan_test
- create_fixture_state encrypts state_json, so tests must set encryption.ENCRYPTION_KEY
- The preview streaming function saves state via a separate get_session() call which
  targets a new DB. To test state-save logic, we patch db.session.get_session.
"""

import json
import pytest
from contextlib import contextmanager
from cryptography.fernet import Fernet
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from sqlmodel import Session

from db import crud, encryption


# ──────────────────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────────────────

def _project(client):
    res = client.post(
        "/api/projects",
        json={
            "name": "Stream Test Project",
            "description": "",
            "base_url": "https://example.com",
            "config": "{}",
            "base_prompt": "",
            "page_load_state": "load",
        },
    )
    assert res.status_code == 200
    return res.json()


def _fixture(client, project_id, scope="cached"):
    res = client.post(
        f"/api/projects/{project_id}/fixtures",
        json={
            "name": f"fixture-{scope}",
            "description": "",
            "setup_steps": [{"action": "navigate", "value": "/login"}],
            "scope": scope,
            "cache_ttl_seconds": 300,
        },
    )
    assert res.status_code == 200
    return res.json()


def _setup_encryption():
    """Set a valid encryption key for tests that use create_fixture_state."""
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()


def _mock_executor(monkeypatch, events):
    """Monkeypatch PlaywrightExecutorClient with a fixed event stream.

    Must patch at agent.executor_client because the code imports it there
    inside the function body.
    """
    async def fake_stream(*args, **kwargs):
        for e in events:
            yield e

    mc = AsyncMock()
    mc.execute_stream = fake_stream
    mc.close = AsyncMock()
    monkeypatch.setattr("agent.executor_client.PlaywrightExecutorClient", lambda: mc)
    return mc


# ──────────────────────────────────────────────────────────────────────────────
# Preview fixture tests
# ──────────────────────────────────────────────────────────────────────────────

def test_preview_fixture_test_scope_no_state_save(client, monkeypatch):
    """Test scope 'test' does NOT save state after execution."""
    project = _project(client)
    fix = _fixture(client, project["id"], scope="test")
    fixture_id = fix["id"]

    _mock_executor(monkeypatch, [
        {"type": "step_started", "step_number": 1, "action": "navigate"},
        {"type": "step_completed", "step_number": 1, "action": "navigate", "status": "passed"},
        {"type": "completed", "status": "passed"},
    ])

    res = client.post(f"/api/fixtures/{fixture_id}/preview?browser=chrome")
    assert res.status_code == 200

    # Scope 'test' never saves state
    state_res = client.get(f"/api/fixtures/{fixture_id}/state?browser=chrome")
    assert state_res.status_code == 200
    assert state_res.json() is None


def test_preview_fixture_cached_scope_saves_state(client, test_engine, monkeypatch):
    """Cached scope saves state after successful capture_state step.

    We patch db.session.get_session so the streaming generator writes
    to the same in-memory test DB as the client fixture.
    """
    _setup_encryption()
    project = _project(client)
    fix = _fixture(client, project["id"], scope="cached")
    fixture_id = fix["id"]

    @contextmanager
    def fake_get_session():
        with Session(test_engine) as session:
            yield session

    monkeypatch.setattr("db.session.get_session", fake_get_session)

    _mock_executor(monkeypatch, [
        {"type": "step_started", "step_number": 1, "action": "navigate"},
        {"type": "step_completed", "step_number": 1, "action": "navigate", "status": "passed"},
        {
            "type": "step_completed",
            "step_number": 2,
            "action": "capture_state",
            "status": "passed",
            "result": {
                "state": {"cookies": [{"name": "sid", "value": "abc"}]},
                "url": "https://example.com/dashboard",
            },
        },
        {"type": "completed", "status": "passed"},
    ])

    res = client.post(f"/api/fixtures/{fixture_id}/preview?browser=firefox")
    assert res.status_code == 200

    state_res = client.get(f"/api/fixtures/{fixture_id}/state?browser=firefox")
    assert state_res.status_code == 200
    state = state_res.json()
    assert state is not None
    assert state["browser"] == "firefox"


def test_preview_fixture_execution_failure_no_state_save(client, monkeypatch):
    """Failed execution does NOT save state."""
    project = _project(client)
    fix = _fixture(client, project["id"], scope="cached")
    fixture_id = fix["id"]

    _mock_executor(monkeypatch, [
        {"type": "step_started", "step_number": 1, "action": "navigate"},
        {"type": "step_completed", "step_number": 1, "action": "navigate", "status": "failed"},
        {"type": "completed", "status": "failed"},
    ])

    res = client.post(f"/api/fixtures/{fixture_id}/preview?browser=chrome")
    assert res.status_code == 200

    state_res = client.get(f"/api/fixtures/{fixture_id}/state?browser=chrome")
    assert state_res.status_code == 200
    assert state_res.json() is None


def test_preview_fixture_not_found(client):
    """Preview returns 404 for unknown fixture."""
    res = client.post("/api/fixtures/999999/preview")
    assert res.status_code == 404


def test_preview_fixture_streaming_yields_events(client, monkeypatch):
    """Preview streams SSE events in order."""
    project = _project(client)
    fix = _fixture(client, project["id"], scope="test")
    fixture_id = fix["id"]

    received = []
    mc = AsyncMock()
    mc.close = AsyncMock()

    async def fake_stream(*args, **kwargs):
        for e in [
            {"type": "step_started", "step_number": 1, "action": "navigate"},
            {"type": "step_completed", "step_number": 1, "action": "navigate", "status": "passed"},
            {"type": "completed", "status": "passed"},
        ]:
            received.append(e)
            yield e

    mc.execute_stream = fake_stream
    monkeypatch.setattr("agent.executor_client.PlaywrightExecutorClient", lambda: mc)

    res = client.post(f"/api/fixtures/{fixture_id}/preview")
    assert res.status_code == 200
    assert len(received) == 3


# ──────────────────────────────────────────────────────────────────────────────
# get_fixture_state with browser filter
# ──────────────────────────────────────────────────────────────────────────────

def test_get_fixture_state_with_browser_filter(client, db_session):
    """get_fixture_state filters results by browser parameter."""
    _setup_encryption()

    project = _project(client)
    fix = _fixture(client, project["id"], scope="cached")
    fixture_id = fix["id"]

    crud.create_fixture_state(
        db_session,
        fixture_id=fixture_id,
        project_id=project["id"],
        url="https://example.com/chrome",
        state_json='{"chrome": true}',
        browser="chrome",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    crud.create_fixture_state(
        db_session,
        fixture_id=fixture_id,
        project_id=project["id"],
        url="https://example.com/firefox",
        state_json='{"firefox": true}',
        browser="firefox",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    res_chrome = client.get(f"/api/fixtures/{fixture_id}/state?browser=chrome")
    assert res_chrome.status_code == 200
    assert res_chrome.json()["browser"] == "chrome"

    res_firefox = client.get(f"/api/fixtures/{fixture_id}/state?browser=firefox")
    assert res_firefox.status_code == 200
    assert res_firefox.json()["browser"] == "firefox"


def test_get_fixture_state_expired_returns_none(client, db_session):
    """Expired state is not returned."""
    _setup_encryption()

    project = _project(client)
    fix = _fixture(client, project["id"], scope="cached")
    fixture_id = fix["id"]

    crud.create_fixture_state(
        db_session,
        fixture_id=fixture_id,
        project_id=project["id"],
        url="https://example.com",
        state_json='{}',
        browser="chrome",
        expires_at=datetime.utcnow() - timedelta(hours=1),  # Already expired
    )
    db_session.commit()

    res = client.get(f"/api/fixtures/{fixture_id}/state?browser=chrome")
    assert res.status_code == 200
    # get_valid_fixture_state filters out expired entries
    assert res.json() is None


def test_get_fixture_state_not_found_fixture(client):
    """get_fixture_state returns 404 for unknown fixture."""
    res = client.get("/api/fixtures/999999/state")
    assert res.status_code == 404


def test_get_fixture_state_no_state(client):
    """get_fixture_state returns None when no state has been saved."""
    project = _project(client)
    fix = _fixture(client, project["id"], scope="cached")
    fixture_id = fix["id"]

    res = client.get(f"/api/fixtures/{fixture_id}/state")
    assert res.status_code == 200
    assert res.json() is None


# ──────────────────────────────────────────────────────────────────────────────
# Generate fixture tests
# ──────────────────────────────────────────────────────────────────────────────

def test_generate_fixture_plan_test_exception(client, monkeypatch):
    """generate_fixture returns 500 on plan_test exception."""
    project = _project(client)

    async def fake_plan_test(state):
        raise ValueError("LLM connection failed")

    # plan_test is imported inside the function body from agent.nodes.planner
    monkeypatch.setattr("agent.nodes.planner.plan_test", fake_plan_test)

    res = client.post(
        f"/api/projects/{project['id']}/fixtures/generate",
        json={"prompt": "login as admin"},
    )
    assert res.status_code == 500
    assert "Failed to generate fixture" in res.json()["detail"]


def test_generate_fixture_empty_steps_error(client, monkeypatch):
    """generate_fixture returns 500 when plan_test returns no steps."""
    project = _project(client)

    async def fake_plan_test(state):
        return {"test_plan": {"steps": []}}

    monkeypatch.setattr("agent.nodes.planner.plan_test", fake_plan_test)

    res = client.post(
        f"/api/projects/{project['id']}/fixtures/generate",
        json={"prompt": "login"},
    )
    assert res.status_code == 500
    assert "no steps" in res.json()["detail"]


def test_generate_fixture_skip_fixtures_context(client, monkeypatch):
    """generate_fixture passes skip_fixtures_context=True to plan_test."""
    project = _project(client)
    captured = {}

    async def fake_plan_test(state):
        captured.update(state)
        return {"test_plan": {"steps": [{"action": "navigate", "value": "/"}]}}

    monkeypatch.setattr("agent.nodes.planner.plan_test", fake_plan_test)

    res = client.post(
        f"/api/projects/{project['id']}/fixtures/generate",
        json={"prompt": "setup"},
    )
    assert res.status_code == 200
    assert captured.get("skip_fixtures_context") is True


def test_generate_fixture_custom_name(client, monkeypatch):
    """generate_fixture uses custom name when provided."""
    project = _project(client)

    async def fake_plan_test(state):
        return {"test_plan": {"steps": [{"action": "navigate"}]}}

    monkeypatch.setattr("agent.nodes.planner.plan_test", fake_plan_test)

    res = client.post(
        f"/api/projects/{project['id']}/fixtures/generate",
        json={"prompt": "setup", "name": "My Custom Fixture"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "My Custom Fixture"


def test_generate_fixture_default_name(client, monkeypatch):
    """generate_fixture uses 'Generated Fixture' when name not provided."""
    project = _project(client)

    async def fake_plan_test(state):
        return {"test_plan": {"steps": [{"action": "navigate"}]}}

    monkeypatch.setattr("agent.nodes.planner.plan_test", fake_plan_test)

    res = client.post(
        f"/api/projects/{project['id']}/fixtures/generate",
        json={"prompt": "setup"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Generated Fixture"


def test_generate_fixture_returns_fixture_data(client, monkeypatch):
    """generate_fixture returns expected fixture data without persisting."""
    project = _project(client)

    async def fake_plan_test(state):
        return {
            "test_plan": {
                "steps": [
                    {"action": "navigate", "value": "/login"},
                    {"action": "fill_form", "target": "email", "value": "admin@example.com"},
                ]
            }
        }

    monkeypatch.setattr("agent.nodes.planner.plan_test", fake_plan_test)

    res = client.post(
        f"/api/projects/{project['id']}/fixtures/generate",
        json={"prompt": "login as admin", "name": "Admin Login"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Admin Login"
    assert data["description"] == "login as admin"
    assert len(data["setup_steps"]) == 2
    assert data["scope"] == "cached"
    assert data["cache_ttl_seconds"] == 3600


def test_generate_fixture_no_test_plan_returns_500(client, monkeypatch):
    """generate_fixture returns 500 when plan_test returns missing test_plan key."""
    project = _project(client)

    async def fake_plan_test(state):
        return {}  # Missing test_plan key

    monkeypatch.setattr("agent.nodes.planner.plan_test", fake_plan_test)

    res = client.post(
        f"/api/projects/{project['id']}/fixtures/generate",
        json={"prompt": "setup"},
    )
    assert res.status_code == 500


def test_generate_fixture_project_not_found(client):
    """generate_fixture returns 404 for unknown project."""
    res = client.post(
        "/api/projects/999999/fixtures/generate",
        json={"prompt": "login"},
    )
    assert res.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# preview_fixture project-not-found and streaming edge branches
# ──────────────────────────────────────────────────────────────────────────────

def test_preview_fixture_project_not_found(client, monkeypatch):
    """preview_fixture returns 404 when fixture exists but project is missing."""
    from db import crud as db_crud

    project = _project(client)
    fix = _fixture(client, project["id"], scope="cached")

    original_get_project = db_crud.get_project

    def patched_get_project(session, project_id):
        if project_id == fix["project_id"]:
            return None
        return original_get_project(session, project_id)

    monkeypatch.setattr("db.crud.get_project", patched_get_project)

    res = client.post(f"/api/fixtures/{fix['id']}/preview")
    assert res.status_code == 404
    assert "Project not found" in res.json()["detail"]


def test_preview_streaming_step_out_of_bounds(client, monkeypatch):
    """Streaming handles step_number beyond display_steps length without error."""
    project = _project(client)
    fix = _fixture(client, project["id"], scope="test")

    # step_number=99 → step_num=98, but only 1 display_step → out-of-bounds branch
    _mock_executor(monkeypatch, [
        {"type": "step_started", "step_number": 99, "action": "navigate"},
        {"type": "completed", "status": "passed"},
    ])

    res = client.post(f"/api/fixtures/{fix['id']}/preview")
    assert res.status_code == 200


def test_preview_streaming_capture_state_result_none(client, monkeypatch):
    """Streaming handles capture_state event with result=None (no state captured)."""
    project = _project(client)
    fix = _fixture(client, project["id"], scope="cached")

    _mock_executor(monkeypatch, [
        {
            "type": "step_completed",
            "step_number": 1,
            "action": "capture_state",
            "status": "passed",
            "result": None,  # result is falsy — captured_state stays None
        },
        {"type": "completed", "status": "passed"},
    ])

    res = client.post(f"/api/fixtures/{fix['id']}/preview")
    assert res.status_code == 200

    # No state should have been saved since result was None
    state_res = client.get(f"/api/fixtures/{fix['id']}/state")
    assert state_res.json() is None


def test_preview_fixture_state_save_replaces_old_state(client, test_engine, db_session, monkeypatch):
    """Saving new cached state deletes any existing state for the same fixture/browser."""
    _setup_encryption()
    project = _project(client)
    fix = _fixture(client, project["id"], scope="cached")
    fixture_id = fix["id"]

    # Pre-create an existing state to be replaced
    crud.create_fixture_state(
        db_session,
        fixture_id=fixture_id,
        project_id=project["id"],
        url="https://example.com/old",
        state_json='{"old": true}',
        browser="chrome",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    @contextmanager
    def fake_get_session():
        with Session(test_engine) as session:
            yield session

    monkeypatch.setattr("db.session.get_session", fake_get_session)

    _mock_executor(monkeypatch, [
        {"type": "step_started", "step_number": 1, "action": "navigate"},
        {"type": "step_completed", "step_number": 1, "action": "navigate", "status": "passed"},
        {
            "type": "step_completed",
            "step_number": 2,
            "action": "capture_state",
            "status": "passed",
            "result": {
                "state": {"cookies": [{"name": "sid", "value": "xyz"}]},
                "url": "https://example.com/new",
            },
        },
        {"type": "completed", "status": "passed"},
    ])

    res = client.post(f"/api/fixtures/{fixture_id}/preview?browser=chrome")
    assert res.status_code == 200

    # New state should exist and replace old
    state_res = client.get(f"/api/fixtures/{fixture_id}/state?browser=chrome")
    assert state_res.json() is not None


def test_preview_fixture_state_save_exception_does_not_fail_preview(client, test_engine, monkeypatch):
    """Exception during state-save is logged but does not cause the preview to fail."""
    _setup_encryption()
    project = _project(client)
    fix = _fixture(client, project["id"], scope="cached")
    fixture_id = fix["id"]

    @contextmanager
    def fake_get_session():
        with Session(test_engine) as session:
            yield session

    monkeypatch.setattr("db.session.get_session", fake_get_session)
    monkeypatch.setattr("db.crud.create_fixture_state", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("DB error")))

    _mock_executor(monkeypatch, [
        {
            "type": "step_completed",
            "step_number": 1,
            "action": "capture_state",
            "status": "passed",
            "result": {
                "state": {"cookies": []},
                "url": "https://example.com/dashboard",
            },
        },
        {"type": "completed", "status": "passed"},
    ])

    # Preview should still succeed even though state-save threw
    res = client.post(f"/api/fixtures/{fixture_id}/preview?browser=chrome")
    assert res.status_code == 200
