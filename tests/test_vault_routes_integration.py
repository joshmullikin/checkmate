import json

from cryptography.fernet import Fernet

from db import crud
import db.encryption as encryption
from db.models import Persona, PersonaCreate, ProjectCreate, TestDataCreate


def _setup_encryption():
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None


def _create_project(db_session):
    return crud.create_project(
        db_session,
        ProjectCreate(
            name="Vault Project",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )


def _create_credential(client, project_id: int, cred_type: str = "login", **overrides):
    payload = {
        "project_id": project_id,
        "name": f"cred-{cred_type}",
        "credential_type": cred_type,
        "username": "user@example.com",
        "password": "pass" if cred_type == "login" else None,
        "api_key": "apikey123" if cred_type == "api_key" else None,
        "token": "tok123" if cred_type == "token" else None,
        "custom_fields": None,
        "environment_id": None,
    }
    payload.update(overrides)
    res = client.post(f"/api/projects/{project_id}/vault/credentials", json=payload)
    assert res.status_code == 200, res.json()
    return res.json()


def test_credentials_routes_lifecycle_and_validation(client, db_session):
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None

    project = _create_project(db_session)

    list_res = client.get(f"/api/projects/{project.id}/vault/credentials")
    assert list_res.status_code == 200
    assert list_res.json() == []

    mismatch = client.post(
        f"/api/projects/{project.id}/vault/credentials",
        json={
            "project_id": project.id + 1,
            "name": "admin",
            "credential_type": "login",
            "password": "secret",
        },
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["detail"] == "Project ID mismatch"

    missing_pw = client.post(
        f"/api/projects/{project.id}/vault/credentials",
        json={
            "project_id": project.id,
            "name": "admin",
            "credential_type": "login",
            "password": None,
        },
    )
    assert missing_pw.status_code == 400

    create = client.post(
        f"/api/projects/{project.id}/vault/credentials",
        json={
            "project_id": project.id,
            "name": "admin",
            "username": "admin@example.com",
            "description": "Admin account",
            "credential_type": "login",
            "password": "super-secret",
            "api_key": None,
            "token": None,
            "custom_fields": None,
            "environment_id": None,
        },
    )
    assert create.status_code == 200
    cred_id = create.json()["id"]

    get_res = client.get(f"/api/projects/{project.id}/vault/credentials/{cred_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "admin"

    reveal = client.get(f"/api/projects/{project.id}/vault/credentials/{cred_id}/reveal")
    assert reveal.status_code == 200
    assert reveal.json()["password"] == "super-secret"

    update = client.put(
        f"/api/projects/{project.id}/vault/credentials/{cred_id}",
        json={"username": "owner@example.com", "description": "Updated"},
    )
    assert update.status_code == 200
    assert update.json()["username"] == "owner@example.com"

    delete = client.delete(f"/api/projects/{project.id}/vault/credentials/{cred_id}")
    assert delete.status_code == 200
    assert delete.json()["status"] == "deleted"


def test_test_data_routes_lifecycle_and_validation(client, db_session):
    project = _create_project(db_session)

    create = client.post(
        f"/api/projects/{project.id}/vault/test-data",
        json={
            "project_id": project.id,
            "name": "seed",
            "description": "Seed values",
            "data": json.dumps({"email": "qa@example.com"}),
            "tags": json.dumps(["smoke"]),
            "environment_id": None,
        },
    )
    assert create.status_code == 200
    td_id = create.json()["id"]

    list_res = client.get(f"/api/projects/{project.id}/vault/test-data")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    get_res = client.get(f"/api/projects/{project.id}/vault/test-data/{td_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "seed"

    update = client.put(
        f"/api/projects/{project.id}/vault/test-data/{td_id}",
        json={"description": "Updated", "tags": json.dumps(["regression"])},
    )
    assert update.status_code == 200
    assert update.json()["description"] == "Updated"

    delete = client.delete(f"/api/projects/{project.id}/vault/test-data/{td_id}")
    assert delete.status_code == 200
    assert delete.json()["status"] == "deleted"


def test_vault_routes_not_found(client):
    assert client.get("/api/projects/999999/vault/credentials").status_code == 404
    assert client.get("/api/projects/999999/vault/test-data").status_code == 404


def test_reveal_credential_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.get(f"/api/projects/{project.id}/vault/credentials/999999/reveal")
    assert res.status_code == 404


def test_reveal_credential_decrypt_errors(client, db_session):
    _setup_encryption()
    project = _create_project(db_session)

    persona = Persona(
        project_id=project.id,
        name="bad-creds",
        credential_type="custom",
        encrypted_password="this-is-not-fernet",
        encrypted_api_key="this-is-not-fernet",
        encrypted_token="this-is-not-fernet",
        encrypted_metadata="this-is-not-fernet",
    )
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)

    response = client.get(f"/api/projects/{project.id}/vault/credentials/{persona.id}/reveal")
    assert response.status_code == 200
    data = response.json()
    assert data["password"] is None
    assert data["api_key"] is None
    assert data["token"] is None
    assert data["custom_fields"] is None


def test_update_credential_crud_returns_none(client, db_session, monkeypatch):
    _setup_encryption()
    project = _create_project(db_session)

    persona = Persona(project_id=project.id, name="target-cred", credential_type="login")
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)

    import api.routes.vault as vault_mod

    monkeypatch.setattr(vault_mod.crud, "update_persona", lambda s, id, data: None)
    response = client.put(
        f"/api/projects/{project.id}/vault/credentials/{persona.id}",
        json={"name": "new-name"},
    )
    assert response.status_code == 404


def test_delete_credential_crud_returns_false(client, db_session, monkeypatch):
    _setup_encryption()
    project = _create_project(db_session)

    persona = Persona(project_id=project.id, name="target-cred", credential_type="login")
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)

    import api.routes.vault as vault_mod

    monkeypatch.setattr(vault_mod.crud, "delete_persona", lambda s, id: False)
    response = client.delete(f"/api/projects/{project.id}/vault/credentials/{persona.id}")
    assert response.status_code == 404


def test_create_credential_api_key_missing_key_returns_400(client, db_session):
    project = _create_project(db_session)
    res = client.post(
        f"/api/projects/{project.id}/vault/credentials",
        json={
            "project_id": project.id,
            "name": "api-cred",
            "credential_type": "api_key",
            "api_key": None,
        },
    )
    assert res.status_code == 400
    assert "api_key" in res.json()["detail"].lower()


def test_create_credential_token_missing_token_returns_400(client, db_session):
    project = _create_project(db_session)
    res = client.post(
        f"/api/projects/{project.id}/vault/credentials",
        json={
            "project_id": project.id,
            "name": "tok-cred",
            "credential_type": "token",
            "token": None,
        },
    )
    assert res.status_code == 400
    assert "token" in res.json()["detail"].lower()


def test_create_credential_api_key_success(client, db_session):
    _setup_encryption()
    project = _create_project(db_session)
    res = _create_credential(client, project.id, cred_type="api_key")
    assert res["credential_type"] == "api_key"


def test_create_credential_token_success(client, db_session):
    _setup_encryption()
    project = _create_project(db_session)
    res = _create_credential(client, project.id, cred_type="token")
    assert res["credential_type"] == "token"


def test_reveal_credential_api_key(client, db_session):
    _setup_encryption()
    project = _create_project(db_session)
    cred = _create_credential(client, project.id, cred_type="api_key")
    res = client.get(f"/api/projects/{project.id}/vault/credentials/{cred['id']}/reveal")
    assert res.status_code == 200
    assert res.json()["api_key"] == "apikey123"
    assert res.json()["password"] is None


def test_reveal_credential_token(client, db_session):
    _setup_encryption()
    project = _create_project(db_session)
    cred = _create_credential(client, project.id, cred_type="token")
    res = client.get(f"/api/projects/{project.id}/vault/credentials/{cred['id']}/reveal")
    assert res.status_code == 200
    assert res.json()["token"] == "tok123"


def test_reveal_credential_with_custom_fields(client, db_session):
    _setup_encryption()
    project = _create_project(db_session)
    cred = _create_credential(
        client,
        project.id,
        cred_type="login",
        custom_fields={"account_id": "12345", "region": "us-east-1"},
    )
    res = client.get(f"/api/projects/{project.id}/vault/credentials/{cred['id']}/reveal")
    assert res.status_code == 200
    assert res.json()["custom_fields"]["account_id"] == "12345"


def test_reveal_credential_wrong_project(client, db_session):
    _setup_encryption()
    project1 = _create_project(db_session)
    project2 = crud.create_project(
        db_session,
        ProjectCreate(
            name="Vault Project 2",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )
    cred = _create_credential(client, project1.id)
    res = client.get(f"/api/projects/{project2.id}/vault/credentials/{cred['id']}/reveal")
    assert res.status_code == 404


def test_get_credential_wrong_project(client, db_session):
    _setup_encryption()
    project1 = _create_project(db_session)
    project2 = crud.create_project(
        db_session,
        ProjectCreate(
            name="Vault Project 2B",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )
    cred = _create_credential(client, project1.id)
    res = client.get(f"/api/projects/{project2.id}/vault/credentials/{cred['id']}")
    assert res.status_code == 404


def test_update_credential_wrong_project(client, db_session):
    _setup_encryption()
    project1 = _create_project(db_session)
    project2 = crud.create_project(
        db_session,
        ProjectCreate(
            name="Vault Project 2C",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )
    cred = _create_credential(client, project1.id)
    res = client.put(
        f"/api/projects/{project2.id}/vault/credentials/{cred['id']}",
        json={"username": "attacker@example.com"},
    )
    assert res.status_code == 404


def test_delete_credential_wrong_project(client, db_session):
    _setup_encryption()
    project1 = _create_project(db_session)
    project2 = crud.create_project(
        db_session,
        ProjectCreate(
            name="Vault Project 2D",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )
    cred = _create_credential(client, project1.id)
    res = client.delete(f"/api/projects/{project2.id}/vault/credentials/{cred['id']}")
    assert res.status_code == 404


def test_update_credential_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.put(
        f"/api/projects/{project.id}/vault/credentials/999999",
        json={"username": "new@example.com"},
    )
    assert res.status_code == 404


def test_update_credential_success(client, db_session):
    _setup_encryption()
    project = _create_project(db_session)
    cred = _create_credential(client, project.id)
    res = client.put(
        f"/api/projects/{project.id}/vault/credentials/{cred['id']}",
        json={"username": "updated@example.com", "description": "Updated desc"},
    )
    assert res.status_code == 200
    assert res.json()["username"] == "updated@example.com"


def test_get_test_data_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.get(f"/api/projects/{project.id}/vault/test-data/999999")
    assert res.status_code == 404


def test_get_test_data_wrong_project(client, db_session):
    project1 = _create_project(db_session)
    project2 = crud.create_project(
        db_session,
        ProjectCreate(
            name="Vault TD Project 2",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )
    td_res = client.post(
        f"/api/projects/{project1.id}/vault/test-data",
        json={
            "project_id": project1.id,
            "name": "seed",
            "description": "d",
            "data": json.dumps({"k": "v"}),
            "tags": "[]",
            "environment_id": None,
        },
    )
    assert td_res.status_code == 200
    td_id = td_res.json()["id"]
    res = client.get(f"/api/projects/{project2.id}/vault/test-data/{td_id}")
    assert res.status_code == 404


def test_update_test_data_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.put(
        f"/api/projects/{project.id}/vault/test-data/999999",
        json={"description": "New"},
    )
    assert res.status_code == 404


def test_update_test_data_wrong_project(client, db_session):
    project1 = _create_project(db_session)
    project2 = crud.create_project(
        db_session,
        ProjectCreate(
            name="Vault TD Project 3",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )
    td_res = client.post(
        f"/api/projects/{project1.id}/vault/test-data",
        json={
            "project_id": project1.id,
            "name": "seed2",
            "description": "d",
            "data": json.dumps({"k": "v"}),
            "tags": "[]",
            "environment_id": None,
        },
    )
    td_id = td_res.json()["id"]
    res = client.put(
        f"/api/projects/{project2.id}/vault/test-data/{td_id}",
        json={"description": "Hack"},
    )
    assert res.status_code == 404


def test_delete_test_data_not_found(client, db_session):
    project = _create_project(db_session)
    res = client.delete(f"/api/projects/{project.id}/vault/test-data/999999")
    assert res.status_code == 404


def test_delete_test_data_wrong_project(client, db_session):
    project1 = _create_project(db_session)
    project2 = crud.create_project(
        db_session,
        ProjectCreate(
            name="Vault TD Project 4",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )
    td_res = client.post(
        f"/api/projects/{project1.id}/vault/test-data",
        json={
            "project_id": project1.id,
            "name": "seed3",
            "description": "d",
            "data": json.dumps({"k": "v"}),
            "tags": "[]",
            "environment_id": None,
        },
    )
    td_id = td_res.json()["id"]
    res = client.delete(f"/api/projects/{project2.id}/vault/test-data/{td_id}")
    assert res.status_code == 404


def test_test_data_project_id_mismatch(client, db_session):
    project = _create_project(db_session)
    res = client.post(
        f"/api/projects/{project.id}/vault/test-data",
        json={
            "project_id": project.id + 1,
            "name": "mismatch",
            "description": "d",
            "data": "{}",
            "tags": "[]",
        },
    )
    assert res.status_code == 400


def test_list_credentials_with_environment_filter(client, db_session):
    _setup_encryption()
    project = _create_project(db_session)

    env_res = client.post(
        f"/api/projects/{project.id}/environments",
        json={
            "project_id": project.id,
            "name": "Staging",
            "base_url": "https://staging.example.com",
            "variables": {},
        },
    )
    assert env_res.status_code == 200
    env_id = env_res.json()["id"]

    _create_credential(client, project.id, name="env-cred", environment_id=env_id)
    _create_credential(client, project.id, name="global-cred", environment_id=None)

    res = client.get(
        f"/api/projects/{project.id}/vault/credentials?environment_id={env_id}"
    )
    assert res.status_code == 200
    names = [c["name"] for c in res.json()]
    assert "env-cred" in names
    assert "global-cred" in names
