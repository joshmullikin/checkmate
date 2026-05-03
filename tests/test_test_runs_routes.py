"""Integration tests for api/routes/test_runs.py"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from types import SimpleNamespace
from datetime import datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(client, name="TR Project"):
    res = client.post(
        "/api/projects",
        json={
            "name": name,
            "description": "",
            "base_url": "https://example.com",
            "config": "{}",
            "base_prompt": "",
            "page_load_state": "load",
        },
    )
    assert res.status_code == 200
    return res.json()["id"]


def _make_test_case(client, project_id):
    res = client.post(
        "/api/test-cases",
        json={
            "project_id": project_id,
            "name": "Sample test",
            "natural_query": "test the flow",
            "steps": json.dumps([{"action": "navigate", "value": "/"}]),
        },
    )
    assert res.status_code == 200
    return res.json()["id"]


def _make_run(client, project_id, test_case_id=None):
    body = {"project_id": project_id, "trigger": "manual", "status": "pending"}
    if test_case_id is not None:
        body["test_case_id"] = test_case_id
    res = client.post("/api/test-runs", json=body)
    assert res.status_code == 200
    return res.json()["id"]


# ---------------------------------------------------------------------------
# Browsers
# ---------------------------------------------------------------------------

def test_get_browsers_returns_empty_on_executor_unavailable(client):
    """When executor is down PlaywrightExecutorClient raises; endpoint returns []."""
    with patch("api.routes.test_runs.PlaywrightExecutorClient") as mock_cls:
        inst = MagicMock()
        inst.get_browsers = AsyncMock(side_effect=Exception("down"))
        inst.close = AsyncMock()
        mock_cls.return_value = inst
        res = client.get("/api/test-runs/browsers")
    assert res.status_code == 200
    assert res.json()["browsers"] == []


def test_get_browsers_returns_list(client):
    with patch("api.routes.test_runs.PlaywrightExecutorClient") as mock_cls:
        inst = MagicMock()
        inst.get_browsers = AsyncMock(return_value={
            "browsers": [{"id": "chromium", "name": "Chromium", "headless": True}],
            "default": "chromium",
        })
        inst.close = AsyncMock()
        mock_cls.return_value = inst
        res = client.get("/api/test-runs/browsers")
    assert res.status_code == 200
    data = res.json()
    assert len(data["browsers"]) == 1
    assert data["default"] == "chromium"


# ---------------------------------------------------------------------------
# List test runs
# ---------------------------------------------------------------------------

def test_list_test_runs_empty(client):
    pid = _make_project(client)
    res = client.get(f"/api/test-runs/project/{pid}")
    assert res.status_code == 200
    assert res.json() == []


def test_list_test_runs_returns_items(client):
    pid = _make_project(client)
    _make_run(client, pid)
    res = client.get(f"/api/test-runs/project/{pid}")
    assert res.status_code == 200
    assert len(res.json()) >= 1


def test_list_test_runs_with_thread_id(client):
    pid = _make_project(client)
    res = client.get(f"/api/test-runs/project/{pid}?thread_id=abc123")
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# Create test run
# ---------------------------------------------------------------------------

def test_create_test_run_success(client):
    pid = _make_project(client)
    res = client.post("/api/test-runs", json={"project_id": pid})
    assert res.status_code == 200
    assert res.json()["project_id"] == pid


def test_create_test_run_project_not_found(client):
    res = client.post("/api/test-runs", json={"project_id": 9999999})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Get test run
# ---------------------------------------------------------------------------

def test_get_test_run_success(client):
    pid = _make_project(client)
    rid = _make_run(client, pid)
    res = client.get(f"/api/test-runs/{rid}")
    assert res.status_code == 200
    assert res.json()["id"] == rid


def test_get_test_run_not_found(client):
    res = client.get("/api/test-runs/9999999")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Get test run steps
# ---------------------------------------------------------------------------

def test_get_test_run_steps_empty(client):
    pid = _make_project(client)
    rid = _make_run(client, pid)
    res = client.get(f"/api/test-runs/{rid}/steps")
    assert res.status_code == 200
    assert res.json() == []


def test_get_test_run_steps_not_found(client):
    res = client.get("/api/test-runs/9999999/steps")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Update test run
# ---------------------------------------------------------------------------

def test_update_test_run_success(client):
    pid = _make_project(client)
    rid = _make_run(client, pid)
    res = client.put(f"/api/test-runs/{rid}", json={"status": "passed", "summary": "All good"})
    assert res.status_code == 200


def test_update_test_run_not_found(client):
    res = client.put("/api/test-runs/9999999", json={"status": "passed"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Execute steps directly
# ---------------------------------------------------------------------------

def test_execute_steps_success(client):
    pid = _make_project(client)
    res = client.post(
        "/api/test-runs/execute",
        json={
            "project_id": pid,
            "steps": [
                {"action": "navigate", "target": None, "value": "/", "description": "Go home"},
                {"action": "click", "target": "button", "value": None, "description": "Click btn"},
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["pass_count"] == 2
    assert data["error_count"] == 0
    assert len(data["steps"]) == 2


def test_execute_steps_project_not_found(client):
    res = client.post(
        "/api/test-runs/execute",
        json={
            "project_id": 9999999,
            "steps": [{"action": "navigate", "value": "/", "description": "x"}],
        },
    )
    assert res.status_code == 404


def test_list_test_runs_with_test_case_id_enriches_name(client):
    """list_test_runs includes test_case_name when run is linked to a test case."""
    pid = _make_project(client, "Run TC Name Project")
    tcid = _make_test_case(client, pid)
    rid = _make_run(client, pid, test_case_id=tcid)
    res = client.get(f"/api/test-runs/project/{pid}")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    matching = [r for r in data if r["id"] == rid]
    assert len(matching) == 1
    # test_case_name should be populated
    assert matching[0].get("test_case_name") is not None


def test_list_test_runs_with_missing_test_case_lookup(monkeypatch):
    """When run references a test case ID that no longer exists, test_case_name stays None."""
    import api.routes.test_runs as test_runs_routes

    run = SimpleNamespace(
        id=1,
        project_id=5,
        test_case_id=999,
        trigger="manual",
        status="pending",
        thread_id=None,
        batch_label=None,
        started_at=None,
        completed_at=None,
        summary=None,
        error_count=0,
        pass_count=0,
        created_at=datetime.utcnow(),
        retry_attempt=0,
        max_retries=0,
        original_run_id=None,
        retry_mode="simple",
        retry_reason=None,
        browser=None,
    )

    monkeypatch.setattr(test_runs_routes.crud, "get_test_runs_by_project", lambda s, p, skip=0, limit=100: [run])
    monkeypatch.setattr(test_runs_routes.crud, "get_test_case", lambda s, tcid: None)

    result = test_runs_routes.list_test_runs(project_id=5, thread_id=None, skip=0, limit=100, session=object())
    assert len(result) == 1
    assert result[0].test_case_name is None

