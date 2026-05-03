"""Edge-case route tests for api/routes/vault.py.

Covers missing branches:
- reveal_credential with api_key, token, custom_fields types
- credential type validation (api_key, token missing required fields)
- credential wrong project_id (404 paths)
- test_data wrong project_id (404 paths)
- test_data update/delete 404 paths
- environment_id filter
"""

import json
import pytest
from cryptography.fernet import Fernet
import db.encryption as encryption


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _setup_encryption():
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None


def _project(client, name="Vault Test Project"):
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
    return res.json()


def _credential(client, project_id, cred_type="login", **overrides):
    base = {
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
    base.update(overrides)
    res = client.post(f"/api/projects/{project_id}/vault/credentials", json=base)
    assert res.status_code == 200, res.json()
    return res.json()


# ──────────────────────────────────────────────────────────────────────────────
# Credential type validation
# ──────────────────────────────────────────────────────────────────────────────

def test_create_credential_api_key_missing_key_returns_400(client):
    """Creating api_key credential without api_key returns 400."""
    project = _project(client)
    res = client.post(
        f"/api/projects/{project['id']}/vault/credentials",
        json={
            "project_id": project["id"],
            "name": "api-cred",
            "credential_type": "api_key",
            "api_key": None,
        },
    )
    assert res.status_code == 400
    assert "api_key" in res.json()["detail"].lower()


def test_create_credential_token_missing_token_returns_400(client):
    """Creating token credential without token returns 400."""
    project = _project(client)
    res = client.post(
        f"/api/projects/{project['id']}/vault/credentials",
        json={
            "project_id": project["id"],
            "name": "tok-cred",
            "credential_type": "token",
            "token": None,
        },
    )
    assert res.status_code == 400
    assert "token" in res.json()["detail"].lower()


def test_create_credential_api_key_success(client):
    """Creating api_key credential with valid api_key succeeds."""
    _setup_encryption()
    project = _project(client)
    _credential(client, project["id"], cred_type="api_key")


def test_create_credential_token_success(client):
    """Creating token credential with valid token succeeds."""
    _setup_encryption()
    project = _project(client)
    _credential(client, project["id"], cred_type="token")


# ──────────────────────────────────────────────────────────────────────────────
# reveal_credential — covers encrypted field paths (api_key, token, custom_fields)
# ──────────────────────────────────────────────────────────────────────────────

def test_reveal_credential_api_key(client):
    """reveal_credential returns decrypted api_key."""
    _setup_encryption()
    project = _project(client)
    cred = _credential(client, project["id"], cred_type="api_key")
    res = client.get(f"/api/projects/{project['id']}/vault/credentials/{cred['id']}/reveal")
    assert res.status_code == 200
    assert res.json()["api_key"] == "apikey123"
    assert res.json()["password"] is None


def test_reveal_credential_token(client):
    """reveal_credential returns decrypted token."""
    _setup_encryption()
    project = _project(client)
    cred = _credential(client, project["id"], cred_type="token")
    res = client.get(f"/api/projects/{project['id']}/vault/credentials/{cred['id']}/reveal")
    assert res.status_code == 200
    assert res.json()["token"] == "tok123"


def test_reveal_credential_with_custom_fields(client):
    """reveal_credential returns decrypted custom_fields."""
    _setup_encryption()
    project = _project(client)
    custom = {"account_id": "12345", "region": "us-east-1"}
    cred = _credential(
        client,
        project["id"],
        cred_type="login",
        custom_fields=custom,
    )
    res = client.get(f"/api/projects/{project['id']}/vault/credentials/{cred['id']}/reveal")
    assert res.status_code == 200
    assert res.json()["custom_fields"]["account_id"] == "12345"


def test_reveal_credential_not_found(client):
    """reveal_credential returns 404 for unknown credential."""
    project = _project(client)
    res = client.get(f"/api/projects/{project['id']}/vault/credentials/999999/reveal")
    assert res.status_code == 404


def test_reveal_credential_wrong_project(client):
    """reveal_credential returns 404 when credential belongs to another project."""
    _setup_encryption()
    project1 = _project(client, "Project One")
    project2 = _project(client, "Project Two")
    cred = _credential(client, project1["id"])
    res = client.get(f"/api/projects/{project2['id']}/vault/credentials/{cred['id']}/reveal")
    assert res.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# get_credential — 404 paths
# ──────────────────────────────────────────────────────────────────────────────

def test_get_credential_wrong_project(client):
    """get_credential returns 404 when credential belongs to another project."""
    _setup_encryption()
    project1 = _project(client, "P1")
    project2 = _project(client, "P2")
    cred = _credential(client, project1["id"])
    res = client.get(f"/api/projects/{project2['id']}/vault/credentials/{cred['id']}")
    assert res.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# update_credential
# ──────────────────────────────────────────────────────────────────────────────

def test_update_credential_not_found(client):
    """update_credential returns 404 for unknown credential."""
    project = _project(client)
    res = client.put(
        f"/api/projects/{project['id']}/vault/credentials/999999",
        json={"username": "new@example.com"},
    )
    assert res.status_code == 404


def test_update_credential_wrong_project(client):
    """update_credential returns 404 for credential in another project."""
    _setup_encryption()
    project1 = _project(client, "U1")
    project2 = _project(client, "U2")
    cred = _credential(client, project1["id"])
    res = client.put(
        f"/api/projects/{project2['id']}/vault/credentials/{cred['id']}",
        json={"username": "attacker@example.com"},
    )
    assert res.status_code == 404


def test_update_credential_success(client):
    """update_credential updates fields successfully."""
    _setup_encryption()
    project = _project(client)
    cred = _credential(client, project["id"])
    res = client.put(
        f"/api/projects/{project['id']}/vault/credentials/{cred['id']}",
        json={"username": "updated@example.com", "description": "Updated desc"},
    )
    assert res.status_code == 200
    assert res.json()["username"] == "updated@example.com"


# ──────────────────────────────────────────────────────────────────────────────
# delete_credential
# ──────────────────────────────────────────────────────────────────────────────

def test_delete_credential_wrong_project(client):
    """delete_credential returns 404 for credential in another project."""
    _setup_encryption()
    project1 = _project(client, "D1")
    project2 = _project(client, "D2")
    cred = _credential(client, project1["id"])
    res = client.delete(f"/api/projects/{project2['id']}/vault/credentials/{cred['id']}")
    assert res.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Test data CRUD — missing branches
# ──────────────────────────────────────────────────────────────────────────────

def test_get_test_data_not_found(client):
    """get_test_data returns 404 for unknown ID."""
    project = _project(client)
    res = client.get(f"/api/projects/{project['id']}/vault/test-data/999999")
    assert res.status_code == 404


def test_get_test_data_wrong_project(client):
    """get_test_data returns 404 for test data in another project."""
    project1 = _project(client, "TD1")
    project2 = _project(client, "TD2")
    td_res = client.post(
        f"/api/projects/{project1['id']}/vault/test-data",
        json={
            "project_id": project1["id"],
            "name": "seed",
            "description": "d",
            "data": json.dumps({"k": "v"}),
            "tags": "[]",
            "environment_id": None,
        },
    )
    assert td_res.status_code == 200
    td_id = td_res.json()["id"]
    res = client.get(f"/api/projects/{project2['id']}/vault/test-data/{td_id}")
    assert res.status_code == 404


def test_update_test_data_not_found(client):
    """update_test_data returns 404 for unknown ID."""
    project = _project(client)
    res = client.put(
        f"/api/projects/{project['id']}/vault/test-data/999999",
        json={"description": "New"},
    )
    assert res.status_code == 404


def test_update_test_data_wrong_project(client):
    """update_test_data returns 404 for test data in another project."""
    project1 = _project(client, "TU1")
    project2 = _project(client, "TU2")
    td_res = client.post(
        f"/api/projects/{project1['id']}/vault/test-data",
        json={
            "project_id": project1["id"],
            "name": "data1",
            "description": "d",
            "data": json.dumps({"x": 1}),
            "tags": "[]",
            "environment_id": None,
        },
    )
    td_id = td_res.json()["id"]
    res = client.put(
        f"/api/projects/{project2['id']}/vault/test-data/{td_id}",
        json={"description": "Hack"},
    )
    assert res.status_code == 404


def test_delete_test_data_not_found(client):
    """delete_test_data returns 404 for unknown ID."""
    project = _project(client)
    res = client.delete(f"/api/projects/{project['id']}/vault/test-data/999999")
    assert res.status_code == 404


def test_delete_test_data_wrong_project(client):
    """delete_test_data returns 404 for test data in another project."""
    project1 = _project(client, "TX1")
    project2 = _project(client, "TX2")
    td_res = client.post(
        f"/api/projects/{project1['id']}/vault/test-data",
        json={
            "project_id": project1["id"],
            "name": "data_x",
            "description": "d",
            "data": json.dumps({"z": 0}),
            "tags": "[]",
            "environment_id": None,
        },
    )
    td_id = td_res.json()["id"]
    res = client.delete(f"/api/projects/{project2['id']}/vault/test-data/{td_id}")
    assert res.status_code == 404


def test_test_data_project_id_mismatch(client):
    """create_test_data returns 400 when project_id in body mismatches URL."""
    project = _project(client)
    res = client.post(
        f"/api/projects/{project['id']}/vault/test-data",
        json={
            "project_id": project["id"] + 1,
            "name": "mismatch",
            "description": "d",
            "data": "{}",
            "tags": "[]",
        },
    )
    assert res.status_code == 400


def test_list_credentials_with_environment_filter(client):
    """list_credentials with environment_id filter returns only matching entries."""
    _setup_encryption()
    project = _project(client)

    # Create environment
    env_res = client.post(
        f"/api/projects/{project['id']}/environments",
        json={
            "project_id": project["id"],
            "name": "Staging",
            "base_url": "https://staging.example.com",
            "variables": {},
        },
    )
    assert env_res.status_code == 200
    env_id = env_res.json()["id"]

    # Create credential with environment
    client.post(
        f"/api/projects/{project['id']}/vault/credentials",
        json={
            "project_id": project["id"],
            "name": "env-cred",
            "credential_type": "login",
            "password": "secret",
            "environment_id": env_id,
        },
    )

    # Create credential without environment (global)
    client.post(
        f"/api/projects/{project['id']}/vault/credentials",
        json={
            "project_id": project["id"],
            "name": "global-cred",
            "credential_type": "login",
            "password": "global-secret",
            "environment_id": None,
        },
    )

    # Filter by environment — should return env-specific + globals
    res = client.get(
        f"/api/projects/{project['id']}/vault/credentials?environment_id={env_id}"
    )
    assert res.status_code == 200
    names = [c["name"] for c in res.json()]
    assert "env-cred" in names
    assert "global-cred" in names
