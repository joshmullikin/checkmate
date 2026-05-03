"""Integration tests for api/routes/environments.py and api/routes/projects.py"""
import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _create_project(client, name="Env Test Project"):
    res = client.post(
        "/api/projects",
        json={"name": name, "description": "", "base_url": "https://example.com",
              "config": "{}", "base_prompt": "", "page_load_state": "load"},
    )
    assert res.status_code == 200
    return res.json()["id"]


# ──────────────────────────────────────────────────────────────────────────────
# Projects route tests
# ──────────────────────────────────────────────────────────────────────────────

def test_projects_list_and_create(client):
    pid = _create_project(client, name="List Me")
    res = client.get("/api/projects")
    assert res.status_code == 200
    ids = [p["id"] for p in res.json()]
    assert pid in ids


def test_project_get_and_update(client):
    pid = _create_project(client, name="Update Me")

    get = client.get(f"/api/projects/{pid}")
    assert get.status_code == 200
    assert get.json()["name"] == "Update Me"

    upd = client.put(
        f"/api/projects/{pid}",
        json={"name": "Updated Name", "description": "d", "base_url": "https://example.com",
              "config": "{}", "base_prompt": "", "page_load_state": "load"},
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Updated Name"


def test_project_not_found_errors(client):
    assert client.get("/api/projects/9999999").status_code == 404
    assert client.put(
        "/api/projects/9999999",
        json={"name": "x", "description": "", "base_url": "https://example.com",
              "config": "{}", "base_prompt": "", "page_load_state": "load"},
    ).status_code == 404
    assert client.delete("/api/projects/9999999").status_code == 404


def test_project_delete(client):
    pid = _create_project(client, name="Delete Project")
    res = client.delete(f"/api/projects/{pid}")
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_project_stats(client):
    res = client.get("/api/projects/stats")
    assert res.status_code == 200


def test_project_dashboard(client):
    pid = _create_project(client, name="Dashboard Project")
    res = client.get(f"/api/projects/{pid}/dashboard")
    assert res.status_code == 200


def test_project_dashboard_not_found(client):
    res = client.get("/api/projects/9999999/dashboard")
    assert res.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Environments route tests
# ──────────────────────────────────────────────────────────────────────────────

def _create_env(client, project_id, name="Staging"):
    return client.post(
        f"/api/projects/{project_id}/environments",
        json={
            "project_id": project_id,
            "name": name,
            "base_url": "https://staging.example.com",
        },
    )


def test_environments_crud(client):
    pid = _create_project(client, name="Env CRUD Project")

    # list empty
    lst = client.get(f"/api/projects/{pid}/environments")
    assert lst.status_code == 200
    assert lst.json() == []

    # create
    create = _create_env(client, pid)
    assert create.status_code == 200
    eid = create.json()["id"]

    # list populated
    lst2 = client.get(f"/api/projects/{pid}/environments")
    assert any(e["id"] == eid for e in lst2.json())

    # update
    upd = client.put(
        f"/api/projects/{pid}/environments/{eid}",
        json={"name": "Production", "base_url": "https://prod.example.com"},
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Production"

    # delete
    del_res = client.delete(f"/api/projects/{pid}/environments/{eid}")
    assert del_res.status_code == 200


def test_create_environment_project_mismatch(client):
    pid = _create_project(client, name="Mismatch Project")
    res = client.post(
        f"/api/projects/{pid}/environments",
        json={"project_id": pid + 999, "name": "Bad", "base_url": "https://example.com"},
    )
    assert res.status_code == 400


def test_create_environment_unknown_project(client):
    res = _create_env(client, 9999999)
    assert res.status_code == 404


def test_update_environment_not_found(client):
    pid = _create_project(client, name="Upd Not Found")
    res = client.put(
        f"/api/projects/{pid}/environments/9999999",
        json={"name": "x", "base_url": "https://example.com"},
    )
    assert res.status_code == 404


def test_delete_environment_not_found(client):
    pid = _create_project(client, name="Del Not Found")
    res = client.delete(f"/api/projects/{pid}/environments/9999999")
    assert res.status_code == 404
