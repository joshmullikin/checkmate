import json

from db import crud
from db.models import ProjectCreate


def _create_project(db_session):
    return crud.create_project(
        db_session,
        ProjectCreate(
            name="Route Project",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )


def _test_case_payload(project_id: int):
    return {
        "project_id": project_id,
        "name": "User login",
        "description": "",
        "natural_query": "Test login flow",
        "steps": json.dumps([
            {"action": "navigate", "value": "/login"},
            {"action": "click", "target": "text=Sign in"},
        ]),
        "expected_result": "Dashboard opens",
        "tags": json.dumps(["smoke"]),
        "fixture_ids": None,
        "priority": "medium",
        "status": "draft",
        "visibility": "public",
        "folder_id": None,
        "test_case_number": None,
    }


def test_create_and_get_test_case_route(client, db_session):
    project = _create_project(db_session)
    create_res = client.post("/api/test-cases", json=_test_case_payload(project.id))
    assert create_res.status_code == 200

    created = create_res.json()
    assert created["project_id"] == project.id
    assert created["name"] == "User login"

    get_res = client.get(f"/api/test-cases/{created['id']}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == created["id"]


def test_create_test_case_returns_404_when_project_missing(client):
    res = client.post("/api/test-cases", json=_test_case_payload(99999))
    assert res.status_code == 404
    assert res.json()["detail"] == "Project not found"


def test_update_status_and_visibility_routes(client, db_session):
    project = _create_project(db_session)
    created = client.post("/api/test-cases", json=_test_case_payload(project.id)).json()
    test_case_id = created["id"]

    status_res = client.patch(f"/api/test-cases/{test_case_id}/status", json={"status": "ready"})
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "ready"

    visibility_res = client.patch(
        f"/api/test-cases/{test_case_id}/visibility",
        json={"visibility": "private"},
    )
    assert visibility_res.status_code == 200
    assert visibility_res.json()["visibility"] == "private"


def test_invalid_status_transition_returns_400(client, db_session):
    project = _create_project(db_session)
    created = client.post("/api/test-cases", json=_test_case_payload(project.id)).json()
    test_case_id = created["id"]

    res = client.patch(f"/api/test-cases/{test_case_id}/status", json={"status": "approved"})
    assert res.status_code == 400
    assert "Cannot transition" in res.json()["detail"]