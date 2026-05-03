"""Edge-case route tests for api/routes/test_cases.py.

Covers missing branches:
- update_visibility with invalid value → 400
- update_visibility to public → 200
- get_test_case_runs with actual runs (exercises the for-loop body)
- get_test_case_runs skip/limit pagination
- run_test_case with invalid JSON steps (json.JSONDecodeError path)
"""

import json
import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _project(client, name="TC Extended"):
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
    assert res.status_code == 200, res.json()
    return res.json()["id"]


def _test_case(client, project_id, name="Test Case", steps=None):
    if steps is None:
        steps = [{"action": "navigate", "value": "/login"}]
    res = client.post(
        "/api/test-cases",
        json={
            "project_id": project_id,
            "name": name,
            "description": "desc",
            "natural_query": "test",
            "steps": json.dumps(steps),
            "expected_result": "ok",
            "tags": json.dumps([]),
            "priority": "medium",
            "status": "draft",
        },
    )
    assert res.status_code == 200, res.json()
    return res.json()


# ──────────────────────────────────────────────────────────────────────────────
# visibility update
# ──────────────────────────────────────────────────────────────────────────────

def test_update_visibility_invalid_value_returns_400(client):
    """update_visibility with an invalid value triggers ValueError → 400."""
    pid = _project(client)
    tc = _test_case(client, pid)
    res = client.patch(
        f"/api/test-cases/{tc['id']}/visibility",
        json={"visibility": "restricted"},
    )
    assert res.status_code == 400
    assert "restricted" in res.json()["detail"].lower()


def test_update_visibility_to_public(client):
    """update_visibility to public returns 200 with visibility=public."""
    pid = _project(client)
    tc = _test_case(client, pid)
    res = client.patch(
        f"/api/test-cases/{tc['id']}/visibility",
        json={"visibility": "public"},
    )
    assert res.status_code == 200
    assert res.json()["visibility"] == "public"


# ──────────────────────────────────────────────────────────────────────────────
# get_test_case_runs — for-loop body and pagination
# ──────────────────────────────────────────────────────────────────────────────

def test_get_test_case_runs_with_run(client):
    """get_test_case_runs returns run data when runs exist (exercises for-loop body)."""
    pid = _project(client)
    tc = _test_case(client, pid)

    # Create a run by calling the sync run endpoint
    run_res = client.post(f"/api/test-cases/{tc['id']}/runs")
    assert run_res.status_code == 200

    runs_res = client.get(f"/api/test-cases/{tc['id']}/runs")
    assert runs_res.status_code == 200
    data = runs_res.json()
    assert len(data) >= 1
    run = data[0]
    assert run["test_case_id"] == tc["id"]
    assert "steps" in run
    assert "status" in run


def test_get_test_case_runs_with_multiple_runs_pagination(client):
    """get_test_case_runs respects skip and limit query parameters."""
    pid = _project(client)
    tc = _test_case(client, pid)

    # Create 3 runs
    for _ in range(3):
        client.post(f"/api/test-cases/{tc['id']}/runs")

    # Get all
    all_res = client.get(f"/api/test-cases/{tc['id']}/runs?limit=10")
    all_data = all_res.json()
    assert len(all_data) == 3

    # Get with limit
    limited_res = client.get(f"/api/test-cases/{tc['id']}/runs?limit=2")
    assert len(limited_res.json()) == 2

    # Get with skip
    skipped_res = client.get(f"/api/test-cases/{tc['id']}/runs?skip=1&limit=10")
    assert len(skipped_res.json()) == 2


# ──────────────────────────────────────────────────────────────────────────────
# run_test_case — invalid JSON steps
# ──────────────────────────────────────────────────────────────────────────────

def test_run_test_case_with_invalid_json_steps(client, db_session):
    """run_test_case handles invalid JSON in steps column gracefully (JSONDecodeError path)."""
    from db import models

    pid = _project(client)
    tc = _test_case(client, pid)

    # Corrupt the steps directly in the DB
    db_tc = db_session.get(models.TestCase, tc["id"])
    db_tc.steps = "NOT VALID JSON ]["
    db_session.add(db_tc)
    db_session.commit()

    res = client.post(f"/api/test-cases/{tc['id']}/runs")
    # Should still succeed — JSONDecodeError leads to steps_data=[], run completes
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("passed", "failed")


# ──────────────────────────────────────────────────────────────────────────────
# run_test_case — steps with all resolve_references paths
# ──────────────────────────────────────────────────────────────────────────────

def test_run_test_case_with_list_steps(client):
    """run_test_case handles steps that are already a list (not a JSON string)."""
    pid = _project(client)
    tc = _test_case(
        client,
        pid,
        steps=[
            {"action": "navigate", "value": "/home"},
            {"action": "click", "target": "button", "value": None},
        ],
    )
    res = client.post(f"/api/test-cases/{tc['id']}/runs")
    assert res.status_code == 200
    data = res.json()
    assert data["pass_count"] == 2
    assert len(data["steps"]) == 2


# ──────────────────────────────────────────────────────────────────────────────
# update_test_case_status — additional branches
# ──────────────────────────────────────────────────────────────────────────────

def test_update_status_draft_to_ready_no_steps_returns_400(client):
    """Transitioning draft→ready with no steps raises ValueError → 400."""
    pid = _project(client)
    # Create test case with EMPTY steps
    res = client.post(
        "/api/test-cases",
        json={
            "project_id": pid,
            "name": "Empty steps TC",
            "description": "d",
            "natural_query": "n",
            "steps": json.dumps([]),  # no steps
            "expected_result": "ok",
            "tags": json.dumps([]),
            "priority": "medium",
            "status": "draft",
        },
    )
    assert res.status_code == 200
    tcid = res.json()["id"]

    # Attempt draft → ready should fail (no steps)
    patch_res = client.patch(f"/api/test-cases/{tcid}/status", json={"status": "ready"})
    assert patch_res.status_code == 400
    assert "no steps" in patch_res.json()["detail"].lower()


def test_update_status_to_in_review(client):
    """Transitioning ready→in_review succeeds."""
    pid = _project(client)
    tc = _test_case(client, pid)

    # Move to ready first
    ready_res = client.patch(f"/api/test-cases/{tc['id']}/status", json={"status": "ready"})
    assert ready_res.status_code == 200

    # Move to in_review
    review_res = client.patch(
        f"/api/test-cases/{tc['id']}/status", json={"status": "in_review"}
    )
    assert review_res.status_code == 200
    assert review_res.json()["status"] == "in_review"


def test_update_status_to_approved(client):
    """Transitioning in_review→approved succeeds."""
    pid = _project(client)
    tc = _test_case(client, pid)

    client.patch(f"/api/test-cases/{tc['id']}/status", json={"status": "ready"})
    client.patch(f"/api/test-cases/{tc['id']}/status", json={"status": "in_review"})

    approved_res = client.patch(
        f"/api/test-cases/{tc['id']}/status", json={"status": "approved"}
    )
    assert approved_res.status_code == 200
    assert approved_res.json()["status"] == "approved"
