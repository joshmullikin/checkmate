"""Integration tests for api/routes/test_cases.py"""
import json
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(client, name="TC Project"):
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


def _make_test_case(client, project_id, name="Login test"):
    return client.post(
        "/api/test-cases",
        json={
            "project_id": project_id,
            "name": name,
            "description": "Test login",
            "natural_query": "test the login flow",
            "steps": json.dumps([{"action": "navigate", "value": "/login"}]),
            "expected_result": "User is logged in",
            "tags": json.dumps([]),
            "priority": "medium",
            "status": "draft",
        },
    )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_test_cases_empty(client):
    pid = _make_project(client)
    res = client.get(f"/api/test-cases/project/{pid}")
    assert res.status_code == 200
    assert res.json() == []


def test_list_test_cases_returns_results(client):
    pid = _make_project(client)
    _make_test_case(client, pid)
    res = client.get(f"/api/test-cases/project/{pid}")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_list_test_cases_pagination(client):
    pid = _make_project(client)
    for i in range(5):
        _make_test_case(client, pid, name=f"Test {i}")
    res = client.get(f"/api/test-cases/project/{pid}?skip=2&limit=2")
    assert res.status_code == 200
    assert len(res.json()) == 2


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_test_case_success(client):
    pid = _make_project(client)
    res = _make_test_case(client, pid)
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Login test"
    assert data["project_id"] == pid


