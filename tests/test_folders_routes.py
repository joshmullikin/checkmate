"""Integration tests for api/routes/folders.py"""
import json
import pytest
from db import crud
from db.models import ProjectCreate, TestCaseCreate, TestCaseStatus


def _make_project(client):
    res = client.post(
        "/api/projects",
        json={"name": "Folders Test Project", "description": "", "base_url": "https://example.com",
              "config": "{}", "base_prompt": "", "page_load_state": "load"},
    )
    assert res.status_code == 200
    return res.json()["id"]


def test_list_folders_auto_seeds_defaults(client):
    pid = _make_project(client)
    res = client.get(f"/api/folders/project/{pid}")
    assert res.status_code == 200
    folders = res.json()
    assert len(folders) >= 2
    names = [f["name"] for f in folders]
    assert "Regression Suite" in names
    assert "Smoke Tests" in names


def test_list_folders_unknown_project_returns_404(client):
    res = client.get("/api/folders/project/999999")
    assert res.status_code == 404


def test_create_and_get_folder(client):
    pid = _make_project(client)
    payload = {"project_id": pid, "name": "My Folder", "folder_type": "regular",
               "smart_criteria": None, "order_index": 0}
    create = client.post("/api/folders", json=payload)
    assert create.status_code == 200
    fid = create.json()["id"]

    get = client.get(f"/api/folders/{fid}")
    assert get.status_code == 200
    assert get.json()["name"] == "My Folder"


def test_create_folder_unknown_project_returns_404(client):
    payload = {"project_id": 99999, "name": "Orphan", "folder_type": "regular",
               "smart_criteria": None, "order_index": 0}
    res = client.post("/api/folders", json=payload)
    assert res.status_code == 404


def test_get_folder_not_found(client):
    res = client.get("/api/folders/9999999")
    assert res.status_code == 404


def test_update_folder(client):
    pid = _make_project(client)
    create = client.post("/api/folders",
                         json={"project_id": pid, "name": "Old Name", "folder_type": "regular",
                               "smart_criteria": None, "order_index": 0})
    fid = create.json()["id"]

    upd = client.put(f"/api/folders/{fid}",
                     json={"name": "New Name", "folder_type": "regular",
                           "smart_criteria": None, "order_index": 0})
    assert upd.status_code == 200
    assert upd.json()["name"] == "New Name"


def test_delete_folder(client):
    pid = _make_project(client)
    create = client.post("/api/folders",
                         json={"project_id": pid, "name": "Delete Me", "folder_type": "regular",
                               "smart_criteria": None, "order_index": 0})
    fid = create.json()["id"]

    delete = client.delete(f"/api/folders/{fid}")
    assert delete.status_code == 200
    assert delete.json()["status"] == "deleted"

    confirm = client.get(f"/api/folders/{fid}")
    assert confirm.status_code == 404


def test_delete_folder_not_found(client):
    res = client.delete("/api/folders/9999999")
    assert res.status_code == 404


def test_get_folder_test_cases_regular(client, db_session):
    pid = _make_project(client)
    create = client.post("/api/folders",
                         json={"project_id": pid, "name": "TC Folder", "folder_type": "regular",
                               "smart_criteria": None, "order_index": 0})
    fid = create.json()["id"]

    tc = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=pid,
            name="Folder Test Case",
            description="",
            natural_query="Folder test case",
            steps="[]",
            status=TestCaseStatus.ACTIVE,
            folder_id=fid,
        ),
    )

    res = client.get(f"/api/folders/{fid}/test-cases")
    assert res.status_code == 200
    ids = [t["id"] for t in res.json()]
    assert tc.id in ids


