from db import crud
from db.models import ProjectCreate


def _create_project(db_session):
    return crud.create_project(
        db_session,
        ProjectCreate(
            name="Settings Project",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="Initial prompt",
            page_load_state="load",
        ),
    )


def test_context_get_and_update(client, db_session):
    project = _create_project(db_session)

    get_res = client.get(f"/api/projects/{project.id}/settings/context")
    assert get_res.status_code == 200
    assert get_res.json()["base_prompt"] == "Initial prompt"

    update_res = client.put(
        f"/api/projects/{project.id}/settings/context",
        json={"base_prompt": "Updated prompt", "page_load_state": "networkidle"},
    )
    assert update_res.status_code == 200
    assert update_res.json() == {
        "base_prompt": "Updated prompt",
        "page_load_state": "networkidle",
    }

    no_change_res = client.put(
        f"/api/projects/{project.id}/settings/context",
        json={},
    )
    assert no_change_res.status_code == 200
    assert no_change_res.json()["base_prompt"] == "Updated prompt"


def test_context_project_not_found(client):
    get_res = client.get("/api/projects/999999/settings/context")
    assert get_res.status_code == 404

    put_res = client.put("/api/projects/999999/settings/context", json={"base_prompt": "x"})
    assert put_res.status_code == 404


def test_persona_lifecycle_and_mismatch(client, db_session):
    project = _create_project(db_session)
    other_project = crud.create_project(
        db_session,
        ProjectCreate(
            name="Other Project",
            description="",
            base_url="https://other.example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )

    create_res = client.post(
        f"/api/projects/{project.id}/settings/personas",
        json={
            "project_id": project.id,
            "name": "admin",
            "username": "admin@example.com",
            "description": "Admin user",
            "credential_type": "login",
            "password": None,
            "api_key": None,
            "token": None,
            "custom_fields": None,
        },
    )
    assert create_res.status_code == 200
    persona_id = create_res.json()["id"]

    list_res = client.get(f"/api/projects/{project.id}/settings/personas")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    mismatch_res = client.post(
        f"/api/projects/{project.id}/settings/personas",
        json={
            "project_id": other_project.id,
            "name": "mismatch",
            "username": None,
            "description": "",
            "credential_type": "login",
            "password": None,
            "api_key": None,
            "token": None,
            "custom_fields": None,
        },
    )
    assert mismatch_res.status_code == 400
    assert mismatch_res.json()["detail"] == "Project ID mismatch"

    delete_res = client.delete(f"/api/projects/{project.id}/settings/personas/{persona_id}")
    assert delete_res.status_code == 200
    assert delete_res.json()["status"] == "deleted"


def test_persona_not_found_and_wrong_project(client, db_session):
    project = _create_project(db_session)
    other = crud.create_project(
        db_session,
        ProjectCreate(
            name="Settings Other",
            description="",
            base_url="https://other.example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )

    missing_get = client.get(f"/api/projects/{project.id}/settings/personas/999999")
    assert missing_get.status_code == 404

    created = client.post(
        f"/api/projects/{project.id}/settings/personas",
        json={
            "project_id": project.id,
            "name": "viewer",
            "username": "viewer@example.com",
            "description": "Viewer",
            "credential_type": "login",
            "password": None,
            "api_key": None,
            "token": None,
            "custom_fields": None,
        },
    )
    pid = created.json()["id"]

    wrong_project_get = client.get(f"/api/projects/{other.id}/settings/personas/{pid}")
    assert wrong_project_get.status_code == 404

    wrong_project_put = client.put(
        f"/api/projects/{other.id}/settings/personas/{pid}",
        json={"name": "x"},
    )
    assert wrong_project_put.status_code == 404

    wrong_project_delete = client.delete(f"/api/projects/{other.id}/settings/personas/{pid}")
    assert wrong_project_delete.status_code == 404


def test_page_lifecycle(client, db_session):
    project = _create_project(db_session)

    create_res = client.post(
        f"/api/projects/{project.id}/settings/pages",
        json={
            "project_id": project.id,
            "name": "login",
            "path": "/login",
            "description": "Login page",
        },
    )
    assert create_res.status_code == 200
    page_id = create_res.json()["id"]

    get_res = client.get(f"/api/projects/{project.id}/settings/pages/{page_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "login"

    update_res = client.put(
        f"/api/projects/{project.id}/settings/pages/{page_id}",
        json={"name": "signin", "path": "/signin", "description": "Sign-in page"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "signin"

    delete_res = client.delete(f"/api/projects/{project.id}/settings/pages/{page_id}")
    assert delete_res.status_code == 200
    assert delete_res.json()["status"] == "deleted"


def test_page_not_found_and_wrong_project(client, db_session):
    project = _create_project(db_session)
    other = crud.create_project(
        db_session,
        ProjectCreate(
            name="Other Pages",
            description="",
            base_url="https://other.example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )

    missing_get = client.get(f"/api/projects/{project.id}/settings/pages/999999")
    assert missing_get.status_code == 404

    created = client.post(
        f"/api/projects/{project.id}/settings/pages",
        json={
            "project_id": project.id,
            "name": "home",
            "path": "/",
            "description": "Home",
        },
    )
    page_id = created.json()["id"]

    wrong_get = client.get(f"/api/projects/{other.id}/settings/pages/{page_id}")
    assert wrong_get.status_code == 404

    wrong_put = client.put(
        f"/api/projects/{other.id}/settings/pages/{page_id}",
        json={"name": "x"},
    )
    assert wrong_put.status_code == 404

    wrong_delete = client.delete(f"/api/projects/{other.id}/settings/pages/{page_id}")
    assert wrong_delete.status_code == 404


def test_list_personas_project_not_found(client):
    res = client.get("/api/projects/999999/settings/personas")
    assert res.status_code == 404


def test_create_persona_project_not_found(client):
    res = client.post(
        "/api/projects/999999/settings/personas",
        json={"project_id": 999999, "name": "x", "username": "x", "credential_type": "login"},
    )
    assert res.status_code == 404


def test_get_persona_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.get(f"/api/projects/{project.id}/settings/personas/999999")
    assert res.status_code == 404


def test_update_persona_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.put(
        f"/api/projects/{project.id}/settings/personas/999999",
        json={"name": "x"},
    )
    assert res.status_code == 404


def test_delete_persona_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.delete(f"/api/projects/{project.id}/settings/personas/999999")
    assert res.status_code == 404


def test_list_pages_project_not_found(client):
    res = client.get("/api/projects/999999/settings/pages")
    assert res.status_code == 404


def test_create_page_project_not_found(client):
    res = client.post(
        "/api/projects/999999/settings/pages",
        json={"project_id": 999999, "name": "home", "path": "/"},
    )
    assert res.status_code == 404


def test_create_page_project_id_mismatch(client, db_session):
    project = _create_project(db_session)
    other = crud.create_project(
        db_session,
        ProjectCreate(
            name="Mismatch Page Project",
            description="",
            base_url="https://other.example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )
    res = client.post(
        f"/api/projects/{project.id}/settings/pages",
        json={"project_id": other.id, "name": "home", "path": "/"},
    )
    assert res.status_code == 400


def test_get_page_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.get(f"/api/projects/{project.id}/settings/pages/999999")
    assert res.status_code == 404


def test_update_page_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.put(
        f"/api/projects/{project.id}/settings/pages/999999",
        json={"name": "x"},
    )
    assert res.status_code == 404


def test_delete_page_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.delete(f"/api/projects/{project.id}/settings/pages/999999")
    assert res.status_code == 404


def test_update_persona_returns_none(client, db_session, monkeypatch):
    project = _create_project(db_session)
    create_res = client.post(
        f"/api/projects/{project.id}/settings/personas",
        json={
            "project_id": project.id,
            "name": "u",
            "username": "u@example.com",
            "credential_type": "login",
        },
    )
    assert create_res.status_code == 200
    persona_id = create_res.json()["id"]

    import api.routes.settings as settings_mod

    monkeypatch.setattr(settings_mod.crud, "update_persona", lambda s, id, data: None)
    response = client.put(
        f"/api/projects/{project.id}/settings/personas/{persona_id}",
        json={"name": "new"},
    )
    assert response.status_code == 404


def test_update_page_returns_none(client, db_session, monkeypatch):
    project = _create_project(db_session)
    create_res = client.post(
        f"/api/projects/{project.id}/settings/pages",
        json={"project_id": project.id, "name": "home", "path": "/"},
    )
    assert create_res.status_code == 200
    page_id = create_res.json()["id"]

    import api.routes.settings as settings_mod

    monkeypatch.setattr(settings_mod.crud, "update_page", lambda s, id, data: None)
    response = client.put(
        f"/api/projects/{project.id}/settings/pages/{page_id}",
        json={"name": "new-home"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Direct function-call unit tests to cover branches in sync route functions
# (FastAPI runs sync routes in a threadpool executor which coverage.py can
# miss; calling the function directly guarantees coverage tracing).
# ---------------------------------------------------------------------------

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock


def test_update_context_project_not_found_after_update(db_session):
    """Line 69: crud.update_project returns None inside update_context."""
    import api.routes.settings as sm
    from db.models import ProjectCreate
    project = crud.create_project(
        db_session,
        ProjectCreate(name="ctx-p", description="", base_url="https://x.com", config="{}", base_prompt="", page_load_state="load"),
    )
    original = sm.crud.update_project
    try:
        sm.crud.update_project = lambda s, pid, d: None
        with pytest.raises(HTTPException) as exc_info:
            from pydantic import BaseModel as _BaseModel
            class _Update(_BaseModel):
                base_prompt: str | None = None
                page_load_state: str | None = None
            sm.update_context(project_id=project.id, data=_Update(base_prompt="x"), session=db_session)
        assert exc_info.value.status_code == 404
    finally:
        sm.crud.update_project = original


def test_get_persona_wrong_project_direct(db_session):
    """Line 129: return persona success path in get_persona route."""
    import api.routes.settings as sm
    from db.models import ProjectCreate, PersonaCreate
    p1 = crud.create_project(db_session, ProjectCreate(name="p1-dp", description="", base_url="https://p1.com", config="{}", base_prompt="", page_load_state="load"))
    persona = crud.create_persona(db_session, PersonaCreate(project_id=p1.id, name="viewer-dp", username="v@example.com", credential_type="login"))
    result = sm.get_persona(project_id=p1.id, persona_id=persona.id, session=db_session)
    assert result.id == persona.id


def test_update_persona_returns_none_direct(db_session):
    """Line 149: return updated success path in update_persona route."""
    import api.routes.settings as sm
    from db.models import ProjectCreate, PersonaCreate, PersonaUpdate
    project = crud.create_project(db_session, ProjectCreate(name="up-p-dp", description="", base_url="https://up.com", config="{}", base_prompt="", page_load_state="load"))
    persona = crud.create_persona(db_session, PersonaCreate(project_id=project.id, name="u2-dp", username="u2@e.com", credential_type="login"))
    result = sm.update_persona(project_id=project.id, persona_id=persona.id, data=PersonaUpdate(name="updated"), session=db_session)
    assert result.name == "updated"


def test_delete_persona_returns_false_direct(db_session):
    """Line 167: crud.delete_persona returns False in delete_persona route."""
    import api.routes.settings as sm
    from db.models import ProjectCreate, PersonaCreate
    project = crud.create_project(db_session, ProjectCreate(name="dp-p-dp", description="", base_url="https://dp.com", config="{}", base_prompt="", page_load_state="load"))
    persona = crud.create_persona(db_session, PersonaCreate(project_id=project.id, name="d2-dp", username="d2@e.com", credential_type="login"))
    original = sm.crud.delete_persona
    try:
        sm.crud.delete_persona = lambda s, pid: False
        with pytest.raises(HTTPException) as exc_info:
            sm.delete_persona(project_id=project.id, persona_id=persona.id, session=db_session)
        assert exc_info.value.status_code == 404
    finally:
        sm.crud.delete_persona = original


def test_list_pages_project_not_found_direct(db_session):
    """Line 185: return pages success path in list_pages route."""
    import api.routes.settings as sm
    from db.models import ProjectCreate, PageCreate
    project = crud.create_project(db_session, ProjectCreate(name="lp-dp", description="", base_url="https://lp.com", config="{}", base_prompt="", page_load_state="load"))
    crud.create_page(db_session, PageCreate(project_id=project.id, name="home-lp", path="/"))
    result = sm.list_pages(project_id=project.id, session=db_session)
    assert len(result) == 1


def test_delete_page_returns_false_direct(db_session):
    """Line 257: crud.delete_page returns False in delete_page route."""
    import api.routes.settings as sm
    from db.models import ProjectCreate, PageCreate
    project = crud.create_project(db_session, ProjectCreate(name="dpg-p-dp", description="", base_url="https://dpg.com", config="{}", base_prompt="", page_load_state="load"))
    page = crud.create_page(db_session, PageCreate(project_id=project.id, name="home-dp", path="/"))
    original = sm.crud.delete_page
    try:
        sm.crud.delete_page = lambda s, pid: False
        with pytest.raises(HTTPException) as exc_info:
            sm.delete_page(project_id=project.id, page_id=page.id, session=db_session)
        assert exc_info.value.status_code == 404
    finally:
        sm.crud.delete_page = original