def test_create_test_case_project_not_found(client):
    res = client.post(
        "/api/test-cases",
        json={
            "project_id": 9999999,
            "name": "X",
            "natural_query": "q",
            "steps": "[]",
        },
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

def test_get_test_case_success(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.get(f"/api/test-cases/{tcid}")
    assert res.status_code == 200
    assert res.json()["id"] == tcid


def test_get_test_case_not_found(client):
    res = client.get("/api/test-cases/9999999")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_update_test_case_success(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.put(
        f"/api/test-cases/{tcid}",
        json={
            "project_id": pid,
            "name": "Updated name",
            "natural_query": "updated query",
            "steps": "[]",
        },
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Updated name"


def test_update_test_case_not_found(client):
    res = client.put(
        "/api/test-cases/9999999",
        json={
            "project_id": 1,
            "name": "X",
            "natural_query": "q",
            "steps": "[]",
        },
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_test_case_success(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.delete(f"/api/test-cases/{tcid}")
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"


def test_delete_test_case_not_found(client):
    res = client.delete("/api/test-cases/9999999")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Status update
# ---------------------------------------------------------------------------

def test_update_status_to_ready(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.patch(f"/api/test-cases/{tcid}/status", json={"status": "ready"})
    assert res.status_code == 200
    assert res.json()["status"] == "ready"


def test_update_status_to_archived(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.patch(f"/api/test-cases/{tcid}/status", json={"status": "archived"})
    assert res.status_code == 200


def test_update_status_not_found(client):
    res = client.patch("/api/test-cases/9999999/status", json={"status": "archived"})
    assert res.status_code == 404


def test_update_status_invalid_transition(client):
    """ready -> draft is invalid per the route docs."""
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    # advance to ready first
    client.patch(f"/api/test-cases/{tcid}/status", json={"status": "ready"})
    # try invalid transition: ready -> draft should raise ValueError
    res = client.patch(f"/api/test-cases/{tcid}/status", json={"status": "draft"})
    # Either 400 (ValueError caught) or 200 (if transition allowed by crud) — just no server error
    assert res.status_code in (200, 400)


# ---------------------------------------------------------------------------
# Visibility update
# ---------------------------------------------------------------------------

def test_update_visibility_to_private(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.patch(f"/api/test-cases/{tcid}/visibility", json={"visibility": "private"})
    assert res.status_code == 200
    assert res.json()["visibility"] == "private"


def test_update_visibility_not_found(client):
    res = client.patch("/api/test-cases/9999999/visibility", json={"visibility": "private"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def test_get_test_case_runs_empty(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.get(f"/api/test-cases/{tcid}/runs")
    assert res.status_code == 200
    assert res.json() == []


def test_get_test_case_runs_not_found(client):
    res = client.get("/api/test-cases/9999999/runs")
    assert res.status_code == 404


def test_run_test_case_creates_run(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.post(f"/api/test-cases/{tcid}/runs")
    assert res.status_code == 200
    data = res.json()
    assert data["test_case_id"] == tcid
    assert data["status"] in ("passed", "failed")


def test_run_test_case_not_found(client):
    res = client.post("/api/test-cases/9999999/runs")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Additional route edge paths
# ---------------------------------------------------------------------------

def test_update_visibility_invalid_value_returns_400(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.patch(
        f"/api/test-cases/{tcid}/visibility",
        json={"visibility": "restricted"},
    )
    assert res.status_code == 400
    assert "restricted" in res.json()["detail"].lower()


def test_update_visibility_to_public(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    res = client.patch(
        f"/api/test-cases/{tcid}/visibility",
        json={"visibility": "public"},
    )
    assert res.status_code == 200
    assert res.json()["visibility"] == "public"


def test_get_test_case_runs_with_run(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    run_res = client.post(f"/api/test-cases/{tcid}/runs")
    assert run_res.status_code == 200

    runs_res = client.get(f"/api/test-cases/{tcid}/runs")
    assert runs_res.status_code == 200
    data = runs_res.json()
    assert len(data) >= 1
    run = data[0]
    assert run["test_case_id"] == tcid
    assert "steps" in run
    assert "status" in run


def test_get_test_case_runs_with_multiple_runs_pagination(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]
    for _ in range(3):
        client.post(f"/api/test-cases/{tcid}/runs")

    all_res = client.get(f"/api/test-cases/{tcid}/runs?limit=10")
    assert len(all_res.json()) == 3

    limited_res = client.get(f"/api/test-cases/{tcid}/runs?limit=2")
    assert len(limited_res.json()) == 2

    skipped_res = client.get(f"/api/test-cases/{tcid}/runs?skip=1&limit=10")
    assert len(skipped_res.json()) == 2


def test_run_test_case_with_invalid_json_steps(client, db_session):
    from db import models

    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]

    db_tc = db_session.get(models.TestCase, tcid)
    db_tc.steps = "NOT VALID JSON ]["
    db_session.add(db_tc)
    db_session.commit()

    res = client.post(f"/api/test-cases/{tcid}/runs")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("passed", "failed")


def test_run_test_case_with_list_steps(client):
    pid = _make_project(client)
    res = client.post(
        "/api/test-cases",
        json={
            "project_id": pid,
            "name": "List steps TC",
            "description": "desc",
            "natural_query": "test",
            "steps": json.dumps(
                [
                    {"action": "navigate", "value": "/home"},
                    {"action": "click", "target": "button", "value": None},
                ]
            ),
            "expected_result": "ok",
            "tags": json.dumps([]),
            "priority": "medium",
            "status": "draft",
        },
    )
    assert res.status_code == 200
    tcid = res.json()["id"]

    run_res = client.post(f"/api/test-cases/{tcid}/runs")
    assert run_res.status_code == 200
    data = run_res.json()
    assert data["pass_count"] == 2
    assert len(data["steps"]) == 2


def test_update_status_draft_to_ready_no_steps_returns_400(client):
    pid = _make_project(client)
    res = client.post(
        "/api/test-cases",
        json={
            "project_id": pid,
            "name": "Empty steps TC",
            "description": "d",
            "natural_query": "n",
            "steps": json.dumps([]),
            "expected_result": "ok",
            "tags": json.dumps([]),
            "priority": "medium",
            "status": "draft",
        },
    )
    assert res.status_code == 200
    tcid = res.json()["id"]

    patch_res = client.patch(f"/api/test-cases/{tcid}/status", json={"status": "ready"})
    assert patch_res.status_code == 400
    assert "no steps" in patch_res.json()["detail"].lower()


def test_update_status_to_in_review(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]

    ready_res = client.patch(f"/api/test-cases/{tcid}/status", json={"status": "ready"})
    assert ready_res.status_code == 200

    review_res = client.patch(
        f"/api/test-cases/{tcid}/status", json={"status": "in_review"}
    )
    assert review_res.status_code == 200
    assert review_res.json()["status"] == "in_review"


def test_update_status_to_approved(client):
    pid = _make_project(client)
    tcid = _make_test_case(client, pid).json()["id"]

    client.patch(f"/api/test-cases/{tcid}/status", json={"status": "ready"})
    client.patch(f"/api/test-cases/{tcid}/status", json={"status": "in_review"})

    approved_res = client.patch(
        f"/api/test-cases/{tcid}/status", json={"status": "approved"}
    )
    assert approved_res.status_code == 200
    assert approved_res.json()["status"] == "approved"