def test_get_smart_folder_test_cases(client):
    pid = _make_project(client)
    # Smart folders are auto-seeded; get them
    folders_res = client.get(f"/api/folders/project/{pid}")
    smart_folder = next(f for f in folders_res.json() if f["folder_type"] == "smart")
    fid = smart_folder["id"]

    res = client.get(f"/api/folders/{fid}/test-cases")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_move_folder(client):
    pid = _make_project(client)
    parent = client.post("/api/folders",
                         json={"project_id": pid, "name": "Parent", "folder_type": "regular",
                               "smart_criteria": None, "order_index": 0}).json()
    child = client.post("/api/folders",
                        json={"project_id": pid, "name": "Child", "folder_type": "regular",
                              "smart_criteria": None, "order_index": 1}).json()

    res = client.patch(f"/api/folders/{child['id']}/move", json={"parent_id": parent["id"]})
    assert res.status_code == 200
    assert res.json()["parent_id"] == parent["id"]


def test_move_test_case_to_folder(client, db_session):
    pid = _make_project(client)
    folder = client.post("/api/folders",
                         json={"project_id": pid, "name": "Target Folder", "folder_type": "regular",
                               "smart_criteria": None, "order_index": 0}).json()
    tc = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=pid,
            name="Movable TC",
            description="",
            natural_query="Movable test case",
            steps="[]",
            status=TestCaseStatus.ACTIVE,
        ),
    )

    res = client.patch(f"/api/folders/test-cases/{tc.id}/move", json={"folder_id": folder["id"]})
    assert res.status_code == 200
    assert res.json()["folder_id"] == folder["id"]


def test_get_folder_runnable_ids(client, db_session):
    pid = _make_project(client)
    folder = client.post("/api/folders",
                         json={"project_id": pid, "name": "Runnable Folder", "folder_type": "regular",
                               "smart_criteria": None, "order_index": 0}).json()
    fid = folder["id"]

    tc = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=pid,
            name="Runnable TC",
            description="",
            natural_query="Navigate to home",
            steps='[{"action": "navigate", "value": "/"}]',
            status=TestCaseStatus.ACTIVE,
            folder_id=fid,
        ),
    )

    res = client.post(f"/api/folders/{fid}/run")
    assert res.status_code == 200
    data = res.json()
    assert tc.id in data["test_case_ids"]
    assert data["count"] == 1


def test_get_folder_runnable_ids_not_found(client):
    res = client.post("/api/folders/9999999/run")
    assert res.status_code == 404


def test_update_folder_not_found(client):
    res = client.put("/api/folders/9999999", json={"name": "X", "folder_type": "regular"})
    assert res.status_code == 404


def test_delete_folder_with_test_cases_returns_409(client, db_session):
    """Delete a folder that contains test cases should return 409."""
    pid = _make_project(client)
    folder = client.post(
        "/api/folders",
        json={"project_id": pid, "name": "Non-empty", "folder_type": "regular",
              "smart_criteria": None, "order_index": 0},
    ).json()
    fid = folder["id"]

    crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=pid,
            name="Blocking TC",
            description="",
            natural_query="test",
            steps='[]',
            status=TestCaseStatus.ACTIVE,
            folder_id=fid,
        ),
    )

    res = client.delete(f"/api/folders/{fid}")
    assert res.status_code == 409


def test_get_folder_test_cases_not_found(client):
    res = client.get("/api/folders/9999999/test-cases")
    assert res.status_code == 404


def test_move_folder_not_found(client):
    res = client.patch("/api/folders/9999999/move", json={"parent_id": None})
    assert res.status_code == 404


def test_move_test_case_not_found(client):
    res = client.patch("/api/folders/test-cases/9999999/move", json={"folder_id": None})
    assert res.status_code == 404


def test_move_folder_circular_raises_400(client):
    """Moving a folder to itself should return 400."""
    pid = _make_project(client)
    folder = client.post(
        "/api/folders",
        json={"project_id": pid, "name": "Self Parent", "folder_type": "regular",
              "smart_criteria": None, "order_index": 0},
    ).json()
    fid = folder["id"]

    res = client.patch(f"/api/folders/{fid}/move", json={"parent_id": fid})
    assert res.status_code == 400
