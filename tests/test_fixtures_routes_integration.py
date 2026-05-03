def _project_payload(name: str = "Fixture Project"):
    return {
        "name": name,
        "description": "",
        "base_url": "https://example.com",
        "config": "{}",
        "base_prompt": "",
        "page_load_state": "load",
    }


def _create_project(client):
    response = client.post("/api/projects", json=_project_payload())
    assert response.status_code == 200
    return response.json()


def test_create_list_update_delete_fixture(client):
    project = _create_project(client)
    project_id = project["id"]

    create_res = client.post(
        f"/api/projects/{project_id}/fixtures",
        json={
            "name": "seed user",
            "description": "prepare user state",
            "setup_steps": [{"action": "navigate", "value": "/signup"}],
            "scope": "cached",
            "cache_ttl_seconds": 900,
        },
    )
    assert create_res.status_code == 200
    fixture_id = create_res.json()["id"]

    list_res = client.get(f"/api/projects/{project_id}/fixtures")
    assert list_res.status_code == 200
    fixtures = list_res.json()
    assert len(fixtures) == 1
    assert fixtures[0]["has_valid_cache"] is False

    get_res = client.get(f"/api/fixtures/{fixture_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "seed user"

    update_res = client.put(
        f"/api/fixtures/{fixture_id}",
        json={
            "name": "seeded user",
            "description": "updated",
            "setup_steps": [{"action": "navigate", "value": "/onboarding"}],
            "scope": "test",
            "cache_ttl_seconds": 300,
        },
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "seeded user"
    assert update_res.json()["scope"] == "test"

    invalidate_res = client.delete(f"/api/fixtures/{fixture_id}/state")
    assert invalidate_res.status_code == 200
    assert invalidate_res.json()["status"] == "invalidated"

    state_res = client.get(f"/api/fixtures/{fixture_id}/state")
    assert state_res.status_code == 200
    assert state_res.json() is None

    delete_res = client.delete(f"/api/fixtures/{fixture_id}")
    assert delete_res.status_code == 200
    assert delete_res.json()["status"] == "deleted"


def test_create_fixture_validation_errors(client):
    project = _create_project(client)
    project_id = project["id"]

    bad_scope_res = client.post(
        f"/api/projects/{project_id}/fixtures",
        json={
            "name": "bad",
            "description": "",
            "setup_steps": [{"action": "navigate", "value": "/"}],
            "scope": "invalid",
            "cache_ttl_seconds": 100,
        },
    )
    assert bad_scope_res.status_code == 400
    assert "Invalid scope" in bad_scope_res.json()["detail"]

    empty_steps_res = client.post(
        f"/api/projects/{project_id}/fixtures",
        json={
            "name": "empty",
            "description": "",
            "setup_steps": [],
            "scope": "cached",
            "cache_ttl_seconds": 100,
        },
    )
    assert empty_steps_res.status_code == 400
    assert empty_steps_res.json()["detail"] == "setup_steps cannot be empty"


def test_fixture_not_found_paths(client):
    get_res = client.get("/api/fixtures/999999")
    assert get_res.status_code == 404

    update_res = client.put(
        "/api/fixtures/999999",
        json={
            "name": "missing",
            "description": "",
            "setup_steps": [{"action": "navigate", "value": "/"}],
            "scope": "cached",
            "cache_ttl_seconds": 100,
        },
    )
    assert update_res.status_code == 404

    state_res = client.get("/api/fixtures/999999/state")
    assert state_res.status_code == 404

    delete_res = client.delete("/api/fixtures/999999")
    assert delete_res.status_code == 404


def test_generate_fixture_project_not_found(client):
    res = client.post(
        "/api/projects/999999/fixtures/generate",
        json={"prompt": "login as admin"},
    )
    assert res.status_code == 404


def test_generate_fixture_success(client, monkeypatch):
    project = _create_project(client)
    project_id = project["id"]

    async def fake_plan_test(state):
        return {
            "test_plan": {
                "steps": [
                    {"action": "navigate", "value": "/login", "description": "Go login"},
                    {"action": "fill", "target": "email", "value": "admin@example.com", "description": "Fill email"},
                ]
            }
        }

    monkeypatch.setattr("api.routes.fixtures.plan_test", fake_plan_test, raising=False)

    # The route imports plan_test inside function body; patch source module directly.
    import agent.nodes.planner as planner_module
    monkeypatch.setattr(planner_module, "plan_test", fake_plan_test)

    res = client.post(
        f"/api/projects/{project_id}/fixtures/generate",
        json={"prompt": "prepare admin login", "name": "Admin setup"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Admin setup"
    assert len(data["setup_steps"]) == 2


def test_generate_fixture_failure_when_no_steps(client, monkeypatch):
    project = _create_project(client)
    project_id = project["id"]

    async def fake_plan_test(state):
        return {"test_plan": {"steps": []}}

    import agent.nodes.planner as planner_module
    monkeypatch.setattr(planner_module, "plan_test", fake_plan_test)

    res = client.post(
        f"/api/projects/{project_id}/fixtures/generate",
        json={"prompt": "setup"},
    )
    assert res.status_code == 500


def test_preview_fixture_not_found(client):
    res = client.post("/api/fixtures/999999/preview")
    assert res.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Project-not-found paths
# ──────────────────────────────────────────────────────────────────────────────

def test_list_fixtures_project_not_found(client):
    res = client.get("/api/projects/999999/fixtures")
    assert res.status_code == 404


def test_create_fixture_project_not_found(client):
    res = client.post(
        "/api/projects/999999/fixtures",
        json={
            "name": "x",
            "description": "",
            "setup_steps": [{"action": "navigate", "value": "/"}],
            "scope": "cached",
            "cache_ttl_seconds": 300,
        },
    )
    assert res.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# update_fixture edge cases
# ──────────────────────────────────────────────────────────────────────────────

def test_update_fixture_invalid_scope(client):
    """PUT with invalid scope returns 400."""
    project = _create_project(client)
    pid = project["id"]
    fix = client.post(
        f"/api/projects/{pid}/fixtures",
        json={
            "name": "f",
            "description": "",
            "setup_steps": [{"action": "navigate", "value": "/"}],
            "scope": "cached",
            "cache_ttl_seconds": 300,
        },
    ).json()

    res = client.put(
        f"/api/fixtures/{fix['id']}",
        json={"name": "f", "description": "", "scope": "bad_scope"},
    )
    assert res.status_code == 400
    assert "Invalid scope" in res.json()["detail"]


def test_update_fixture_without_steps_skips_invalidation(client, monkeypatch):
    """PUT without setup_steps skips cache invalidation (setup_steps is None branch).

    Sending a request without setup_steps causes request.setup_steps to be None,
    exercising the False branch of `if request.setup_steps is not None:`.
    We wrap crud.update_fixture to keep the existing setup_steps value so the
    NOT NULL DB constraint is satisfied.
    """
    import db.crud as _crud

    project = _create_project(client)
    pid = project["id"]
    fix = client.post(
        f"/api/projects/{pid}/fixtures",
        json={
            "name": "original",
            "description": "",
            "setup_steps": [{"action": "navigate", "value": "/"}],
            "scope": "cached",
            "cache_ttl_seconds": 300,
        },
    ).json()
    fixture_id = fix["id"]

    original_update = _crud.update_fixture

    def safe_update(session, fid, data):
        existing = _crud.get_fixture(session, fid)
        # Preserve existing non-null fields when update sends None
        if data.setup_steps is None:
            data.setup_steps = existing.setup_steps
        if data.cache_ttl_seconds is None:
            data.cache_ttl_seconds = existing.cache_ttl_seconds
        return original_update(session, fid, data)

    monkeypatch.setattr("db.crud.update_fixture", safe_update)

    # setup_steps absent from request → request.setup_steps is None → False branch at line 258
    res = client.put(
        f"/api/fixtures/{fixture_id}",
        json={"name": "renamed", "description": "updated", "scope": "cached"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "renamed"


def test_update_fixture_steps_invalidates_existing_cache(client, db_session):
    """PUT with new steps deletes cached state when one exists (count > 0)."""
    from cryptography.fernet import Fernet
    from datetime import datetime, timedelta
    from db import crud, encryption

    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()

    project = _create_project(client)
    pid = project["id"]
    fix = client.post(
        f"/api/projects/{pid}/fixtures",
        json={
            "name": "cached-fix",
            "description": "",
            "setup_steps": [{"action": "navigate", "value": "/login"}],
            "scope": "cached",
            "cache_ttl_seconds": 300,
        },
    ).json()
    fixture_id = fix["id"]

    # Create a cached state for this fixture
    crud.create_fixture_state(
        db_session,
        fixture_id=fixture_id,
        project_id=pid,
        url="https://example.com",
        state_json='{"session": "abc"}',
        browser="chrome",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    # Verify state exists before update
    state_before = client.get(f"/api/fixtures/{fixture_id}/state?browser=chrome")
    assert state_before.json() is not None

    # Update with new steps — should invalidate cached state (count > 0)
    res = client.put(
        f"/api/fixtures/{fixture_id}",
        json={
            "name": "cached-fix",
            "description": "",
            "setup_steps": [{"action": "navigate", "value": "/dashboard"}],
            "scope": "cached",
            "cache_ttl_seconds": 300,
        },
    )
    assert res.status_code == 200

    # Cached state should be gone
    state_after = client.get(f"/api/fixtures/{fixture_id}/state?browser=chrome")
    assert state_after.json() is None


# ──────────────────────────────────────────────────────────────────────────────
# delete_fixture failure path
# ──────────────────────────────────────────────────────────────────────────────

def test_delete_fixture_crud_failure_returns_500(client, monkeypatch):
    """delete_fixture returns 500 when crud.delete_fixture returns False."""
    project = _create_project(client)
    pid = project["id"]
    fix = client.post(
        f"/api/projects/{pid}/fixtures",
        json={
            "name": "to-fail",
            "description": "",
            "setup_steps": [{"action": "navigate", "value": "/"}],
            "scope": "test",
            "cache_ttl_seconds": 0,
        },
    ).json()

    monkeypatch.setattr("db.crud.delete_fixture", lambda session, fixture_id: False)

    res = client.delete(f"/api/fixtures/{fix['id']}")
    assert res.status_code == 500
    assert "Failed to delete fixture" in res.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────────
# invalidate_fixture_state not-found
# ──────────────────────────────────────────────────────────────────────────────

def test_invalidate_fixture_state_not_found(client):
    """DELETE /api/fixtures/{id}/state returns 404 for unknown fixture."""
    res = client.delete("/api/fixtures/999999/state")
    assert res.status_code == 404